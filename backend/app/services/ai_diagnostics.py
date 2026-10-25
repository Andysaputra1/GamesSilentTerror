"""Request/response diagnostics scoped to one async call; credentials are never recorded."""

from contextlib import contextmanager
from contextvars import ContextVar
from time import perf_counter
from urllib.parse import urlsplit

_trace = ContextVar("ai_diagnostic_trace", default=None)


def public_data(value, depth=0):
    """Bound payload size and redact credential fields while retaining token counts."""
    if depth > 12:
        return "[truncated]"
    if isinstance(value, dict):
        return {
            str(key): (
                "[REDACTED]"
                if any(
                    word in str(key).lower()
                    for word in (
                        "password",
                        "authorization",
                        "cookie",
                        "api_key",
                        "secret",
                        "access_token",
                        "refresh_token",
                    )
                )
                else public_data(item, depth + 1)
            )
            for key, item in list(value.items())[:80]
        }
    if isinstance(value, (list, tuple)):
        return [public_data(item, depth + 1) for item in value[:50]]
    if isinstance(value, str):
        return value if len(value) <= 24000 else value[:24000] + "\n[truncated]"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return type(value).__name__


@contextmanager
def measure(trace, step):
    started = perf_counter()
    try:
        yield
    finally:
        if trace is not None:
            trace.setdefault("timings", {})[step] = round((perf_counter() - started) * 1000, 2)


@contextmanager
def capture_exchange(trace):
    token = _trace.set(trace)
    try:
        with measure(trace, "llm_ms"):
            yield
    except BaseException as error:
        if trace is not None:
            if not isinstance(trace.get("response"), dict):
                trace["response"] = {}
            trace["response"]["error_type"] = type(error).__name__
        raise
    finally:
        _trace.reset(token)


def record_request(url, body):
    trace = _trace.get()
    if trace is not None:
        parsed = urlsplit(url)
        endpoint = f"{parsed.scheme}://{parsed.hostname}"
        if parsed.port:
            endpoint += f":{parsed.port}"
        trace["request"] = {
            "method": "POST",
            "endpoint": endpoint + parsed.path,
            "body": public_data(body),
            "credentials": "Header autentikasi tidak dicatat.",
        }
        if isinstance(body.get("input"), str):
            trace["prompt"] = body["input"]
        elif body.get("messages"):
            trace["prompt"] = body["messages"][-1].get("content")


def record_response(status, body=None):
    trace = _trace.get()
    if trace is not None:
        # Never store upstream error bodies; they may echo sensitive request headers.
        trace["response"] = {"status_code": status}
        if body is not None and 200 <= status < 300:
            trace["response"]["body"] = public_data(body)

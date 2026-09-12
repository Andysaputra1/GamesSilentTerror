"""Jejak fungsi opt-in, bukan profiler seluruh Python. Hanya dibaca admin."""
from collections import deque
from copy import deepcopy
from datetime import datetime, timezone
from functools import wraps
from inspect import signature
from threading import RLock
from time import perf_counter
from uuid import uuid4


def safe(value, depth=0):
    # Pertahanan tambahan: header/credential tidak boleh menjadi field log.
    if depth > 5:
        return '[truncated]'
    if isinstance(value, dict):
        return {str(k): '[REDACTED]' if any(word in str(k).lower() for word in
                ['password', 'token', 'authorization', 'cookie', 'api_key', 'secret']) else safe(v, depth+1)
                for k, v in list(value.items())[:50]}
    if isinstance(value, (list, tuple)):
        return [safe(v, depth+1) for v in value[:50]]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return str(value)[:4000]


class ActivityService:
    def __init__(self):
        self.events = deque(maxlen=2000)
        self.lock = RLock()

    def record(self, room, function, params=None, *, status='complete', result=None, duration_ms=None, call_id=None):
        event = {'id':uuid4().hex, 'call_id':call_id, 'at':datetime.now(timezone.utc).isoformat(),
                 'room':room, 'function':function, 'params':safe(params or {}), 'status':status,
                 'result':safe(result), 'duration_ms':duration_ms}
        with self.lock:
            self.events.appendleft(event)

    def list(self, code=None):
        with self.lock:
            return deepcopy([e for e in self.events if code is None or e['room'] == code][:200])


activity = ActivityService()


def traced(function):
    # Decorator merekam command room, tanpa spam polling snapshot/health.
    @wraps(function)
    def wrapped(*args, **kwargs):
        params = dict(signature(function).bind(*args, **kwargs).arguments)
        params.pop('self', None)
        code = params.get('code')
        call_id = uuid4().hex
        start = perf_counter()
        activity.record(code, function.__qualname__, params, status='running', call_id=call_id)
        try:
            result = function(*args, **kwargs)
        except Exception as error:
            activity.record(code, function.__qualname__, params, status='error', result=type(error).__name__,
                            duration_ms=round((perf_counter()-start)*1000, 2), call_id=call_id)
            raise
        code = code or getattr(result, 'code', None)
        if isinstance(result, dict):
            code = code or result.get('code')
            summary = {'phase':result.get('game', result).get('phase'), 'ok':True}
        else:
            summary = {'ok':True}
        activity.record(code, function.__qualname__, params, result=summary,
                        duration_ms=round((perf_counter()-start)*1000, 2), call_id=call_id)
        return result
    return wrapped

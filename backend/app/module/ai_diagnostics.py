"""Pengukur lama satu tahap untuk jejak panel."""

from contextlib import contextmanager
from time import perf_counter


@contextmanager
def measure(trace, step):
    started = perf_counter()
    try:
        yield
    finally:
        if trace is not None:
            trace.setdefault("timings", {})[step] = round((perf_counter() - started) * 1000, 2)

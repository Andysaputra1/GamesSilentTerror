"""Batas percobaan in-memory untuk development satu worker. Jangan percaya X-Forwarded-For."""
from collections import OrderedDict, deque
from threading import RLock
from time import monotonic
from fastapi import HTTPException, Request

_attempts = OrderedDict()
_lock = RLock()


def limit_auth(request: Request):
    key = (request.client.host if request.client else 'unknown', request.url.path)
    now = monotonic()
    with _lock:
        attempts = _attempts.setdefault(key, deque())
        while attempts and attempts[0] < now - 60:
            attempts.popleft()
        if len(attempts) >= 15:
            raise HTTPException(429, 'Terlalu banyak percobaan. Tunggu satu menit.', headers={'Retry-After': '60'})
        attempts.append(now)
        _attempts.move_to_end(key)
        while len(_attempts) > 2000:
            _attempts.popitem(last=False)

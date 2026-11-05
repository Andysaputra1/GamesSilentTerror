"""Batas percobaan in-memory untuk satu worker.

Kunci = IP klien dari uvicorn. Di Azure, uvicorn memakai --proxy-headers sehingga IP ini berasal dari
X-Forwarded-For yang ditulis Caddy; header itu tidak boleh dibaca langsung di sini karena bisa dipalsukan
bila backend dibuka tanpa proxy.
"""

from collections import OrderedDict, deque
from threading import RLock
from time import monotonic
from fastapi import HTTPException, Request

_riwayat_percobaan = OrderedDict()
_kunci_thread = RLock()


# Batasi frekuensi percobaan autentikasi per alamat klien dalam jendela waktu.
def limit_auth(request: Request):
    klien_dan_path = (request.client.host if request.client else "unknown", request.url.path)
    waktu_sekarang = monotonic()
    with _kunci_thread:
        attempts = _riwayat_percobaan.setdefault(klien_dan_path, deque())
        # Buang percobaan yang sudah di luar jendela 60 detik.
        while attempts and attempts[0] < waktu_sekarang - 60:
            attempts.popleft()
        if len(attempts) >= 15:
            raise HTTPException(
                429, "Terlalu banyak percobaan. Tunggu satu menit.", headers={"Retry-After": "60"}
            )
        attempts.append(waktu_sekarang)
        # Klien yang paling lama diam dibuang lebih dulu agar memori tidak tumbuh tanpa batas.
        _riwayat_percobaan.move_to_end(klien_dan_path)
        while len(_riwayat_percobaan) > 2000:
            _riwayat_percobaan.popitem(last=False)

"""Jejak fungsi opt-in, bukan profiler seluruh Python. Hanya dibaca admin."""

from collections import deque
from copy import deepcopy
from datetime import datetime, timezone
from functools import wraps
from inspect import signature
from threading import RLock
from time import perf_counter
from uuid import uuid4


# Redaksi field rahasia dan batasi ukuran/nesting data sebelum masuk jejak aktivitas.
def _saring_data_jejak(nilai, kedalaman=0):
    if kedalaman > 5:
        return "[truncated]"
    if isinstance(nilai, dict):
        # Field berisi kata ini tidak boleh masuk log: header dan credential.
        kata_rahasia = ("password", "token", "authorization", "cookie", "api_key", "secret")
        return {
            str(kunci): (
                "[REDACTED]"
                if any(kata in str(kunci).lower() for kata in kata_rahasia)
                else _saring_data_jejak(isi, kedalaman + 1)
            )
            for kunci, isi in list(nilai.items())[:50]
        }
    if isinstance(nilai, (list, tuple)):
        return [_saring_data_jejak(isi, kedalaman + 1) for isi in nilai[:50]]
    if nilai is None or isinstance(nilai, (bool, int, float)):
        return nilai
    return str(nilai)[:4000]


class ActivityService:
    # Siapkan riwayat terbatas di memori dan lock untuk akses bersamaan.
    def __init__(self):
        self.events = deque(maxlen=2000)
        self.lock = RLock()

    # Catat satu tahap pemanggilan fungsi setelah parameter dan hasil disanitasi.
    def record(
        self,
        room,
        function,
        params=None,
        *,
        status="complete",
        result=None,
        duration_ms=None,
        call_id=None,
    ):
        catatan = {
            "id": uuid4().hex,
            "call_id": call_id,
            "at": datetime.now(timezone.utc).isoformat(),
            "room": room,
            "function": function,
            "params": _saring_data_jejak(params or {}),
            "status": status,
            "result": _saring_data_jejak(result),
            "duration_ms": duration_ms,
        }
        with self.lock:
            self.events.appendleft(catatan)

    # Kembalikan salinan maksimal 200 event agar pemanggil tidak mengubah arsip.
    def list(self, code=None):
        with self.lock:
            return deepcopy(
                [catatan for catatan in self.events if code is None or catatan["room"] == code][
                    :200
                ]
            )


activity = ActivityService()


# Bungkus command ruangan dengan pencatatan awal, hasil, error, dan durasi; polling tidak dibungkus.
def traced(fungsi):
    @wraps(fungsi)
    def fungsi_tercatat(*args, **kwargs):
        parameter = dict(signature(fungsi).bind(*args, **kwargs).arguments)
        parameter.pop("self", None)
        kode_room = parameter.get("code")
        id_panggilan = uuid4().hex
        waktu_mulai = perf_counter()
        activity.record(
            kode_room, fungsi.__qualname__, parameter, status="running", call_id=id_panggilan
        )
        try:
            hasil = fungsi(*args, **kwargs)
        except Exception as error:
            activity.record(
                kode_room,
                fungsi.__qualname__,
                parameter,
                status="error",
                result=type(error).__name__,
                duration_ms=round((perf_counter() - waktu_mulai) * 1000, 2),
                call_id=id_panggilan,
            )
            raise
        # Command create tidak menerima kode room; kodenya baru diketahui dari hasil.
        kode_room = kode_room or getattr(hasil, "code", None)
        if isinstance(hasil, dict):
            kode_room = kode_room or hasil.get("code")
            ringkasan = {"phase": hasil.get("game", hasil).get("phase"), "ok": True}
        else:
            ringkasan = {"ok": True}
        activity.record(
            kode_room,
            fungsi.__qualname__,
            parameter,
            result=ringkasan,
            duration_ms=round((perf_counter() - waktu_mulai) * 1000, 2),
            call_id=id_panggilan,
        )
        return hasil

    return fungsi_tercatat

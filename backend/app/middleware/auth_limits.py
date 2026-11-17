"""Batas percobaan in-memory untuk satu worker: login, daftar, Google, gabung room, dan chat.

Kunci IP = IP klien dari uvicorn. Di Azure, uvicorn memakai --proxy-headers sehingga IP ini berasal dari
X-Forwarded-For yang ditulis Caddy; header itu tidak boleh dibaca langsung di sini karena bisa dipalsukan
bila backend dibuka tanpa proxy.
"""

from collections import OrderedDict, deque
from math import ceil
from threading import RLock
from time import monotonic
from fastapi import HTTPException, Request

PESAN_TERLALU_BANYAK = "Terlalu banyak percobaan. Tunggu satu menit."


class BatasPercobaan:
    """Paling banyak `batas` percobaan per kunci dalam `jendela_detik`. Hanya di memori, hilang saat restart."""

    # Kunci yang paling lama diam dibuang lebih dulu bila jumlahnya lewat maks_kunci, agar memori tidak tumbuh.
    def __init__(self, batas, jendela_detik, pesan=PESAN_TERLALU_BANYAK, maks_kunci=2000):
        self.batas = batas
        self.jendela = jendela_detik
        self.pesan = pesan
        self.maks_kunci = maks_kunci
        self.riwayat = OrderedDict()
        self.kunci_thread = RLock()

    # Detik sampai kunci boleh mencoba lagi; 0 berarti boleh sekarang. Percobaan di luar jendela dibuang dulu.
    def sisa_tunggu(self, kunci):
        waktu_sekarang = monotonic()
        with self.kunci_thread:
            percobaan = self.riwayat.get(kunci)
            if not percobaan:
                return 0
            while percobaan and percobaan[0] <= waktu_sekarang - self.jendela:
                percobaan.popleft()
            if len(percobaan) < self.batas:
                return 0
            return percobaan[0] + self.jendela - waktu_sekarang

    # Catat satu percobaan untuk kunci ini.
    def catat(self, kunci):
        with self.kunci_thread:
            self.riwayat.setdefault(kunci, deque()).append(monotonic())
            self.riwayat.move_to_end(kunci)
            while len(self.riwayat) > self.maks_kunci:
                self.riwayat.popitem(last=False)

    # Lupakan semua percobaan kunci ini (mis. login yang akhirnya berhasil).
    def hapus(self, kunci):
        with self.kunci_thread:
            self.riwayat.pop(kunci, None)

    # Tolak dengan HTTP 429 bila kunci sudah mencapai batas.
    def tolak_bila_penuh(self, kunci):
        tunggu = self.sisa_tunggu(kunci)
        if tunggu > 0:
            raise HTTPException(429, self.pesan, headers={"Retry-After": str(ceil(tunggu))})

    # Tolak bila penuh, selain itu catat percobaan ini (satu langkah di bawah kunci, jadi dua thread tidak lolos bersama).
    def tolak_atau_catat(self, kunci):
        with self.kunci_thread:
            self.tolak_bila_penuh(kunci)
            self.catat(kunci)


class BatasPerIp(BatasPercobaan):
    """Dependency FastAPI: percobaan dihitung per (IP klien, path)."""

    def __call__(self, request: Request):
        self.tolak_atau_catat(
            (request.client.host if request.client else "unknown", request.url.path)
        )


# Panel admin dan cek penulis: sedikit orang, jadi ketat.
limit_auth = BatasPerIp(15, 60)
# Login, daftar, dan Google pemain: satu lab atau Wi-Fi kampus berbagi satu IP NAT, jadi lebih longgar. Tebakan password
# satu akun ditahan batas_gagal_login, bukan batas ini.
limit_auth_pemain = BatasPerIp(60, 60)
# Password salah per akun (isian username/email yang dirapikan), dari IP mana pun.
batas_gagal_login = BatasPercobaan(
    10, 15 * 60, "Terlalu banyak password salah untuk akun ini. Coba lagi 15 menit lagi."
)

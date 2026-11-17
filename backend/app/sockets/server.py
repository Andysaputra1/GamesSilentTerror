"""
Membuat sio dan mengirim pesan ke room. Modul lain cukup mengimpor sio dan emit_room dari sini.

Alurnya
1. Saat berkas ini diimpor, sio dibuat. Event dari browser didaftarkan chat.py, lalu main.py memasang sio ke aplikasi
2. emit_room: Periksa ulang semua sambungan di room, keluarkan yang tidak sah, lewati yang belum bisa dicek, lalu kirim pesannya

Cek token ke MySQL berjalan di thread, bukan di event loop, dan hasilnya dipakai ulang beberapa detik per sambungan.
"""

from __future__ import annotations

import asyncio
import logging
import time
import weakref

import socketio
from app.config.database import PersistenceError
from app.config.settings import settings
from app.services.auth_service import SessionValidationError, auth_service
from app.services.room_service import Room, room_service

logger = logging.getLogger("shadow_heist.socket")

sio = socketio.AsyncServer(async_mode="asgi", cors_allowed_origins=settings.allowed_origins)

# Catatan tiap sambungan aktif, {sid: {username, token, room, dicek}}. Hanya di memori, jadi hilang saat server restart.
# `sid` = nomor sambungan, dibuat Socket.IO. `dicek` = waktu (monotonic) token terakhir terbukti sah.
sockets: dict[str, dict] = {}
# Hasil cek token dipakai ulang selama ini (detik): siaran ke room ramai tidak lagi menanyai MySQL sekali per
# sambungan per pesan. Akibatnya logout atau sesi yang dicabut paling lambat berlaku sesudah selang ini.
TOKEN_BERLAKU_DETIK = 5.0
# Satu kunci siaran per room. Cek token bisa menunggu thread, jadi tanpa kunci pesan yang disiarkan belakangan bisa
# mendahului pesan sebelumnya. Kunci hilang sendiri saat tidak ada siaran yang memakainya.
_kunci_siaran: weakref.WeakValueDictionary[str, asyncio.Lock] = weakref.WeakValueDictionary()


# Username pemilik token sambungan. Token yang baru saja terbukti sah tidak dicek ulang; selain itu dicek ke MySQL di
# thread supaya event loop (jam, bot, semua room) tidak ikut menunggu database.
async def cek_token_socket(socket: dict) -> str:
    if time.monotonic() - socket.get("dicek", float("-inf")) < TOKEN_BERLAKU_DETIK:
        return socket["username"]
    akun = await asyncio.to_thread(auth_service.check_user_by_token, socket["token"])
    if akun.username == socket["username"]:
        socket["dicek"] = time.monotonic()
    return akun.username


# Cocokkan identitas dengan sesi login socket dan pastikan masih anggota ruangan. Hasil: room-nya.
async def verifikasi_socket(sid: str, username: str) -> Room:
    socket = sockets.get(sid)
    if socket is None:
        raise ValueError("Login diperlukan sebelum masuk ke game.")
    if username != socket["username"]:
        raise ValueError("Identitas pemain tidak sesuai dengan sesi login.")

    # Token handshake diperiksa lagi supaya logout/expiry mencabut akses chat.
    # PersistenceError sengaja diteruskan: database gagal bukan berarti sesi pemain berakhir.
    try:
        if await cek_token_socket(socket) != socket["username"]:
            raise ValueError("Sesi login berubah. Silakan sambungkan ulang.")
    except SessionValidationError as error:
        raise ValueError("Sesi login berakhir. Silakan login ulang.") from error

    return room_service.get(socket["room"], socket["username"])


async def emit_room(event, data, *, to):
    """Cabut penerima lama sebelum broadcast, termasuk socket pasif setelah logout/leave."""
    kunci = _kunci_siaran.get(to)
    if kunci is None:
        kunci = _kunci_siaran[to] = asyncio.Lock()
    async with kunci:
        dilewati = []
        for sid, socket in list(sockets.items()):
            if socket["room"] != to:
                continue
            try:
                await verifikasi_socket(sid, socket["username"])
            except ValueError:
                # Sesi berakhir atau sudah keluar room: catatannya ikut dibuang, jadi tidak dicek ulang tiap siaran.
                sockets.pop(sid, None)
                await sio.leave_room(sid, to)
            except PersistenceError:
                # Gagal tertutup: pesan ini tidak dikirim ke sambungan yang belum bisa dicek. Sambungannya tetap di
                # kanal, jadi siaran berikutnya sampai lagi begitu database pulih.
                logger.warning("Token socket %s belum bisa dicek; siaran ini dilewati.", sid)
                dilewati.append(sid)
        await sio.emit(event, data, to=to, skip_sid=dilewati or None)

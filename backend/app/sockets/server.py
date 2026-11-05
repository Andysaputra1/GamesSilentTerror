"""
Membuat sio dan mengirim pesan ke room. Modul lain cukup mengimpor sio dan emit_room dari sini.

Alurnya
1. Saat berkas ini diimpor, sio dibuat. Event dari browser didaftarkan chat.py, lalu main.py memasang sio ke aplikasi
2. emit_room: Periksa ulang semua sambungan di room, keluarkan yang tidak sah, lalu kirim pesannya
"""

from __future__ import annotations

import logging

import socketio
from app.config.database import PersistenceError
from app.config.settings import settings
from app.services.auth_service import SessionValidationError, auth_service
from app.services.room_service import Room, room_service

logger = logging.getLogger("shadow_heist.socket")

sio = socketio.AsyncServer(async_mode="asgi", cors_allowed_origins=settings.allowed_origins)

# Catatan tiap sambungan aktif, {sid: {username, token, room}}. Hanya di memori, jadi hilang saat server restart.
# `sid` = nomor sambungan, dibuat Socket.IO.
sockets: dict[str, dict[str, str]] = {}


# Cocokkan identitas dengan sesi login socket dan pastikan masih anggota ruangan. Hasil: room-nya.
def verifikasi_socket(sid: str, username: str) -> Room:
    socket = sockets.get(sid)
    if socket is None:
        raise ValueError("Login diperlukan sebelum masuk ke game.")
    if username != socket["username"]:
        raise ValueError("Identitas pemain tidak sesuai dengan sesi login.")

    # Token handshake diperiksa lagi supaya logout/expiry mencabut akses chat.
    # PersistenceError sengaja diteruskan: database gagal bukan berarti sesi pemain berakhir.
    try:
        akun = auth_service.check_user_by_token(socket["token"])
        if akun.username != socket["username"]:
            raise ValueError("Sesi login berubah. Silakan sambungkan ulang.")
    except SessionValidationError as error:
        raise ValueError("Sesi login berakhir. Silakan login ulang.") from error

    return room_service.get(socket["room"], socket["username"])


async def emit_room(event, data, *, to):
    """Cabut penerima lama sebelum broadcast, termasuk socket pasif setelah logout/leave."""
    for sid, socket in list(sockets.items()):
        if socket["room"] != to:
            continue
        try:
            verifikasi_socket(sid, socket["username"])
        except ValueError:
            await sio.leave_room(sid, to)
        except PersistenceError:
            # Dikeluarkan di sini berarti pemain berhenti menerima chat sampai menyambung ulang.
            logger.warning("Token socket %s belum bisa dicek; tetap di kanal %s.", sid, to)
    await sio.emit(event, data, to=to)

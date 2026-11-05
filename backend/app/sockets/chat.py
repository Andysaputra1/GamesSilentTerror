"""
Menerima event Socket.IO dari browser pemain, lalu mengirim hasilnya ke room.

Alurnya
1. Saat berkas ini diimpor, event connect, disconnect, send_chat didaftarkan ke sio
2. connect: Cek token login dan room, catat socket ini milik siapa, masuk kanal room
3. send_chat: Serahkan ke chat_service; kalau ditolak, kirim system_alert ke pengirim
4. disconnect: Hapus catatan socket (keanggotaan lobby dan data MySQL tetap)

Chat bot tidak lewat send_chat. Bot hanya memakai emit_room di server.py untuk mengirim pesannya ke room.
"""

from __future__ import annotations

import logging
from typing import Any

import socketio
from app.config.database import PersistenceError
from app.services.auth_service import SessionValidationError, auth_service
from app.services.chat_service import ChatDitolak, kirim_chat_pemain
from app.services.room_service import room_service
from app.sockets.server import sio, sockets

logger = logging.getLogger("shadow_heist.socket")


# Jalan saat browser menyambung: mengecek siapa yang masuk dan ke room mana, sebelum sambungan boleh menerima chat.
# auth = data dari browser (token, room_code). environ tidak dipakai, tapi wajib ada karena Socket.IO mengirimnya.
async def connect(sid: str, environ: dict[str, Any], auth: Any = None) -> None:
    token = str(auth.get("token", "")) if isinstance(auth, dict) else ""
    try:
        akun = auth_service.check_user_by_token(token)
    except (SessionValidationError, PersistenceError) as error:
        raise socketio.exceptions.ConnectionRefusedError("Login diperlukan.") from error
    try:
        kode_room = str(auth.get("room_code", ""))
        room_service.get(kode_room, akun.username)
    except ValueError as error:
        logger.info("Koneksi Socket ditolak untuk %s: %s", sid, error)
        raise socketio.exceptions.ConnectionRefusedError("Ruangan tidak valid.") from error

    kode_room = kode_room.strip().upper()
    # Token ikut dicatat karena dicek ulang tiap chat, jadi pemain yang sudah logout tidak bisa terus chat lewat sambungan lama.
    sockets[sid] = {"username": akun.username, "token": token, "room": kode_room}
    await sio.enter_room(sid, kode_room)
    logger.info("Pemain terkoneksi ke Socket: %s", sid)


# Jalan saat browser terputus: hanya menghapus catatan sambungan.
# Keanggotaan room tetap, jadi pemain yang memuat ulang halaman bisa kembali ke room yang sama.
async def disconnect(sid: str) -> None:
    sockets.pop(sid, None)
    logger.info("Pemain keluar dari Socket: %s", sid)


# Jalan saat pemain mengirim chat. Semua tahapnya ada di chat_service; di sini hanya penolakannya yang dikirim balik.
async def send_chat(sid: str, data: dict[str, Any]) -> None:
    try:
        await kirim_chat_pemain(sid, data)
    except ChatDitolak as error:
        await sio.emit("system_alert", {"msg": str(error)}, to=sid)


sio.on("connect", connect)
sio.on("disconnect", disconnect)
sio.on("send_chat", send_chat)

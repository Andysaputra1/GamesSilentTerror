"""
Membangun Server HTTP, Mengkoneksi dengan Socket.IO,Mengatur Jam Server dan mengatur bot NPC.

Alurnya 
1. Memasang Socket.IO (dibuat di sockets/server.py, event-nya di sockets/chat.py)
2. Membangun Server (Koneksi ke DB, Konfigurasi AI, Konfigurasi NPC, Memuat Otak AI, Menyalakan Jam (cek terus setiap 0.5 Detik))

Jadinya AI Mulai Mikir dari Sini (isi pikirannya di module/npc_service.py)
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, suppress
import logging

import socketio
from fastapi import FastAPI

from app.config.settings import settings
from app.controllers.routes import api_router
from app.middleware.cors import configure_cors
from app.services.ai_config_service import muat_konfigurasi_ai
from app.config.database import engine, database_is_ready
from app.module.npc_brain.runtime import brain_runtime
from app.services.npc_config_service import muat_konfigurasi_npc
from app.module.npc_service import npc_service
from app.module.persistence_service import PersistenceError
from app.services.room_service import room_service
# Cukup diimpor: chat.py mendaftarkan event connect, disconnect, dan send_chat ke sio.
from app.sockets import chat  # noqa: F401
from app.sockets.server import sio

@asynccontextmanager
async def lifespan(_: FastAPI):
    # setiap 0.5 detik jalankan pengcekan fase dan bot
    async def game_clock():
        while True:
            try:
                # ganti fase yang waktunya habis
                room_service.perbarui_fase_semua_room()
                # jalankan bot yang sudah waktunya
                npc_service.jalankan_bot_yang_sudah_waktunya()
            except Exception:
                logger.exception("Satu putaran jam permainan gagal.")
            # tunggu 0,5 detik
            await asyncio.sleep(0.5)
    
    
    if database_is_ready():
        logger.info("Koneksi MySQL siap.")
        try:
            # API key, token, dan link LLM yang disimpan lewat panel dibaca dari DB ke memori,
            # supaya tidak hilang saat server restart.
            muat_konfigurasi_ai()
        except PersistenceError as error:
            logger.error("Konfigurasi AI panel gagal dimuat; memakai .env: %s", error)
        try:
            # Pengaturan Otak NPC dari panel (penulis kalimat dan model) dibaca dari DB ke otak bot.
            muat_konfigurasi_npc()
        except PersistenceError as error:
            logger.warning("Konfigurasi Otak NPC panel gagal dimuat; memakai .env: %s", error)
    else:
        logger.error("Koneksi awal MySQL gagal.")


    # memasukan Indobert, Fuzzy , NLG 
    brain_runtime.mulai_memuat()

    # Jam jalan sebagai tugas latar, supaya tetap berdetak sambil server melayani pemain.
    clock = asyncio.create_task(game_clock())
    try:
        yield
    finally:
        # Server mati: hentikan jam, batalkan giliran bot yang masih jalan, tutup thread otak, tutup koneksi MySQL.
        clock.cancel()
        with suppress(asyncio.CancelledError):
            await clock
        await npc_service.close()
        brain_runtime.tutup()
        engine.dispose()


# Menyiapkan pencatat log. File lain memakai anak dari nama ini (mis. shadow_heist.auth), jadi pesannya ikut aturan yang sama.
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("shadow_heist")

# Bangun FastAPI dan daftarkan lifespan(Koneksi ke DB, Konfigurasi AI, Konfigurasi NPC, Memuat Otak AI, Menyalakan Jam (cek terus setiap 0.5 Detik)).
# Lifespan baru jalan saat Uvicorn menyalakan server.
app = FastAPI(title=settings.app_name, lifespan=lifespan)

configure_cors(app)
app.include_router(api_router)

# Socket.IO: jalur yang tetap terbuka antara server dan browser, jadi server bisa mengirim chat kapan saja.
# Di sini hanya persiapan: connect, disconnect, dan send_chat baru jalan saat ada pemain.
asgi_app = socketio.ASGIApp(sio, other_asgi_app=app)

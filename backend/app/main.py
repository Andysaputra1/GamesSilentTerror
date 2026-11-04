"""
Membangun Server HTTP, Mengkoneksi dengan Socket.IO,Mengatur Jam Server dan mengatur bot NPC.

Alurnya 
1. Membangun Socket.IO
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
from app.controller.controller_main import api_router
from app.controller.middleware.cors import configure_cors
from app.controller.realtime.socket_handlers import register_socket_handlers
from app.module.ai_runtime_service import muat_konfigurasi_ai
from app.module.mysql_connector import engine, database_is_ready
from app.module.npc_brain.runtime import brain_runtime
from app.module.npc_config_service import load_npc_configuration
from app.module.npc_service import NPCService
from app.module.persistence_service import PersistenceError
from app.module.room_service import room_service

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
            load_npc_configuration()
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


# Setup Logger
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("shadow_heist")

# Koneksi WebSocket lewat Socket.IO: jalur realtime server dengan browser pemain, bot NPC ikut memakainya.
sio = socketio.AsyncServer(async_mode="asgi", cors_allowed_origins=settings.allowed_origins)
socket_controller = register_socket_handlers(sio)
npc_service = NPCService(sio, broadcast=socket_controller.emit_room)

# Bangun FastAPI dan daftarkan lifespan(Koneksi ke DB, Konfigurasi AI, Konfigurasi NPC, Memuat Otak AI, Menyalakan Jam (cek terus setiap 0.5 Detik)).
# Lifespan baru jalan saat Uvicorn menyalakan server.
app = FastAPI(title=settings.app_name, lifespan=lifespan)

configure_cors(app)
app.include_router(api_router)

asgi_app = socketio.ASGIApp(sio, other_asgi_app=app)

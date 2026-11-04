"""Application composition root for the Shadow Heist Python backend.

FastAPI routes are HTTP controllers; services own use cases and transactions.
Models contain parameterized SQL, modules own infrastructure, and Socket.IO
has its own event controller.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, suppress
import logging

import socketio
from fastapi import FastAPI

from app.controller.controller_main import api_router
from app.controller.middleware.cors import configure_cors
from app.module.ai_runtime_service import muat_konfigurasi_ai
from app.module.mysql_connector import engine, database_is_ready
from app.config.settings import settings
from app.controller.realtime.socket_handlers import register_socket_handlers
from app.module.npc_service import NPCService
from app.module.npc_brain.runtime import brain_runtime
from app.module.npc_config_service import load_npc_configuration
from app.module.persistence_service import PersistenceError
from app.module.room_service import room_service

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("shadow_heist")


# Mengatur hidup server: yang dijalankan saat server nyala dan saat server mati.
# Alur 1 (server nyala): 1 cek MySQL -> 2 muat konfigurasi panel -> 3 muat otak bot di latar -> 4 nyalakan jam
# Alur 2 (server mati): 1 hentikan jam -> 2 batalkan giliran bot -> 3 tutup thread otak -> 4 tutup koneksi MySQL
@asynccontextmanager
async def lifespan(_: FastAPI):
    """Validate connectivity without changing schema."""
    if database_is_ready():
        logger.info("Koneksi MySQL siap.")
        try:
            muat_konfigurasi_ai()
        except PersistenceError as error:
            logger.error("Konfigurasi AI panel gagal dimuat; memakai .env: %s", error)
        try:
            load_npc_configuration()
        except PersistenceError:
            logger.warning("Konfigurasi NPC panel belum tersimpan; memakai nilai .env.")
    else:
        logger.error("Koneksi awal MySQL gagal.")

    # Otak NPC (IndoBERT + fuzzy + NLG) dimuat di latar agar server langsung melayani.
    brain_runtime.mulai_memuat()

    # Jam permainan: tiap 0,5 detik, tidak bergantung pada tab pemain atau kecepatan respons LLM.
    # Alur: 1 ganti fase yang waktunya habis -> 2 jalankan bot yang sudah waktunya -> 3 tunggu 0,5 detik
    async def game_clock():
        while True:
            try:
                room_service.perbarui_fase_semua_room()
                npc_service.jalankan_bot_yang_sudah_waktunya()
            except Exception:
                # Error tak terduga tidak boleh mematikan jam permainan untuk seluruh server.
                logger.exception("Satu putaran jam permainan gagal.")
            await asyncio.sleep(0.5)

    clock = asyncio.create_task(game_clock())
    try:
        yield
    finally:
        clock.cancel()
        with suppress(asyncio.CancelledError):
            await clock
        await npc_service.close()
        brain_runtime.tutup()
        engine.dispose()


app = FastAPI(title=settings.app_name, lifespan=lifespan)
configure_cors(app)
app.include_router(api_router)

# The former Node real-time server is hosted alongside FastAPI on port 8000.
sio = socketio.AsyncServer(async_mode="asgi", cors_allowed_origins=settings.allowed_origins)
socket_controller = register_socket_handlers(sio)
npc_service = NPCService(sio, broadcast=socket_controller.emit_room)

# Uvicorn targets this object so FastAPI and Socket.IO share one backend port.
asgi_app = socketio.ASGIApp(sio, other_asgi_app=app)

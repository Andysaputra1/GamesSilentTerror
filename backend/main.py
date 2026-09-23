"""Application composition root for the Shadow Heist Python backend.

FastAPI routes are HTTP controllers; services own use cases and transactions.
Models contain parameterized SQL, modules own infrastructure, and Socket.IO
has its own event controller.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
import logging
import asyncio
from contextlib import suppress
from services.room_service import room_service

import socketio
from fastapi import FastAPI

from controller.controller_main import api_router
from controller.middleware.cors import configure_cors
from module.mysql_connector import engine, database_is_ready
from config.settings import settings
from realtime.socket_handlers import register_socket_handlers
from services.analysis_service import analysis_service
from services.persistence_service import persistence_service
from services.npc_service import NPCService

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("shadow_heist")


@asynccontextmanager
# LIFECYCLE ASYNC: muat SVM dan cek MySQL saat startup; tutup pool koneksi saat aplikasi berhenti.
async def lifespan(_: FastAPI):
    """Load the classifier and validate connectivity without changing schema."""
    # TAHAP 0: saat backend mulai, muat model SVM dari file ke memori.
    # Ini bukan training/upload; file model harus sudah tersedia di server.
    analysis_service.load_model()
    if database_is_ready():
        logger.info("Koneksi MySQL siap.")
        from services.ai_runtime_service import load_panel_configuration
        from services.persistence_service import PersistenceError

        try:
            load_panel_configuration()
        except PersistenceError:
            logger.error("Konfigurasi panel belum tersedia; jalankan migrasi V6.")
    else:
        logger.error("Koneksi awal MySQL gagal.")

    # Timer server tidak bergantung pada tab pemain atau kecepatan respons LLM.
    async def game_clock():
        while True:
            room_service.tick_all()
            npc_service.schedule()
            await asyncio.sleep(0.5)

    clock = asyncio.create_task(game_clock())
    try:
        yield
    finally:
        clock.cancel()
        with suppress(asyncio.CancelledError):
            await clock
        await npc_service.close()
        engine.dispose()


app = FastAPI(title=settings.app_name, lifespan=lifespan)
configure_cors(app)
app.include_router(api_router)

# The former Node real-time server is hosted alongside FastAPI on port 8000.
sio = socketio.AsyncServer(async_mode="asgi", cors_allowed_origins=settings.allowed_origins)
socket_controller = register_socket_handlers(sio, analysis_service, persistence_service)
npc_service = NPCService(sio)

# Uvicorn targets this object so FastAPI and Socket.IO share one backend port.
asgi_app = socketio.ASGIApp(sio, other_asgi_app=app)

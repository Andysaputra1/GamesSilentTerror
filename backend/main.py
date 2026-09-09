"""Application composition root for the Shadow Heist Python backend.

FastAPI routes are HTTP controllers; services own use cases and transactions.
Models contain parameterized SQL, modules own infrastructure, and Socket.IO
has its own event controller.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
import logging

import socketio
from fastapi import FastAPI

from controller.controller_main import api_router
from controller.middleware.cors import configure_cors
from module.mysql_connector import engine, database_is_ready
from config.settings import settings
from realtime.socket_handlers import register_socket_handlers
from services.analysis_service import analysis_service
from services.persistence_service import persistence_service


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
    else:
        logger.error("Koneksi awal MySQL gagal.")
    yield
    engine.dispose()


app = FastAPI(title=settings.app_name, lifespan=lifespan)
configure_cors(app)
app.include_router(api_router)

# The former Node real-time server is hosted alongside FastAPI on port 8000.
sio = socketio.AsyncServer(async_mode="asgi", cors_allowed_origins=settings.allowed_origins)
socket_controller = register_socket_handlers(sio, analysis_service, persistence_service)

# Uvicorn targets this object so FastAPI and Socket.IO share one backend port.
asgi_app = socketio.ASGIApp(sio, other_asgi_app=app)

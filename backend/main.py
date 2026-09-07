"""Application composition root for the Shadow Heist Python backend.

FastAPI routes are the HTTP controllers, services contain use cases, SQLAlchemy
models map to the versioned MySQL schema, and Socket.IO has its own controller.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
import logging

import socketio
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from api.router import api_router
from config.database import engine
from config.settings import settings
from realtime.socket_handlers import register_socket_handlers
from services.analysis_service import analysis_service
from services.persistence_service import persistence_service


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("shadow_heist")


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Load the classifier and validate connectivity without changing schema."""
    analysis_service.load_model()
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        logger.info("Koneksi MySQL siap.")
    except SQLAlchemyError:
        # Health status still works and reports database_ready=false for diagnostics.
        logger.exception("Koneksi awal MySQL gagal.")
    yield
    engine.dispose()


app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)
app.include_router(api_router)

# The former Node real-time server is hosted alongside FastAPI on port 8000.
sio = socketio.AsyncServer(async_mode="asgi", cors_allowed_origins=settings.allowed_origins)
socket_controller = register_socket_handlers(sio, analysis_service, persistence_service)

# Uvicorn targets this object so FastAPI and Socket.IO share one backend port.
asgi_app = socketio.ASGIApp(sio, other_asgi_app=app)

"""Controller kesehatan sistem."""

import asyncio
from datetime import datetime, timezone

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.bot.bot_controller import brain_runtime
from app.config.database import database_is_ready
from app.config.settings import settings
from app.services import panel_service
from app.services.ollama_client import model_available
from app.services.ai_config_service import ai_runtime

router = APIRouter(tags=["system"])


@router.get("/app-status")
# CONTROLLER HEALTH: laporkan kesiapan database dan provider/model AI tanpa mengirim secret konfigurasi.
# SELECT 1 berjalan di thread: endpoint ini publik, dan MySQL yang lambat tidak boleh menahan event loop.
async def app_status() -> dict[str, object]:
    """Health check retained from the former Express backend."""
    konfigurasi_ai = ai_runtime.current()
    return {
        "app_name": settings.app_name,
        "status": "OK",
        "ai_provider": konfigurasi_ai.ai_provider,
        "ai_model": (
            konfigurasi_ai.ollama_model
            if konfigurasi_ai.ai_provider == "docker"
            else konfigurasi_ai.openrouter_model
        ),
        "ollama_ready": (
            await model_available(config=konfigurasi_ai)
            if konfigurasi_ai.ai_provider == "docker"
            else None
        ),
        "openrouter_configured": bool(konfigurasi_ai.openrouter_api_key_value),
        "database_ready": await asyncio.to_thread(database_is_ready),
        "server_date": datetime.now(timezone.utc),
    }


# Status model IndoBERT dari pemuatan otak NPC: siap, memuat, atau gagal (bot memakai aksi cadangan engine).
def status_indobert():
    status = brain_runtime.ringkasan()
    return "siap" if status["siap"] else "gagal" if status["gagal"] else "memuat"


@router.get("/ready")
# CONTROLLER READY: 200 hanya bila MySQL menjawab dan semua migrasi wajib (sampai migrasi terbaru) sudah tercatat.
# Status IndoBERT ikut dilaporkan tetapi tidak membuat /ready gagal: model dimuat di latar sesudah server nyala, dan
# healthcheck compose memakai endpoint ini. Tanpa memanggil provider AI.
def ready():
    """Cheap deployment readiness; never calls a paid or local AI provider."""
    migrasi_kurang = panel_service.migrasi_kurang()
    siap = migrasi_kurang == []
    return JSONResponse(
        {
            "ready": siap,
            "database": migrasi_kurang is not None,
            "migrasi_kurang": migrasi_kurang or [],
            "indobert": status_indobert(),
        },
        status_code=200 if siap else 503,
    )

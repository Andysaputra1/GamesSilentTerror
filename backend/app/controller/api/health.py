"""Controller kesehatan sistem."""

from datetime import datetime, timezone

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.module.mysql_connector import PersistenceError, database_is_ready, jalankan_transaksi
from app.config.settings import settings
from app.module.ollama_client import model_available
from app.module.ai_runtime_service import ai_runtime

router = APIRouter(tags=["system"])


@router.get("/app-status")
# CONTROLLER HEALTH: laporkan kesiapan database dan provider/model AI tanpa mengirim secret konfigurasi.
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
        "database_ready": database_is_ready(),
        "server_date": datetime.now(timezone.utc),
    }


@router.get("/ready")
# CONTROLLER READY: 200 hanya bila migrasi V5 dan V6 sudah ada; tanpa memanggil provider AI.
def ready():
    """Cheap deployment readiness; never calls a paid or local AI provider."""
    skema_siap = False
    try:
        skema_siap = (
            jalankan_transaksi(
                lambda database: database.execute(
                    text(
                        "SELECT COUNT(*) FROM schema_migrations WHERE version IN ('V5__chat_history','V6__admin_panel')"
                    )
                ).scalar()
            )
            == 2
        )
    except PersistenceError:
        pass
    return JSONResponse(
        {"ready": skema_siap},
        status_code=200 if skema_siap else 503,
    )

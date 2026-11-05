"""Controller kesehatan sistem."""

from datetime import datetime, timezone

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.config.database import database_is_ready
from app.config.settings import settings
from app.services import panel_service
from app.services.ollama_client import model_available
from app.services.ai_config_service import ai_runtime

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
    skema_siap = panel_service.skema_siap()
    return JSONResponse(
        {"ready": skema_siap},
        status_code=200 if skema_siap else 503,
    )

"""System-health controller."""

from datetime import datetime, timezone

from fastapi import APIRouter

from module.mysql_connector import database_is_ready
from config.settings import settings
from services.analysis_service import analysis_service
from module.ollama_client import model_available


router = APIRouter(tags=["system"])


@router.get("/app-status")
# CONTROLLER HEALTH: laporkan kesiapan database, SVM, dan provider/model AI tanpa mengirim secret konfigurasi.
async def app_status() -> dict[str, object]:
    """Health check retained from the former Express backend."""
    return {
        "app_name": settings.app_name,
        "status": "OK",
        "model_ready": analysis_service.model_ready,
        "ai_provider": settings.ai_provider,
        "ai_model": settings.ollama_model if settings.ai_provider == "docker" else settings.openai_model,
        "ollama_ready": await model_available() if settings.ai_provider == "docker" else None,
        "openai_configured": analysis_service.openai_ready,
        "database_ready": database_is_ready(),
        "server_date": datetime.now(timezone.utc),
    }

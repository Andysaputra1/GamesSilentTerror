"""System-health controller."""

from datetime import datetime, timezone

from fastapi import APIRouter

from module.mysql_connector import database_is_ready
from config.settings import settings
from services.analysis_service import analysis_service
from module.ollama_client import model_available
from services.ai_runtime_service import ai_runtime

router = APIRouter(tags=["system"])


@router.get("/app-status")
# CONTROLLER HEALTH: laporkan kesiapan database, SVM, dan provider/model AI tanpa mengirim secret konfigurasi.
async def app_status() -> dict[str, object]:
    """Health check retained from the former Express backend."""
    selected = ai_runtime.current()
    return {
        "app_name": settings.app_name,
        "status": "OK",
        "model_ready": analysis_service.model_ready,
        "ai_provider": selected.ai_provider,
        "ai_model": (
            selected.ollama_model
            if selected.ai_provider == "docker"
            else (
                selected.openrouter_model
                if selected.api_backend == "openrouter"
                else selected.openai_model
            )
        ),
        "ollama_ready": (
            await model_available(config=selected) if selected.ai_provider == "docker" else None
        ),
        "openrouter_configured": bool(selected.openrouter_api_key_value),
        "openai_configured": analysis_service.openai_ready,
        "database_ready": database_is_ready(),
        "server_date": datetime.now(timezone.utc),
    }


@router.get("/ready")
def ready():
    """Cheap deployment readiness; never calls a paid or local AI provider."""
    from fastapi.responses import JSONResponse
    from services.persistence_service import PersistenceService, PersistenceError
    from sqlalchemy import text

    schema_ready = False
    try:
        schema_ready = (
            PersistenceService._run(
                lambda db: db.execute(
                    text(
                        "SELECT COUNT(*) FROM schema_migrations WHERE version IN ('V5__chat_history','V6__admin_panel')"
                    )
                ).scalar()
            )
            == 2
        )
    except PersistenceError:
        pass
    healthy = schema_ready and analysis_service.model_ready
    return JSONResponse(
        {
            "ready": healthy,
            "schema_ready": schema_ready,
            "model_ready": analysis_service.model_ready,
        },
        status_code=200 if healthy else 503,
    )

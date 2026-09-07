"""System-health controller."""

from datetime import datetime, timezone

from fastapi import APIRouter
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from config.database import SessionLocal
from config.settings import settings
from services.analysis_service import analysis_service


router = APIRouter(tags=["system"])


def _database_is_ready() -> bool:
    database = SessionLocal()
    try:
        database.execute(text("SELECT 1"))
        return True
    except SQLAlchemyError:
        return False
    finally:
        database.close()


@router.get("/app-status")
async def app_status() -> dict[str, object]:
    """Health check retained from the former Express backend."""
    return {
        "app_name": settings.app_name,
        "status": "OK",
        "model_ready": analysis_service.model_ready,
        "ai_provider": "openai",
        "openai_configured": analysis_service.openai_ready,
        "database_ready": _database_is_ready(),
        "server_date": datetime.now(timezone.utc),
    }

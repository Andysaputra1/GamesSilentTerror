"""Composition root for REST controllers."""

from fastapi import APIRouter

from app.controller.api.auth import router as auth_router
from app.controller.api.health import router as health_router
from app.controller.api.rooms import router as rooms_router
from app.controller.api.panel import router as panel_router
from app.controller.api.panel_npc import router as panel_npc_router
from app.controller.api.survey import router as survey_router
from app.controller.api.users import router as users_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(auth_router)
api_router.include_router(rooms_router)

api_router.include_router(panel_router)
api_router.include_router(panel_npc_router)
api_router.include_router(survey_router)
api_router.include_router(users_router)

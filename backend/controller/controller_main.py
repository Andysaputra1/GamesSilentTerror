"""Composition root for REST controllers."""

from fastapi import APIRouter

from controller.api.auth import router as auth_router
from controller.api.game import router as game_router
from controller.api.health import router as health_router
from controller.api.rooms import router as rooms_router
from controller.api.panel import router as panel_router
from controller.api.users import router as users_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(auth_router)
api_router.include_router(game_router)
api_router.include_router(rooms_router)

api_router.include_router(panel_router)
api_router.include_router(users_router)

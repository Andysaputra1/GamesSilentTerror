"""Register HTTP cross-origin policy using application configuration."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config.settings import settings


# FUNCTION SETUP: pasang kebijakan origin, method, dan header untuk request lintas origin dari browser.
def configure_cors(app: FastAPI) -> None:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["*"],
    )

"""Pasang kebijakan lintas origin HTTP sesuai konfigurasi aplikasi."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config.settings import settings


# Pasang kebijakan origin, method, dan header untuk request lintas origin dari browser.
def configure_cors(app: FastAPI) -> None:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=True,
        # PUT wajib ada: simpan skin (/api/auth/skin) dipanggil lintas origin dari frontend Vercel.
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["*"],
    )

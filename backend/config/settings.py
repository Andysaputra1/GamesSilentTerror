"""Centralized environment configuration for the backend."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, SecretStr, field_validator
from pydantic_settings import SettingsConfigDict

from config.mysql import MySQLSettings


BACKEND_DIR = Path(__file__).resolve().parents[1]
PROJECT_DIR = BACKEND_DIR.parent


class Settings(MySQLSettings):
    """Settings loaded from Docker environment variables or the root ``.env``."""

    model_config = SettingsConfigDict(
        env_file=PROJECT_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Shadow Heist Python Backend"
    app_environment: str = "development"
    panel_encryption_key: SecretStr | None = None
    panel_username: str = "administrator"
    panel_password_hash: SecretStr | None = None
    openrouter_api_key: SecretStr | None = None
    openrouter_default: SecretStr | None = Field(default=None, validation_alias=AliasChoices("openrouter_default", "OPENROUTER_DEFAULT"))
    openrouter_key_source: Literal["default", "custom"] = "default"
    openrouter_custom_configured: bool = False
    openrouter_model: str = "qwen/qwen3-14b"
    ollama_tunnel_token: SecretStr | None = None
    api_backend: Literal["openai", "openrouter"] = "openrouter"
    history_admin_usernames: str = ""
    admin_usernames: str = "user1"
    google_client_id: str = ""
    cors_origins: str = "http://localhost:4200,http://127.0.0.1:4200"
    ai_provider: Literal["api", "docker"] = "api"
    ollama_base_url: str = "http://localhost:11435"
    ollama_model: str = "qwen3:8b"
    ollama_timeout_seconds: float = Field(default=180.0, gt=0)
    ollama_max_output_tokens: int = Field(default=160, ge=1, le=2000)
    ollama_context_length: int = Field(default=2048, ge=512)

    @field_validator("ollama_model", mode="before")
    @classmethod
    # VALIDATOR CLASS METHOD: ubah pilihan 8/14 menjadi nama model Ollama dan tolak pilihan lain.
    def resolve_ollama_model(cls, value: object) -> str:
        models = {
            "8": "qwen3:8b", "14": "qwen3:14b",
            "qwen3:8b": "qwen3:8b", "qwen3:14b": "qwen3:14b",
        }
        selected = str(value).strip().lower()
        if selected not in models:
            raise ValueError("OLLAMA_MODEL harus 8 atau 14.")
        return models[selected]

    # ``openai_api_env`` remains accepted only as a compatibility alias. New
    # installations should always use the official OPENAI_API_KEY name.
    openai_api_key: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("OPENAI_API_KEY", "openai_api_env", "OPENAI_API_ENV"),
    )
    openai_model: str = "gpt-5-mini"
    openai_timeout_seconds: float = Field(default=30.0, gt=0)
    openai_max_output_tokens: int = Field(default=320, ge=64, le=2_000)
    openai_reasoning_effort: Literal["minimal", "low", "medium", "high"] = "minimal"
    intent_model_path: Path = BACKEND_DIR / "artifacts" / "svm" / "intent_classifier.pkl"

    auth_session_hours: int = Field(default=24, ge=1, le=24 * 30)

    default_room_code: str = "local-lobby"

    @property
    def openrouter_api_key_value(self) -> str | None:
        key = (self.openrouter_default or self.openrouter_api_key) if self.openrouter_key_source == "default" else self.openrouter_api_key
        return key.get_secret_value().strip() or None if key else None

    @property
    # PROPERTY: pecah konfigurasi CORS menjadi daftar origin browser yang diizinkan.
    def allowed_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    # PROPERTY: ambil nilai secret untuk klien API di backend; jangan tampilkan nilainya di log/frontend.
    def openai_api_key_value(self) -> str | None:
        """Return the key only for the server-side OpenAI client."""
        if self.openai_api_key is None:
            return None
        return self.openai_api_key.get_secret_value().strip() or None



@lru_cache
# FUNCTION CACHE: buat konfigurasi tervalidasi sekali, lalu gunakan ulang hasilnya.
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

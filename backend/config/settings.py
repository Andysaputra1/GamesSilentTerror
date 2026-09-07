"""Centralized environment configuration for the backend."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import quote_plus

from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


BACKEND_DIR = Path(__file__).resolve().parents[1]
PROJECT_DIR = BACKEND_DIR.parent


class Settings(BaseSettings):
    """Settings loaded from Docker environment variables or the root ``.env``."""

    model_config = SettingsConfigDict(
        env_file=PROJECT_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Shadow Heist Python Backend"
    app_environment: str = "development"
    cors_origins: str = "http://localhost:4200,http://127.0.0.1:4200"

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
    intent_model_path: Path = BACKEND_DIR / "models" / "intent_classifier.pkl"

    auth_session_hours: int = Field(default=24, ge=1, le=24 * 30)

    mysql_host: str = "localhost"
    mysql_port: int = Field(default=3306, ge=1, le=65535)
    mysql_database: str = "shadow_heist"
    mysql_user: str = "shadow_app"
    mysql_password: str = "shadow_app_dev_2026"
    database_url: str | None = None
    sql_echo: bool = False
    database_pool_size: int = Field(default=5, ge=1)
    database_max_overflow: int = Field(default=10, ge=0)

    default_room_code: str = "local-lobby"

    @property
    def allowed_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def openai_api_key_value(self) -> str | None:
        """Return the key only for the server-side OpenAI client."""
        if self.openai_api_key is None:
            return None
        return self.openai_api_key.get_secret_value().strip() or None

    @property
    def sqlalchemy_database_url(self) -> str:
        if self.database_url:
            return self.database_url

        user = quote_plus(self.mysql_user)
        password = quote_plus(self.mysql_password)
        database = quote_plus(self.mysql_database)
        return (
            f"mysql+pymysql://{user}:{password}@{self.mysql_host}:"
            f"{self.mysql_port}/{database}?charset=utf8mb4"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

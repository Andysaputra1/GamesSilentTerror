"""Centralized environment configuration for the backend."""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, SecretStr, field_validator
from pydantic_settings import SettingsConfigDict

from config.mysql import MySQLSettings

BACKEND_DIR = Path(__file__).resolve().parents[1]
PROJECT_DIR = BACKEND_DIR.parent

# Jalur rantai penulis kalimat NPC yang dipakai game (bagian dari JALUR_PENULIS notebook npc_nlg).
JALUR_PENULIS_NPC = ("openrouter", "tautan")
# Jalur Claude yang sudah dihapus: diabaikan bila masih ada di .env atau konfigurasi tersimpan.
JALUR_PENULIS_LAMA = ("claude_bedrock", "claude_api")
# penyedia/model (mis. qwen/qwen3-14b); segmen tidak boleh diawali titik agar path URL tetap lurus.
POLA_MODEL_OPENROUTER = re.compile(r"[a-z0-9][a-z0-9._-]*/[A-Za-z0-9_:-][A-Za-z0-9._:-]*")


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
    openrouter_default: SecretStr | None = Field(
        default=None, validation_alias=AliasChoices("openrouter_default", "OPENROUTER_DEFAULT")
    )
    openrouter_key_source: Literal["default", "custom"] = "default"
    openrouter_custom_configured: bool = False
    openrouter_model: str = "qwen/qwen3-14b"
    ollama_tunnel_token: SecretStr | None = None
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
    # VALIDATOR CLASS METHOD: ubah pilihan 4/8/14 menjadi nama model Ollama dan tolak pilihan lain.
    def resolve_ollama_model(cls, value: object) -> str:
        models = {
            "4": "qwen3:4b-instruct",
            "qwen3:4b-instruct": "qwen3:4b-instruct",
            "8": "qwen3:8b",
            "14": "qwen3:14b",
            "qwen3:8b": "qwen3:8b",
            "qwen3:14b": "qwen3:14b",
        }
        selected = str(value).strip().lower()
        if selected not in models:
            raise ValueError("OLLAMA_MODEL harus 4, 8, atau 14.")
        return models[selected]

    openai_timeout_seconds: float = Field(default=30.0, gt=0)
    openai_max_output_tokens: int = Field(default=320, ge=64, le=2_000)
    intent_model_path: Path = BACKEND_DIR / "artifacts" / "svm" / "intent_classifier.pkl"

    # OTAK NPC (hasil ekspor notebook skripsi): metode penalaran, penulis kalimat, dan lokasi IndoBERT.
    # campuran = bot dalam satu room dibagi bergiliran ke fuzzy, utility, dan behavior tree.
    npc_method: Literal["campuran", "fuzzy", "utility", "bt", "llm"] = "campuran"
    # otomatis = rantai penulis LLM (urutan di bawah, bisa diubah di panel), semua gagal → templat;
    # templat = tanpa LLM sama sekali; claude = nilai lama, diperlakukan seperti otomatis.
    npc_writer: Literal["otomatis", "claude", "templat"] = "otomatis"
    # Prioritas awal rantai penulis: OpenRouter → LLM sendiri lewat link (Docker/tunnel).
    npc_writer_order: str = ",".join(JALUR_PENULIS_NPC)
    # Model OpenRouter penulis kalimat; kosong = openrouter_model (qwen/qwen3-14b).
    npc_openrouter_model: str = ""
    npc_validate_nlg: bool = True
    npc_intent_model_dir: Path | None = None
    npc_target_model_dir: Path | None = None
    npc_nlu_device: Literal["cpu", "cuda"] = "cpu"
    npc_step_seconds: float = Field(default=3.0, ge=1.0, le=30.0)

    @field_validator("npc_intent_model_dir", "npc_target_model_dir", mode="before")
    @classmethod
    # VALIDATOR: nilai kosong di .env berarti "tidak diatur", bukan folder kerja atau key kosong.
    def empty_as_none(cls, value: object) -> object:
        return None if isinstance(value, str) and not value.strip() else value

    @field_validator("npc_writer_order", mode="before")
    @classmethod
    # VALIDATOR: daftar jalur dipisah koma tanpa duplikat; nama yang tidak dikenal ditolak saat startup.
    def validate_writer_order(cls, value: object) -> str:
        jalur = [j.strip() for j in str(value or "").split(",") if j.strip()]
        jalur = [j for j in jalur if j not in JALUR_PENULIS_LAMA]
        if not set(jalur) <= set(JALUR_PENULIS_NPC) or len(set(jalur)) != len(jalur):
            raise ValueError("NPC_WRITER_ORDER hanya boleh berisi " + ", ".join(JALUR_PENULIS_NPC))
        return ",".join(jalur)

    @field_validator("npc_openrouter_model", mode="before")
    @classmethod
    # VALIDATOR: model OpenRouter berbentuk penyedia/model, mis. qwen/qwen3-14b.
    def validate_openrouter_model(cls, value: object) -> str:
        model = str(value or "").strip()
        if model and not POLA_MODEL_OPENROUTER.fullmatch(model):
            raise ValueError("NPC_OPENROUTER_MODEL harus berbentuk penyedia/model.")
        return model

    auth_session_hours: int = Field(default=24, ge=1, le=24 * 30)

    default_room_code: str = "local-lobby"

    # Pilih kunci bawaan atau kustom sesuai konfigurasi panel tanpa fallback diam-diam.
    @property
    def openrouter_api_key_value(self) -> str | None:
        key = (
            (self.openrouter_default or self.openrouter_api_key)
            if self.openrouter_key_source == "default"
            else self.openrouter_api_key
        )
        return key.get_secret_value().strip() or None if key else None

    @property
    # PROPERTY: pecah konfigurasi CORS menjadi daftar origin browser yang diizinkan.
    def allowed_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
# FUNCTION CACHE: buat konfigurasi tervalidasi sekali, lalu gunakan ulang hasilnya.
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

"""Override provider satu proses. .env tetap sumber default setelah restart."""

import json
from threading import RLock

from cryptography.fernet import Fernet, InvalidToken
from pydantic import SecretStr
from sqlalchemy import text

from app.config.settings import settings
from app.module.persistence_service import PersistenceError, PersistenceService


class AIRuntimeService:
    # Siapkan override provider dalam memori dengan akses yang dilindungi lock.
    def __init__(self):
        self.lock = RLock()
        self.override = None

    # Snapshot per request: pergantian panel tidak mengubah request yang sudah berjalan.
    def current(self, base=None):
        base = settings if base is None else base
        with self.lock:
            return base.model_copy(update=self.override) if self.override else base

    # Hapus override sehingga request berikutnya memakai konfigurasi environment.
    def reset(self):
        with self.lock:
            self.override = None

    # Apakah nilai field berasal dari konfigurasi panel (bukan .env), mis. URL tunnel LLM.
    def diatur_panel(self, field):
        with self.lock:
            return bool(self.override and self.override.get(field))


ai_runtime = AIRuntimeService()


# Buat alat enkripsi dari PANEL_ENCRYPTION_KEY; tolak penyimpanan jika kunci belum valid.
# Alur: 1 cek kunci server -> 2 buat cipher
def _cipher():
    try:
        if not settings.panel_encryption_key:
            raise ValueError()
        return Fernet(settings.panel_encryption_key.get_secret_value().encode())
    except ValueError as error:
        raise PersistenceError(
            "Kunci enkripsi panel belum siap. Jalankan setup_panel.py di server."
        ) from error


# Ubah isi baris DB menjadi nilai yang dipakai program. API key dibuka hanya untuk sumber kustom.
# Alur: 1 salin isi baris -> 2 ambil key terenkripsi -> 3 dekripsi API key -> 4 dekripsi token tunnel
def _decode_config(stored):
    override = dict(stored)
    override.pop("api_backend", None)  # kunci lama; OpenAI langsung sudah dihapus
    token = override.pop("ollama_tunnel_token_encrypted", None)
    encrypted = override.pop("openrouter_key_encrypted", None)
    source = override.setdefault("openrouter_key_source", "custom" if encrypted else "default")
    override["openrouter_custom_configured"] = bool(encrypted)
    if source == "custom":
        override["openrouter_api_key"] = None
    if encrypted and source == "custom":
        try:
            override["openrouter_api_key"] = SecretStr(
                _cipher().decrypt(encrypted.encode()).decode()
            )
        except (InvalidToken, UnicodeError) as error:
            raise PersistenceError(
                "API key panel tidak dapat dibuka. Periksa PANEL_ENCRYPTION_KEY server."
            ) from error
    # Token tunnel panel menimpa OLLAMA_TUNNEL_TOKEN .env; tanpa token panel, .env tetap dipakai.
    if token:
        try:
            override["ollama_tunnel_token"] = SecretStr(_cipher().decrypt(token.encode()).decode())
        except (InvalidToken, UnicodeError) as error:
            raise PersistenceError(
                "Token tunnel panel tidak dapat dibuka. Periksa PANEL_ENCRYPTION_KEY server."
            ) from error
    return override


# Ambil konfigurasi AI yang disimpan di panel saat server nyala, supaya key dan link tidak hilang
# saat restart. Baris kosong bukan error: bot memakai nilai .env.
# Alur: 1 tarik data DB -> 2 cek isi -> 3 dekripsi key -> 4 simpan ke memori
def muat_konfigurasi_ai():
    nilai = PersistenceService._run(
        lambda db: db.execute(text("SELECT config FROM panel_configuration WHERE id=1")).scalar()
    )
    stored = json.loads(nilai) if isinstance(nilai, str) else nilai
    if stored:
        override = _decode_config(stored)
        with ai_runtime.lock:
            ai_runtime.override = override


# Simpan konfigurasi AI dari panel ke DB dan memori, supaya langsung berlaku tanpa restart.
# Alur: 1 baca isi lama (baris dikunci) -> 2 susun isi baru dan enkripsi key -> 3 uji dekripsi -> 4 tulis DB -> 5 simpan ke memori
def save_panel_configuration(
    provider,
    endpoint,
    api_key=None,
    key_source=None,
    tunnel_token=None,
    clear_tunnel_token=False,
    model=None,
):
    stored = {
        "ai_provider": provider,
        "openrouter_model": "qwen/qwen3-14b",
        "ollama_base_url": endpoint,
    }
    with ai_runtime.lock:
        # Kunci baris konfigurasi agar pembaruan sumber kunci tidak menimpa perubahan lain.
        def write(db):
            previous = db.execute(
                text("SELECT config FROM panel_configuration WHERE id=1 FOR UPDATE")
            ).scalar()
            previous = json.loads(previous) if isinstance(previous, str) else (previous or {})
            # Model lokal (ai-docker: qwen3:4b-instruct/qwen3:14b); kosong = pilihan sebelumnya.
            stored["ollama_model"] = model or previous.get("ollama_model") or "qwen3:14b"
            source = key_source or (
                "custom"
                if api_key
                else previous.get(
                    "openrouter_key_source",
                    "custom" if previous.get("openrouter_key_encrypted") else "default",
                )
            )
            if source not in {"default", "custom"}:
                raise ValueError("Sumber API key tidak valid.")
            stored["openrouter_key_source"] = source
            if api_key and source == "custom":
                stored["openrouter_key_encrypted"] = _cipher().encrypt(api_key.encode()).decode()
            elif previous.get("openrouter_key_encrypted"):
                stored["openrouter_key_encrypted"] = previous["openrouter_key_encrypted"]
            # Token tunnel: isi baru menggantikan, kosong mempertahankan, hapus kembali ke .env.
            if tunnel_token:
                stored["ollama_tunnel_token_encrypted"] = (
                    _cipher().encrypt(tunnel_token.encode()).decode()
                )
            elif previous.get("ollama_tunnel_token_encrypted") and not clear_tunnel_token:
                stored["ollama_tunnel_token_encrypted"] = previous["ollama_tunnel_token_encrypted"]
            if (
                provider == "api"
                and source == "custom"
                and not stored.get("openrouter_key_encrypted")
            ):
                raise ValueError("Isi API key sendiri sebelum memilih mode ini.")
            override = _decode_config(stored)
            db.execute(
                text("""
                INSERT INTO panel_configuration(id,config) VALUES(1,:config)
                ON DUPLICATE KEY UPDATE config=:config
            """),
                {"config": json.dumps(stored)},
            )
            return override

        ai_runtime.override = PersistenceService._run(write)

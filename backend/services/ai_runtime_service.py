"""Override provider satu proses. .env tetap sumber default setelah restart."""

from threading import RLock
from config.settings import settings


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

    # Validasi pasangan provider/model sebelum mengaktifkan override sementara.
    def select(self, provider, model):
        if provider not in {"api", "docker"} or model not in {"8", "14"}:
            raise ValueError("Provider/model tidak valid.")
        with self.lock:
            self.override = {"ai_provider": provider, "ollama_model": f"qwen3:{model}b"}

    # Hapus override sehingga request berikutnya memakai konfigurasi environment.
    def reset(self):
        with self.lock:
            self.override = None


ai_runtime = AIRuntimeService()


# Bangun cipher dari kunci server; tolak penyimpanan jika kunci belum valid.
def _cipher():
    from cryptography.fernet import Fernet
    from services.persistence_service import PersistenceError

    try:
        if not settings.panel_encryption_key:
            raise ValueError()
        return Fernet(settings.panel_encryption_key.get_secret_value().encode())
    except ValueError as error:
        raise PersistenceError(
            "Kunci enkripsi panel belum siap. Jalankan setup_panel.py di server."
        ) from error


# Pulihkan konfigurasi tersimpan dan dekripsi kunci hanya untuk sumber kustom.
def _decode_config(stored):
    from pydantic import SecretStr
    from cryptography.fernet import InvalidToken
    from services.persistence_service import PersistenceError

    override = dict(stored)
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
    return override


# Muat konfigurasi panel tersimpan sebagai override saat backend dimulai.
def load_panel_configuration():
    import json
    from sqlalchemy import text
    from services.persistence_service import PersistenceService

    # Baca satu dokumen konfigurasi panel dan normalisasi JSON dari driver database.
    def read(db):
        value = db.execute(text("SELECT config FROM panel_configuration WHERE id=1")).scalar()
        return json.loads(value) if isinstance(value, str) else value

    stored = PersistenceService._run(read)
    if stored:
        override = _decode_config(stored)
        with ai_runtime.lock:
            ai_runtime.override = override


# Enkripsi kunci, simpan konfigurasi secara atomik, lalu terapkan override.
def save_panel_configuration(provider, endpoint, api_key=None, key_source=None):
    import json
    from sqlalchemy import text
    from services.persistence_service import PersistenceService

    stored = {
        "ai_provider": provider,
        "api_backend": "openrouter",
        "ollama_model": "qwen3:14b",
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

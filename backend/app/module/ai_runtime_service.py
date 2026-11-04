"""Override provider AI satu proses: konfigurasi panel (API key, token tunnel, link dan model LLM) menimpa .env.

Isinya disimpan terenkripsi di baris panel_configuration id=1 dan disalin ke memori (ai_runtime.override).
Selama baris itu kosong, .env tetap dipakai.

Alurnya saat server nyala (muat_konfigurasi_ai, dipanggil main.py)
1. Baca baris id=1 dari DB
2. Baris kosong: selesai, bot memakai .env
3. Ada isi: buka enkripsi key dan token, lalu simpan ke memori

Alurnya saat panel menyimpan (save_panel_configuration)
1. Baca isi lama dengan baris dikunci. Gagal baca: panel menerima gagal
2. Susun isi baru dan enkripsi key. Sumber key salah atau key kosong: batal, DB tidak berubah
3. Uji buka hasil enkripsinya. Gagal: batal, DB tidak berubah
4. Tulis ke DB
5. Simpan ke memori, jadi langsung berlaku tanpa restart
"""

import json
from threading import RLock

from cryptography.fernet import Fernet, InvalidToken
from pydantic import SecretStr
from sqlalchemy import text

from app.config.settings import settings
from app.module.mysql_connector import PersistenceError, jalankan_transaksi


class AIRuntimeService:
    # Siapkan override provider dalam memori dengan akses yang dilindungi lock.
    def __init__(self):
        self.lock = RLock()
        self.override = None

    # Snapshot per request: pergantian panel tidak mengubah request yang sudah berjalan.
    def current(self):
        with self.lock:
            return settings.model_copy(update=self.override) if self.override else settings

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
def _decode_config(stored):
    override = dict(stored)
    override.pop("api_backend", None)  # kunci lama; OpenAI langsung sudah dihapus
    token = override.pop("ollama_tunnel_token_encrypted", None)
    encrypted = override.pop("openrouter_key_encrypted", None)
    source = override.setdefault("openrouter_key_source", "custom" if encrypted else "default")
    override["openrouter_custom_configured"] = bool(encrypted)
    # Sumber kustom tanpa key tersimpan: dikosongkan supaya tidak diam-diam memakai key dari .env.
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
def muat_konfigurasi_ai():
    nilai = jalankan_transaksi(
        lambda db: db.execute(text("SELECT config FROM panel_configuration WHERE id=1")).scalar()
    )
    stored = json.loads(nilai) if isinstance(nilai, str) else nilai
    if stored:
        override = _decode_config(stored)
        with ai_runtime.lock:
            ai_runtime.override = override


# Simpan konfigurasi AI dari panel ke DB dan memori, supaya langsung berlaku tanpa restart.
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
            # Uji buka sebelum menulis: kalau gagal, error dilempar dan DB tidak berubah.
            override = _decode_config(stored)
            db.execute(
                text("""
                INSERT INTO panel_configuration(id,config) VALUES(1,:config)
                ON DUPLICATE KEY UPDATE config=:config
            """),
                {"config": json.dumps(stored)},
            )
            return override

        # Gagal baca atau tulis: error dilempar, memori tidak berubah, panel menerima gagal.
        ai_runtime.override = jalankan_transaksi(write)

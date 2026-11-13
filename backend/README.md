# Backend Python

File ini menjelaskan konfigurasi backend: variabel environment, pengaturan yang bisa ditimpa dari panel, cara
menjalankan backend tanpa Docker, dan pola SQL di model. Susunan folder dan aturan lapisan ada di
[CODE_GUIDE.md](../CODE_GUIDE.md); menjalankan seluruh aplikasi lewat Docker ada di [README.md](../README.md).

Backend memakai FastAPI untuk HTTP dan Socket.IO untuk chat, dengan entry point `app.main:asgi_app`. Saat menyala,
`app/main.py` memuat konfigurasi panel dari MySQL, memuat otak bot (IndoBERT, fuzzy, penulis kalimat) di latar, lalu
menjalankan jam permainan tiap 0,5 detik.

## Variabel environment

`app/config/settings.py` membaca environment Docker atau file `.env` di root repo. Contoh lengkap ada di
`.env.example`. Sesudah mengubah `.env`, recreate container backend; restart saja tidak memuat environment baru.

**Database** (`app/config/mysql.py`)

| Variabel | Bawaan | Guna |
| --- | --- | --- |
| `MYSQL_HOST`, `MYSQL_PORT`, `MYSQL_DATABASE`, `MYSQL_USER` | `localhost`, `3306`, `shadow_heist`, `shadow_app` | Koneksi MySQL. Alias `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER` juga diterima; bila keduanya ada, `MYSQL_*` yang dipakai |
| `MYSQL_PASSWORD` (alias `DB_PASSWORD`) | tanpa bawaan | **Wajib.** Backend gagal menyala bila kosong |
| `DATABASE_URL` | kosong | Opsional; bila diisi dipakai apa adanya sebagai alamat SQLAlchemy |
| `DATABASE_POOL_SIZE`, `DATABASE_MAX_OVERFLOW`, `SQL_ECHO` | `5`, `10`, `false` | Ukuran pool dan log SQL |

Di Docker lokal, `MYSQL_HOST` dan port diisi Compose; alias `DB_*` harus diteruskan sendiri ke environment container
bila dipakai.

**Akun dan panel**

| Variabel | Bawaan | Guna |
| --- | --- | --- |
| `AUTH_SESSION_HOURS` | `24` | Lama sesi pemain (1–720 jam) |
| `GOOGLE_CLIENT_ID` | kosong | OAuth Web Client ID untuk login Google (publik, tanpa secret) |
| `CORS_ORIGINS` | `http://localhost:4200,http://127.0.0.1:4200` | Origin frontend yang diizinkan untuk HTTP, Socket.IO, dan login Google. Di Azure diisi dari `FRONTEND_ORIGIN` |
| `PANEL_USERNAME`, `PANEL_PASSWORD_HASH` | `administrator`, kosong | Login panel. Hash dibuat `scripts/setup_panel.py` |
| `PANEL_ENCRYPTION_KEY` | kosong | Kunci Fernet untuk key dan token yang disimpan dari panel. Dibuat sekali oleh `setup_panel.py`; simpan cadangannya terpisah dari database |
| `ADMIN_USERNAMES`, `HISTORY_ADMIN_USERNAMES` | `user1`, kosong | Hanya daftar username yang dicadangkan (tidak boleh dipakai akun game) |

**LLM dan otak bot**

| Variabel | Bawaan | Guna |
| --- | --- | --- |
| `AI_PROVIDER` | `api` (`.env.example`: `docker`) | Pilihan awal menu Konfigurasi AI: `api` = OpenRouter, `docker` = Ollama atau tunnel. Juga menentukan model yang dilaporkan `/app-status` dan apakah `ollama_ready` diperiksa |
| `openrouter_default` (atau `OPENROUTER_DEFAULT`) | kosong | Key OpenRouter bawaan server untuk pilihan "Default dari server" |
| `OPENROUTER_API_KEY` | kosong | Key OpenRouter lama; cadangan bila `openrouter_default` kosong |
| `OLLAMA_BASE_URL` | `http://localhost:11435` (Compose lokal: `http://ollama:11434`) | Link LLM sendiri bila panel belum menyimpan URL tunnel |
| `OLLAMA_MODEL` | `14` | Model link: `4` = `qwen3:4b-instruct`, `8` = `qwen3:8b`, `14` = `qwen3:14b`. Nilai lain ditolak |
| `OLLAMA_TUNNEL_TOKEN` | kosong | Bearer token link; token yang disimpan di panel menimpanya |
| `NPC_WRITER` | `otomatis` | `otomatis` = rantai penulis LLM lalu templat; `templat` = tanpa LLM |
| `NPC_WRITER_ORDER` | `openrouter,tautan` | Prioritas awal rantai penulis; hanya `openrouter` dan `tautan` (link LLM sendiri) |
| `NPC_OPENROUTER_MODEL` | kosong | Model OpenRouter penulis (`penyedia/model`). Kosong = `qwen/qwen3-14b` |
| `NPC_NLU_DEVICE` | `cpu` | `cpu` atau `cuda` untuk IndoBERT |
| `NPC_STEP_SECONDS` | `3` | Jarak langkah tiap bot (1–30 detik) |
| `NPC_INTENT_MODEL_DIR`, `NPC_TARGET_MODEL_DIR` | kosong | Lokasi model IndoBERT bila tidak di `backend/artifacts/indobert/{intent,target}` |

Variabel khusus Compose (`MYSQL_ROOT_PASSWORD`, `PMA_ABSOLUTE_URI`, `OLLAMA_CONTEXT_LENGTH`, `OLLAMA_KEEP_ALIVE`,
`OLLAMA_MODELS_TO_PULL`) dibaca container MySQL, phpMyAdmin, atau Ollama, bukan backend. Lihat [OLLAMA.md](../OLLAMA.md)
untuk tiga yang terakhir.

## Pengaturan dari panel

Panel menyimpan pengaturan di tabel `panel_configuration` dan memuatnya lagi saat backend menyala, jadi pengaturan
panel menimpa `.env` tanpa restart. Selama baris panel kosong, `.env` yang dipakai.

**Menu 01 Konfigurasi AI** (baris `id = 1`, `services/ai_config_service.py`)

- **Sumber key OpenRouter.** "Default dari server" membaca `openrouter_default`, lalu `OPENROUTER_API_KEY` bila
  kosong. "API key sendiri" memakai key yang diketik di panel dan tidak beralih ke key default bila key itu kosong
  atau salah. Beralih ke Default tidak menghapus key sendiri. Kolom key yang dibiarkan kosong mempertahankan key lama.
- **URL tunnel Ollama** harus HTTPS dengan alamat publik, tanpa password, query, atau fragment. Endpoint harus
  meneruskan `/api/chat` ke Ollama, atau memakai server kompatibel OpenAI (`/v1/chat/completions`).
- **Token tunnel** (`LLM_TOKEN` dari `ai-docker/.env`) menimpa `OLLAMA_TUNNEL_TOKEN`; centang "Hapus token"
  mengembalikannya ke environment.
- **Model lokal** dipakai jalur link bila "Model LLM link" di menu Otak NPC dibiarkan Bawaan.
- Key dan token disimpan sebagai ciphertext Fernet dengan `PANEL_ENCRYPTION_KEY`. Nilainya tidak pernah dikembalikan
  API panel. Bila kunci itu hilang atau diganti, key yang tersimpan tidak bisa didekripsi lagi.

**Menu 05 Otak NPC** (baris `id = 2`, `services/npc_config_service.py`)

- Penulis kalimat (`otomatis` atau `templat`), urutan dan jalur aktif rantai penulis, **Model OpenRouter**, dan
  **Model LLM link**. Nilai awalnya dari `NPC_WRITER`, `NPC_WRITER_ORDER`, dan `NPC_OPENROUTER_MODEL`. Kolom Model
  OpenRouter yang kosong berarti model OpenRouter dari Konfigurasi AI (bawaan `qwen/qwen3-14b`).
  Model yang dipakai produksi tercatat di [deployment/README.md](deployment/README.md#panel-dan-secret-di-vm).
- Rantai memakai key OpenRouter dan link dari Konfigurasi AI. Jalur tanpa key atau link dilewati; bila semua gagal,
  bot memakai templat.
- Tombol **Tes koneksi semua prioritas** mengirim pesan pendek ke setiap jalur aktif (OpenRouter memakai saldo).

## Menjalankan backend tanpa Docker

Butuh Python 3.11, MySQL yang sudah diberi migrasi, dan model IndoBERT (lihat [README.md](../README.md#langkah)).

```sh
cd backend
python -m venv .venv
# Windows: ganti .venv/bin/python dengan .venv\Scripts\python
# PyTorch CPU dulu (seperti Dockerfile), supaya pip tidak mengunduh wheel CUDA yang besar.
.venv/bin/python -m pip install torch==2.14.0 --index-url https://download.pytorch.org/whl/cpu
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m uvicorn app.main:asgi_app --host 0.0.0.0 --port 8000
```

Jalankan **satu worker** saja: ruangan, pertandingan, nonce Google, dan batas percobaan login hanya ada di memori satu
proses. Migrasi tidak membuat akun; buat akun lewat halaman daftar atau `python scripts/create_user.py <username>
--name "Nama"` dari folder `backend`. Perintah tes ada di [CODE_GUIDE.md](../CODE_GUIDE.md#tes-dan-simulasi).

## Pola SQL di model

Query ditulis sebagai SQL langsung di `app/models/`, bukan query ORM. SQLAlchemy hanya dipakai sebagai konektor, pool,
dan pengikat parameter.

```python
# app/models/auth_queries.py
from sqlalchemy import text

def account_by_username(database, username):
    sql = text("""
        SELECT id, username, display_name, password_hash, is_active, skin_id
        FROM user_accounts WHERE username = :username
    """)
    return database.execute(sql, {"username": username}).mappings().one_or_none()
```

Pemakaian dari service:

```python
from app.config.database import jalankan_transaksi
from app.models.auth_queries import account_by_username

account = jalankan_transaksi(lambda database: account_by_username(database, "user1"))
# account berupa mapping (account["username"]) atau None bila tidak ditemukan.
# Error SQL di-rollback lalu menjadi PersistenceError.
```

- Jangan menyisipkan input pengguna ke teks SQL. Pakai placeholder bernama (`:username`) dan dictionary parameter.
- Service menentukan batas transaksi, sehingga beberapa query bisa commit atau rollback bersama. Controller
  menerjemahkan error menjadi respons API.
- Pool ditutup hanya saat aplikasi berhenti, bukan tiap query.
- Semua perubahan tabel lewat [migrasi](migrations/README.md).

# Shadow Heist Python Backend

Struktur API menggunakan controller, services, dan model berisi SQL langsung.

```text
backend/
  artifacts/
    svm/intent_classifier.pkl   # Model ML privat, terpisah dari model database
  config/
    settings.py                 # Pengaturan aplikasi/AI dan pembaca environment
    mysql.py                    # Host, port, database, kredensial, pool
    upload.py                   # Folder tujuan, batas ukuran/jumlah, tipe upload
  controller/
    controller_main.py          # Menggabungkan router HTTP
    api/
      auth.py
      game.py
      health.py
      rooms.py                  # Lobby, start, snapshot privat, aksi/vote, checker
    middleware/
      auth.py                   # Validasi bearer token sebelum controller
      cors.py                   # Kebijakan cross-origin
  migrations/                   # SQL untuk membuat/mengubah struktur tabel
  models/
    auth_queries.py             # SELECT/INSERT/DELETE akun dan sesi
    game_queries.py             # SELECT/INSERT/UPDATE pemain, chat, analisis
  module/
    mysql_connector.py          # Engine, connection pool, session, health probe
    upload.py                   # Helper simpan satu file atau batch
    create_user.py              # CLI akun tambahan untuk multiplayer lokal
  services/                     # Logika password, sesi login, AI, dan game
  schemas/                      # Validasi request/response API
  realtime/                     # Controller event Socket.IO
  tests/
  main.py                       # Entry point ASGI
```

Alur: HTTP/Socket.IO -> controller -> service -> models (SQL) -> module (MySQL).
Model tidak menyimpan aturan HTTP atau menulis respons API. Services mengatur
transaksi agar beberapa query bisa commit/rollback bersama.

Engine murni ada di `services/match_engine.py`: role, fase, skill, cooldown,
voting, kemenangan, serta snapshot privat. `services/room_service.py` membatasi
akses anggota/host dan memegang lock. `main.py` menjalankan clock pertandingan;
frontend hanya menampilkan keputusan server. Lihat [alur dan aturan game](../GAME_CONCEPT.md).

State pertandingan masih di memori satu proses, bukan snapshot MySQL. Reconnect
browser aman selama proses hidup, tetapi restart backend menghilangkan match.
Chat/analisis disimpan lewat model SQL yang sudah ada. Tes `tests/live_match_smoke.py`
menjalankan pertandingan nyata empat akun sementara sampai selesai, dengan cleanup
akun milik tes. Jangan menjalankannya pada deployment publik.

## SQL langsung di model

```python
# models/auth_queries.py
from sqlalchemy import text

def account_by_username(database, username):
    sql = text("""
        SELECT id, username, display_name, password_hash, is_active
        FROM user_accounts WHERE username = :username
    """)
    return database.execute(sql, {"username": username}).mappings().one_or_none()
```

Pemakaian dari service:

```python
from module.mysql_connector import SessionLocal
from models.auth_queries import account_by_username

with SessionLocal.begin() as database:
    account = account_by_username(database, "user1")
    # account berupa mapping: account["username"], atau None jika tidak ditemukan.
```

SQLAlchemy digunakan sebagai konektor/pool dan pengikat parameter SQL; query
aplikasi ditulis sebagai SQL langsung, bukan query ORM. Jangan interpolasi input
pengguna ke SQL. Gunakan `:username` dan dictionary parameter, padanan placeholder
`?` di mysql2. Exception diteruskan ke service untuk rollback dan diterjemahkan
controller menjadi respons API. Pool ditutup hanya saat aplikasi berhenti,
bukan setiap query. Semua perubahan tabel tetap melalui migrations.

## Config

Environment Docker atau file `.env` di root dibaca oleh `config/settings.py`.
Pengaturan MySQL didefinisikan di `config/mysql.py`:
`MYSQL_HOST`, `MYSQL_PORT`, `MYSQL_DATABASE`, `MYSQL_USER`, `MYSQL_PASSWORD`.
Alias `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD` juga diterima;
jika keduanya diberikan, nama MYSQL_* diprioritaskan. Nilai DB_* harus diteruskan
ke environment container jika menjalankan backend lewat Docker.

Secret tidak disimpan dalam mysql.json atau kode controller. Lihat `.env.example`.
`OPENAI_API_KEY` (atau alias lama `openai_api_env`) hanya dibaca backend.
Default model dan batas respons tetap di settings.py.
Pilih `AI_PROVIDER=docker` untuk Ollama lokal atau `AI_PROVIDER=api` untuk OpenAI.
`OLLAMA_MODEL` memilih model lokal (default qwen3:8b). Recreate service ai-engine
setelah mengubah .env; lihat ../OLLAMA.md untuk perintah dan pemeriksaan status.

## Module upload (padanan helper Multer)

```python
from config.upload import PROFILE_PICTURE, ASSET_ICON
from module.upload import save_upload, save_uploads

# Di dalam fungsi async yang menerima FastAPI UploadFile:
stored = await save_upload(file, PROFILE_PICTURE)
# stored.filename, stored.relative_path, stored.size, stored.content_type

assets = await save_uploads(files, ASSET_ICON)
```

App icon: 5 MiB/file; asset icon: 5 MiB/file, maksimal 50 file; profile picture:
2 MiB/file. Saat ini menerima PNG, JPEG, WebP dengan pemeriksaan MIME dan
signature header (bukan decoding seluruh gambar). SVG, video, PDF, dan fitur
Boarding/PusatInfo dari contoh Node belum disertakan.

Nama file memakai UUID, tidak memakai path dari nama asli. File yang gagal
disimpan dibersihkan, termasuk file batch yang sudah tersimpan sebelum kegagalan.
File berada di `backend/public/uploads/`. Helper ini belum membuka endpoint upload
atau URL publik. Saat membuat endpoint multipart, pasang `python-multipart`,
validasi autentikasi di controller, dan petakan UploadError menjadi error HTTP.
Controller menentukan hak akses file dan kebijakan penyajiannya.

## Menjalankan dan menguji

Entry point tetap `uvicorn main:asgi_app --host 0.0.0.0 --port 8000` dari backend.
URL HTTP dan event Socket.IO tidak berubah karena refactor ini.

```sh
python -m unittest discover -s tests -v
# Khusus database MySQL sementara yang telah diberi migration:
STRUCTURE_TEST_DB=1 python -m unittest discover -s tests -p mysql_smoke.py -v
```

Tes MySQL menulis data percobaan; jangan arahkan ke database pengguna. Tes
controller memakai respons AI mock untuk memeriksa jalur API dan penyimpanan
SQL, tanpa panggilan berbayar ke OpenAI.

Migration V2 menyediakan akun development `user1 / user132` dengan hash PBKDF2.

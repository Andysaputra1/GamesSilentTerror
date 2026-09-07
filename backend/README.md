# Shadow Heist Python Backend

Backend ini memakai MVC yang disesuaikan untuk FastAPI:

- `config/` — semua pengaturan environment dan koneksi database.
- `api/routes/` — controller HTTP.
- `realtime/` — controller event Socket.IO.
- `services/` — use case AI, fuzzy logic, dan penyimpanan data.
- `models/` — model ORM SQLAlchemy yang memetakan tabel MySQL.
- `schemas/` — validasi request dan response API dengan Pydantic.
- `migrations/` — sumber kebenaran struktur database SQL yang dijalankan MySQL saat volume baru dibuat.

`PersistenceService` menyimpan sesi default, pemain, chat, serta hasil analisis
SVM/fuzzy/AI Host. Aplikasi tidak menjalankan `create_all()`: setiap perubahan
struktur database harus ditambahkan sebagai migration SQL baru, misalnya
`V2__add_votes.sql`.

Konfigurasi dibaca dari environment Docker atau `.env` root. Lihat
`.env.example` untuk kredensial development dan `docker-compose.yml` untuk
variabel yang diteruskan ke service `ai-engine`.

## AI Host dan login development

AI Host memakai OpenAI Responses API. Isi `OPENAI_API_KEY` pada `.env` root;
key hanya diteruskan ke container backend dan tidak pernah ke Angular. Nama
lama `openai_api_env` masih diterima untuk kompatibilitas, tetapi
`OPENAI_API_KEY` adalah nama yang direkomendasikan.

Default `OPENAI_MODEL=gpt-5-mini` memakai reasoning `minimal` dan maksimum
320 output token. Keduanya dapat diganti di `.env` bila diperlukan.

Migration `V2__add_authentication.sql` membuat akun development awal:
`user1` dengan password `user132`. Password tersimpan sebagai hash PBKDF2,
bukan teks biasa. Ganti atau hapus akun ini sebelum deployment publik.

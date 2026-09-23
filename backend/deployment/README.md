# Database baru untuk Azure

`mysql/001_schema.sql` adalah baseline untuk volume MySQL **kosong**, bukan
migrasi upgrade database lama. Tidak ada DROP, penghapusan data, atau akun demo.
Database lokal tetap menggunakan migrasi historis V1–V4 di `backend/migrations`.
Jangan mengganti baseline ini untuk meng-upgrade database yang sudah berjalan;
buat migrasi inkremental baru dan backup database terlebih dahulu.

## Audit tabel

| Tabel | Pemakaian backend |
| --- | --- |
| user_accounts | Login dan pendaftaran (`models/auth_queries.py`) |
| auth_sessions | Validasi token dan logout (`models/auth_queries.py`) |
| account_identities | Email dan identitas Google (`models/auth_queries.py`) |
| game_sessions | Identitas room dan fase dalam persistence (`models/game_queries.py`) |
| players | Peserta room, status, dan skor (`models/game_queries.py`) |
| chat_messages | Pesan chat yang disimpan (`models/game_queries.py`) |
| ai_analyses | Hasil SVM/fuzzy dan respons AI (`models/game_queries.py`) |
| schema_migrations | Catatan versi skema; dipertahankan untuk administrasi migrasi |

Semua tabel aplikasi masih digunakan. `players` berbeda dari `user_accounts`:
satu akun dapat menjadi peserta beberapa room. State lengkap pertandingan,
timer, dan voting masih di memori; volume tidak memulihkan match setelah restart.
Baseline tidak memasukkan user1, janice, kimberly, ataupun data pertandingan lokal.
Kolom/enum lama tetap dipertahankan untuk kompatibilitas query saat ini.

## Jalankan di VM

Dari root repository, buat password acak pada file lokal yang diabaikan Git:

```bash
test ! -e .env.azure && (umask 077; printf 'MYSQL_PASSWORD=%s\nMYSQL_ROOT_PASSWORD=%s\n' "$(openssl rand -hex 24)" "$(openssl rand -hex 24)" > .env.azure)
sudo docker volume create shadow_heist_mysql_data
sudo docker compose --env-file .env.azure -f docker-compose.azure.yml up -d mysql
sudo docker compose --env-file .env.azure -f docker-compose.azure.yml ps
```

Jangan membagikan `.env.azure`. Password ini diperlukan backend nanti. Mengubah
environment tidak merotasi password pada database yang sudah diinisialisasi.

Volume eksternal harus dibuat lebih dulu dan dipertahankan oleh Compose saat
`down`, termasuk `down -v`. Penghapusan volume manual atau disk VM tetap menghapus
data. Volume bukan backup: simpan dump terpisah di luar VM sebelum upgrade.
MySQL tidak membuka port host dan tidak menjalankan phpMyAdmin.

Untuk melihat tabel, masuk dengan password root dari file lokal (jangan kirim
password ke chat):

```bash
sudo docker compose --env-file .env.azure -f docker-compose.azure.yml exec mysql mysql -uroot -p shadow_heist
```

```sql
SHOW TABLES;
SELECT COUNT(*) FROM user_accounts;
```

Hasil awal: delapan tabel dan nol akun. Registrasi membutuhkan perubahan backend
akun/email/Google yang masih harus dirilis bersama sebelum backend VPS dijalankan.

MySQL hanya mengeksekusi baseline saat direktori data masih kosong. Jika volume
sudah berisi database, berhenti dan audit isinya; jangan menghapus volume untuk
memaksa inisialisasi ulang. Skema ini tidak menonaktifkan akun demo pada volume lama.

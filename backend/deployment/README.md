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

Hasil awal: sebelas tabel dan nol akun pemain. Registrasi membutuhkan perubahan backend
akun/email/Google yang masih harus dirilis bersama sebelum backend VPS dijalankan.

MySQL hanya mengeksekusi baseline saat direktori data masih kosong. Jika volume
sudah berisi database, berhenti dan audit isinya; jangan menghapus volume untuk
memaksa inisialisasi ulang. Skema ini tidak menonaktifkan akun demo pada volume lama.


## Riwayat chat pemain dan bot

Pesan Socket.IO pemain disimpan sebelum echo dan sebelum menunggu AI. Balasan bot
tersimpan sebagai baris terpisah dengan nama pengirim dan referensi pesan pemain.
Metadata pertandingan, ronde, fase, dan waktu tersedia; urutan menggunakan ID database.
Tidak ada penghapusan otomatis saat logout, keluar room, atau restart backend.
Volume database harus tetap dipertahankan dan dibackup. Ini bukan pemulihan match aktif.
Commit database mendahului broadcast: pesan tetap dapat tercatat jika proses berhenti
sebelum browser menerima broadcast; arsip bukan bukti penerimaan oleh setiap browser.

Untuk melihat arsip, buka `/panel` pada origin backend melalui HTTPS dan login
sebagai administrator. `/history` dan `/admin` mengarah ke panel baru.
Semua API panel memakai sesi administrator terpisah dari akun pemain.

Database baru menjalankan 001_schema.sql, 002_chat_history.sql, dan 003_admin_panel.sql otomatis.
Database/volume lama: backup dulu, hentikan backend sementara, lalu jalankan
`backend/migrations/V5__chat_history.sql` **sekali saja** pada database shadow_heist.
Contoh dari root repository di VM untuk service MySQL Azure:

```bash
sudo docker compose --env-file .env.azure -f docker-compose.azure.yml exec mysql sh -c 'exec mysql -uroot -p"$MYSQL_ROOT_PASSWORD" shadow_heist'
```

Di prompt MySQL, periksa `SELECT * FROM schema_migrations;`. Jika V5 belum ada:

```sql
SOURCE /docker-entrypoint-initdb.d/002_chat_history.sql;
```

Jalankan sebelum backend versi baru diaktifkan. Jangan menghapus volume untuk migrasi.
Jika SQL gagal, periksa struktur kolom sebelum mengulang: ALTER TABLE MySQL bukan
transaksi yang dapat dibatalkan bersama INSERT penanda migrasi.
Pesan lama tetap ada dan ditandai `legacy`; identitas bot/ronde lama tidak direka ulang.
Balasan AI lama tetap tersimpan di ai_analyses dan belum dimasukkan ke tabel percakapan,
karena kode lama tidak mencatat apakah respons benar-benar dipublikasikan.

`schema_migrations` menyimpan versi struktur yang sudah diterapkan dan waktunya.
Saat ini project memakai SQL manual, belum ada migration runner otomatis; tabel ini
adalah catatan audit untuk menentukan script mana yang sudah dijalankan, bukan chat.


## Panel administrator (/panel)

Tiga menu: konfigurasi AI, checker per room (live + arsip), dan riwayat percakapan.
Room baru dicatat sejak dibuat, termasuk yang belum mempunyai pesan. Kode room
lama tidak dipakai ulang. Room lama yang tidak pernah tercatat di DB tidak dapat
direkonstruksi. Trace checker yang selesai dicatat sejak V6; trace sebelum fitur
ini atau request yang terputus karena proses mati tidak otomatis dipulihkan.

Database lama: sesudah V5, jalankan `SOURCE /docker-entrypoint-initdb.d/003_admin_panel.sql;`
sekali jika `V6__admin_panel` belum ada di schema_migrations. Migrasi ini menambah
panel_configuration, panel_sessions, dan checker_traces tanpa menghapus chat.

Siapkan login di VM dari root repository:

```bash
python3 backend/scripts/setup_panel.py .env.azure
```

Masukkan password administrator yang ditentukan pemilik saat diminta dua kali.
Script memakai library standar Python; hanya hash salted PBKDF2 yang disimpan.
Set username tetap `administrator`. Jangan commit file .env.azure.
Kirim environment `PANEL_USERNAME`, `PANEL_PASSWORD_HASH`, `OPENROUTER_API_KEY`,
dan opsional `OLLAMA_TUNNEL_TOKEN` ke container backend, lalu restart backend.
Compose Azure sudah memuat MySQL, backend satu worker, dan Caddy HTTPS. Lihat AZURE_SETUP.md untuk urutan deploy.
Sesi admin berlaku 8 jam, dapat dicabut melalui logout, dan tidak valid setelah
hash password di environment diganti. Token hanya berada di memori tab browser;
refresh halaman memerlukan login ulang. Jalankan satu worker backend untuk engine game.

API: OpenRouter `qwen/qwen3-14b`. API key dapat diisi langsung melalui menu
Konfigurasi AI di /panel. Kolom kosong mempertahankan key; key baru mengganti yang
tersimpan. Nilainya tidak dikembalikan oleh API panel dan input dibersihkan setelah simpan.
Database menyimpan ciphertext Fernet di JSON panel_configuration (tanpa migrasi tambahan).
OPENROUTER_API_KEY di environment tetap menjadi fallback jika belum ada key dari panel.
Script setup_panel.py menyiapkan PANEL_ENCRYPTION_KEY sekali dan mempertahankannya
saat password admin diganti. Kirim PANEL_ENCRYPTION_KEY ke container backend.
Backup kunci ini terpisah dari database: key panel tidak bisa didekripsi jika kunci
server hilang atau diganti. Pemakaian HTTPS wajib pada deployment publik.
Lokal: Qwen3 `qwen3:14b`, masukkan URL dasar tunnel HTTPS di panel. Endpoint harus
meneruskan POST /api/chat ke Ollama dan model harus sudah diunduh pada mesin lokal.
Jika tunnel menggunakan Bearer auth, set OLLAMA_TUNNEL_TOKEN pada backend.
Konfigurasi provider/URL tersimpan di MySQL dan dimuat ulang saat startup.
Tidak ada fallback otomatis ke provider lain. Tombol Cek AI mengirim prompt pendek
untuk benar-benar menguji jawaban; mode API memakai saldo OpenRouter.

Riwayat menampilkan semua pesan chat yang tercatat, pemain dan bot. Download
menghasilkan CSV UTF-8 (BOM) dengan tepat dua kolom: chat_id, isi_chat. Filter tanggal
opsional menggunakan hari WIB, batas awal inklusif dan akhir sampai penghujung hari.
Download selalu semua room, meski tampilan sedang memilih satu room. CSV mempertahankan
isi pesan persis termasuk tanda kutip dan baris baru; ketika mengimpor ke spreadsheet,
perlakukan isi_chat sebagai teks agar isi pesan tidak dievaluasi sebagai formula.
ID dipakai untuk urutan stabil; pesan baru selama export tidak ditambahkan ke snapshot export.

Di frontend Vercel, route /panel mengarah ke origin BACKEND_URL + /panel, jadi set
BACKEND_URL ke origin HTTPS backend dan redeploy frontend setelah backend tersedia.
Checker publik lama /api/rooms/{code}/checker ditutup (410), dan /games/checker
mengarahkan ke panel. /api/admin lama dan /api/history lama tidak dipasang lagi.


### Pilihan key OpenRouter

Di Konfigurasi AI tersedia `Default dari server` dan `API key sendiri`.
Default membaca `openrouter_default` (atau `OPENROUTER_DEFAULT`) dari environment;
`OPENROUTER_API_KEY` lama tetap didukung jika key default belum diisi.
API key sendiri menggunakan ciphertext yang disimpan melalui panel, tidak beralih
ke key default jika key sendiri kosong atau tidak valid. Pilihan sumber tersimpan
bersama konfigurasi dan berlaku untuk chat game maupun tombol Cek AI.
Beralih ke Default tidak menghapus key sendiri; pilih kembali API key sendiri
untuk memakainya lagi tanpa mengetik ulang. Tidak ada key mentah dalam respons API.
Kedua pilihan tetap OpenRouter, model qwen/qwen3-14b. Restart backend setelah
mengubah environment; perubahan pilihan di panel langsung berlaku untuk request berikutnya.

# Deploy backend ke Azure

File ini untuk memperbarui backend produksi di VM Azure: susunan server, langkah update rutin, backup, menjalankan
migrasi pada database yang sudah berisi, dan pengaturan panel di VM. Pemasangan pertama (DNS, firewall, Google OAuth,
Vercel) ada di [AZURE_SETUP.md](AZURE_SETUP.md). Isi tiap migrasi ada di
[backend/migrations/README.md](../migrations/README.md).

## Susunan produksi

| Bagian | Isi |
| --- | --- |
| Alamat | Backend `https://backendthesis.andylabs.site`, panel `https://backendthesis.andylabs.site/panel`, frontend `https://silent-terror.andylabs.site` (Vercel) |
| Repo di VM | `~/GamesSilentTerror`, dengan secret di `.env.azure` (diabaikan Git, jangan dibagikan) |
| Compose | `docker-compose.azure.yml`, selalu dipakai dengan `--env-file .env.azure` |
| `mysql` | MySQL 8.4.11. Volume eksternal `shadow_heist_mysql_data`; `backend/migrations/` dipasang ke `/docker-entrypoint-initdb.d`. Tanpa port host dan tanpa phpMyAdmin |
| `backend` | Image dari `deployment/Dockerfile.azure`: PyTorch CPU, uvicorn **satu worker**, `--proxy-headers` supaya IP pemain berasal dari Caddy. `AI_PROVIDER=api` |
| `proxy` | Caddy 2 (`deployment/Caddyfile`), port 80 dan 443, sertifikat HTTPS otomatis untuk `BACKEND_DOMAIN`. Baru menyala bila backend sehat |

Image backend menyalin seluruh folder `backend/` kecuali `tests/` (lihat `backend/.dockerignore`). Artinya model
IndoBERT di `backend/artifacts/indobert/{intent,target}` harus sudah ada di VM sebelum build, dan tes tidak ikut di
image.

Semua perintah di bawah dijalankan dari `~/GamesSilentTerror` dengan awalan Compose yang sama:

```bash
cd ~/GamesSilentTerror
sudo docker compose --env-file .env.azure -f docker-compose.azure.yml ps
```

## Update rutin

1. **Pilih waktu tanpa pertandingan.** Membuat ulang backend menghapus pertandingan yang sedang berjalan; arsip chat
   tetap ada.
2. **Ambil kode:** `git pull --ff-only`.
3. **Periksa migrasi baru.** Bandingkan file di `backend/migrations/` dengan isi `schema_migrations` (lihat
   [Menjalankan migrasi](#menjalankan-migrasi-di-database-lama)). File baru **tidak** jalan sendiri karena volume
   produksi sudah berisi data.
4. **Bila ada migrasi baru:** [backup](#backup-database) dulu, lalu jalankan file yang belum tercatat, sebelum backend
   versi baru menyala.
5. **Build dan nyalakan backend:**

   ```bash
   sudo docker compose --env-file .env.azure -f docker-compose.azure.yml up -d --build backend
   ```

   Build bisa memakan sekitar 10 menit bila cache kosong. Bila SSH mudah putus, jalankan di latar dan pantau lognya;
   jangan menyalakan build kedua selama build pertama masih jalan. Contoh ini tanpa `sudo` (yang tidak bisa meminta
   password di latar), jadi pengguna VM harus anggota grup `docker`.

   ```bash
   nohup docker compose --env-file .env.azure -f docker-compose.azure.yml up -d --build backend \
     > /tmp/deploy.log 2>&1 < /dev/null &
   tail -f /tmp/deploy.log
   ```

6. **Periksa hasil:**

   ```bash
   sudo docker compose --env-file .env.azure -f docker-compose.azure.yml ps
   sudo docker compose --env-file .env.azure -f docker-compose.azure.yml logs --tail=60 backend proxy
   curl -fsS https://backendthesis.andylabs.site/ready
   ```

   `/ready` hanya memeriksa migrasi V5 dan V6. Coba juga login, buat room, dan chat dari frontend. Login yang gagal
   dengan 503 sesudah update biasanya berarti ada migrasi yang belum dijalankan.
7. **Bila disk VM menipis**, hapus image dan build cache yang tidak terpakai. Volume jangan disentuh.

   ```bash
   sudo docker image prune -a
   sudo docker builder prune -a
   ```

## Backup database

Sandi root dibaca dari environment container, jadi tidak perlu diketik atau dicetak:

```bash
sudo docker compose --env-file .env.azure -f docker-compose.azure.yml exec -T mysql \
  sh -c 'exec mysqldump -uroot -p"$MYSQL_ROOT_PASSWORD" --single-transaction --routines --triggers shadow_heist' \
  > backup_sebelum_VXX_$(date +%Y%m%d_%H%M).sql
```

Simpan salinan dump di luar VM. Volume eksternal tidak terhapus oleh `down` atau `down -v`, tetapi menghapus volume
secara manual atau kehilangan disk VM tetap menghapus data. Volume bukan backup.

## Menjalankan migrasi di database lama

1. Masuk ke MySQL:

   ```bash
   sudo docker compose --env-file .env.azure -f docker-compose.azure.yml exec mysql \
     sh -c 'exec mysql -uroot -p"$MYSQL_ROOT_PASSWORD" shadow_heist'
   ```

2. Lihat versi yang sudah tercatat: `SELECT version FROM schema_migrations;`
3. Jalankan berurutan file yang versinya belum ada:

   | Versi di `schema_migrations` | Perintah |
   | --- | --- |
   | `V5__chat_history` | `SOURCE /docker-entrypoint-initdb.d/V05__chat_history.sql;` |
   | `V6__admin_panel` | `SOURCE /docker-entrypoint-initdb.d/V06__admin_panel.sql;` |
   | `V7__add_skin_preference` | `SOURCE /docker-entrypoint-initdb.d/V07__add_skin_preference.sql;` |
   | `V7__survey_and_npc` | `SOURCE /docker-entrypoint-initdb.d/V07__survey_and_npc.sql;` |
   | `V8__fix_role_stalker_enum` | `SOURCE /docker-entrypoint-initdb.d/V08__fix_role_stalker_enum.sql;` (pastikan dulu `SELECT COUNT(*) FROM players WHERE role = 'detective';` bernilai 0) |
   | `V9__chat_nlu` | `SOURCE /docker-entrypoint-initdb.d/V09__chat_nlu.sql;` |
   | `V10__match_participants` | `SOURCE /docker-entrypoint-initdb.d/V10__match_participants.sql;` |
   | `V11__survey_player_feedback` | `SOURCE /docker-entrypoint-initdb.d/V11__survey_player_feedback.sql;` |

   Cara lain tanpa masuk client: kirim file lewat stdin,
   `sudo docker compose ... exec -T mysql sh -c 'exec mysql -uroot -p"$MYSQL_ROOT_PASSWORD" shadow_heist' < backend/migrations/V11__survey_player_feedback.sql`.

Database Azure yang dibuat sebelum 26 Oktober 2026 berasal dari baseline lama: penanda `AZURE_BASELINE_1`
menggantikan V1–V4, jadi **jangan jalankan V01–V04 di sana**. Jangan menghapus volume untuk memaksa migrasi. Bila SQL
gagal di tengah, periksa struktur kolom sebelum mengulang, karena `ALTER TABLE` tidak bisa dibatalkan bersama
`INSERT` penanda migrasi.

## Audit tabel

Skema lengkap berisi 15 tabel. `players` berbeda dari `user_accounts`: satu akun bisa menjadi peserta banyak room.

| Tabel | Pemakaian backend |
| --- | --- |
| `user_accounts`, `auth_sessions`, `account_identities` | Akun, sesi login, email dan identitas Google (`models/auth_queries.py`) |
| `game_sessions`, `players` | Identitas room dan peserta room (`models/game_queries.py`) |
| `chat_messages` | Arsip chat manusia dan bot beserta bacaan NLU (`game_queries.py`, `panel_queries.py`) |
| `checker_traces` | Jejak checker yang selesai (`game_queries.py`, `panel_queries.py`) |
| `panel_configuration`, `panel_sessions` | Konfigurasi panel (baris 1 Konfigurasi AI, baris 2 Otak NPC) dan sesi admin (`panel_queries.py`) |
| `survey_questions`, `survey_responses`, `match_bots`, `match_participants` | Survei, metode dan persona bot, peserta pertandingan selesai (`survey_queries.py`) |
| `schema_migrations` | Catatan versi migrasi; dibaca `/ready` |
| `ai_analyses` | Arsip analisis SVM/fuzzy dan balasan bot lama. Tidak ditulis lagi |

Kolom lama `players.aggressiveness`, `players.suspicion_score`, `chat_messages.intent`, dan
`chat_messages.suspicion_score` tidak diisi lagi sejak analisis lama dihapus; datanya dibiarkan sebagai arsip.

**Riwayat chat.** Chat manusia disimpan sebelum disiarkan; chat bot disimpan sebagai baris sendiri. Karena commit
mendahului broadcast, arsip bukan bukti bahwa setiap browser menerima pesannya. Tidak ada penghapusan otomatis saat
logout, keluar room, atau restart. Pesan dari sebelum V5 ditandai `legacy`, dan identitas bot atau ronde lamanya tidak
direka ulang. Room lama yang tidak pernah tercatat di database dan jejak sebelum V6 tidak bisa dipulihkan.

## Panel dan secret di VM

- `setup_azure.py` (pemasangan pertama) atau `python3 backend/scripts/setup_panel.py .env.azure` (ganti password)
  menulis `PANEL_PASSWORD_HASH` dan membuat `PANEL_ENCRYPTION_KEY` sekali. Kunci itu dipertahankan saat password
  diganti. Simpan cadangannya terpisah dari database: key yang disimpan dari panel tidak bisa didekripsi bila kunci
  hilang.
- Username panel tetap `administrator` (diset di Compose). Sesi admin berlaku 8 jam, bisa dicabut lewat logout, dan
  tidak berlaku lagi sesudah hash password diganti. Token panel hanya di memori tab, jadi refresh halaman perlu login
  ulang.
- Variabel lain di `.env.azure`: `GOOGLE_CLIENT_ID`, `FRONTEND_ORIGIN` (menjadi `CORS_ORIGINS`), `BACKEND_DOMAIN`,
  `openrouter_default`, opsional `OPENROUTER_API_KEY`, `OLLAMA_TUNNEL_TOKEN`, dan `NPC_*`. Arti tiap variabel ada di
  [backend/README.md](../README.md#variabel-environment).
- Sesudah mengubah `.env.azure`, terapkan dengan
  `sudo docker compose --env-file .env.azure -f docker-compose.azure.yml up -d backend` (container dibuat ulang).
- Key OpenRouter, link LLM sendiri, dan model penulis bisa diatur langsung dari panel tanpa restart (lihat
  [backend/README.md](../README.md#pengaturan-dari-panel)). Produksi memakai Model OpenRouter `google/gemini-2.5-flash`
  di menu Otak NPC. Link LLM dari laptop dikirim otomatis oleh `ai-docker/jalankan.bat`.
- Frontend Vercel mengalihkan `/panel` ke `BACKEND_URL` + `/panel`. Panel wajib dibuka lewat HTTPS.

# Pemasangan pertama di Azure

File ini berisi langkah sekali jalan untuk menyiapkan backend Silent Terror di VM Azure baru: DNS, firewall, Google
OAuth, file `.env.azure`, model, dan sambungan ke frontend Vercel. Update rutin sesudahnya (backup, migrasi, build)
ada di [README.md](README.md).

| Bagian | Alamat |
| --- | --- |
| Frontend | https://silent-terror.andylabs.site |
| Backend | https://backendthesis.andylabs.site |
| Panel | https://backendthesis.andylabs.site/panel |
| IP publik VM | 70.153.8.162 (cek di Azure bila berubah) |

## 1. DNS dan jaringan

1. DNS dikelola nameserver Vercel, walaupun registrar domainnya Hostinger. Buat A record `backendthesis` →
   IP publik VM di Vercel DNS.
2. Jangan memasang subdomain backend ke project Vercel.
3. Di jaringan VM Azure, izinkan TCP 80 dan 443 masuk. Port MySQL 3306 dan backend 8000 tetap tertutup untuk publik;
   Docker hanya membuka port Caddy. Jaga akses SSH yang sudah ada.
4. Bila UFW aktif, izinkan OpenSSH dulu sebelum mengubah aturan firewall.

## 2. Google login

1. Di Google Cloud > Google Auth Platform > Clients, edit OAuth client jenis Web application yang sudah ada.
2. Isi Authorized JavaScript origins, tanpa garis miring di akhir dan tanpa `/login`:
   - `https://silent-terror.andylabs.site`
   - `https://games-silent-terror.vercel.app` (hanya bila URL lama masih dipakai)
   - `http://localhost:4200` (opsional, untuk development lokal)
3. Authorized redirect URIs boleh kosong. Google Identity Services memakai popup dengan callback JavaScript, lalu
   frontend mengirim ID token ke `/api/auth/google`. Client Secret tidak diperlukan.
4. Atur branding aplikasi, email dukungan dan developer, serta audience di Google Auth Platform. Bila konsol meminta
   test user selama mode Testing, tambahkan akun Google yang dipakai untuk uji.

Jangan pernah meng-commit kredensial Google atau file environment.

## 3. Repo, `.env.azure`, dan model di VM

1. Clone repo ke `~/GamesSilentTerror` dan masuk ke foldernya.
2. Buat `.env.azure`:

   ```bash
   python3 backend/scripts/setup_azure.py
   nano .env.azure
   ```

   Skrip membuat password database dan `PANEL_ENCRYPTION_KEY` yang belum ada, mempertahankan password database yang
   sudah ada, menambah kunci `BACKEND_DOMAIN`, `FRONTEND_ORIGIN`, `GOOGLE_CLIENT_ID`, `openrouter_default`, dan
   `OLLAMA_TUNNEL_TOKEN`, lalu meminta password administrator panel dua kali (minimal 8 karakter). File dibuat dengan
   izin `600`.
3. Di `nano`, isi `GOOGLE_CLIENT_ID` dengan Client ID yang sama dengan `.env` lokal. Opsional, isi
   `openrouter_default` dengan key OpenRouter bawaan, atau atur key sendiri nanti dari panel. Biarkan
   `BACKEND_DOMAIN=backendthesis.andylabs.site` dan `FRONTEND_ORIGIN=https://silent-terror.andylabs.site`.
4. Salin dua folder model IndoBERT dari laptop ke `backend/artifacts/indobert/intent/` dan
   `backend/artifacts/indobert/target/` di VM (mis. dengan `scp -r`). Model ikut masuk image saat build; tanpa model,
   bot tidak bisa chat.

Jangan membagikan `.env.azure`. Mengubah password di file ini nanti tidak merotasi password database yang sudah
diinisialisasi.

## 4. Nyalakan MySQL

```bash
sudo docker volume create shadow_heist_mysql_data
sudo docker compose --env-file .env.azure -f docker-compose.azure.yml up -d mysql
sudo docker compose --env-file .env.azure -f docker-compose.azure.yml ps
```

- Volume baru: MySQL menjalankan semua file di `backend/migrations/` (V01–V12, tanpa V03) berurutan, tanpa akun
  bawaan. Hasil awalnya 15 tabel (termasuk `schema_migrations`), sepuluh pertanyaan survei formal, dan nol akun.
- Volume yang sudah berisi data: migrasi tidak dijalankan ulang. Hentikan, periksa isinya, lalu ikuti
  [README.md](README.md#menjalankan-migrasi-di-database-lama). Jangan menghapus volume untuk memaksa inisialisasi.

Untuk memeriksa tabel (password root diminta di terminal; jangan menempelnya ke chat):

```bash
sudo docker compose --env-file .env.azure -f docker-compose.azure.yml exec mysql mysql -uroot -p shadow_heist
```

```sql
SHOW TABLES;
SELECT COUNT(*) FROM user_accounts;
```

## 5. Nyalakan semua service

```bash
sudo docker compose --env-file .env.azure -f docker-compose.azure.yml up -d --build
sudo docker compose --env-file .env.azure -f docker-compose.azure.yml ps
sudo docker compose --env-file .env.azure -f docker-compose.azure.yml logs --tail=60 backend proxy
curl -fsS https://backendthesis.andylabs.site/ready
curl -fsS https://backendthesis.andylabs.site/api/auth/google/config
```

Caddy mengambil dan memperbarui sertifikat HTTPS sendiri begitu DNS dan port 80/443 berfungsi. `/ready` memeriksa
skema tanpa menghubungi layanan AI. Satu worker backend memang disengaja: ruangan dan nonce Google hidup di satu
proses. Restart backend memutus pertandingan aktif, tetapi tidak menghapus arsip chat.

## 6. Hubungkan Vercel

1. Di project Vercel `games-silent-terror`, environment Production, isi
   `BACKEND_URL=https://backendthesis.andylabs.site`.
2. Redeploy frontend hanya sesudah `/ready` lewat HTTPS berhasil.
3. `GOOGLE_CLIENT_ID` dibaca frontend dari backend, jadi bukan secret build frontend.
4. CORS di backend diatur lewat `FRONTEND_ORIGIN` di `.env.azure`. Bila kedua domain frontend dipakai, isi keduanya
   sebagai origin HTTPS lengkap dipisah koma.
5. Uji dari domain frontend asli: login Google, buat room, chat WebSocket, login `/panel`, dan unduh riwayat chat.
   Login Google sungguhan butuh pemilik akun di browser; unit test tidak bisa memeriksa konfigurasi Google Cloud.

Rincian deploy frontend ada di [frontend/DEPLOYMENT.md](../../frontend/DEPLOYMENT.md).

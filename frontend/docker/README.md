# Frontend Docker untuk kerja bareng

Frontend Angular berjalan di laptop teman; API, WebSocket, AI, dan database tetap memakai backend VPS `https://backendthesis.andylabs.site`. Perubahan CSS/HTML/TypeScript dalam `frontend/src` dan aset `frontend/public` otomatis dimuat ulang. Tidak perlu memasang Node.js, MySQL, atau model AI di laptop.

## 1. Persiapan laptop

Pasang Git dan Docker Desktop, lalu jalankan Docker Desktop (Linux containers). Clone repo yang sudah diberikan akses:

```bash
git clone https://github.com/Andysaputra1/GamesSilentTerror.git
cd GamesSilentTerror/frontend/docker
```

Salin contoh env. PowerShell Windows:

```powershell
Copy-Item .env.example .env
```

CMD Windows: `copy .env.example .env`. macOS/Linux: `cp .env.example .env`.

Isinya sudah mengarah ke VPS:

```dotenv
BACKEND_URL=https://backendthesis.andylabs.site
FRONTEND_PORT=4200
```

Env frontend ini hanya berisi alamat publik. API key OpenRouter, password database, dan env Azure tetap di backend; tidak perlu dibagikan kepada pengembang frontend. Semua akun, room, dan chat yang dibuat dari frontend lokal memakai data server yang sama dengan website utama.

## 2. Izinkan frontend lokal di backend VPS (Andy, sekali saja)

Koneksi browser membutuhkan izin CORS pada backend. Dalam `~/GamesSilentTerror/.env.azure`, ubah/tambahkan satu baris berikut. Pertahankan domain frontend produksi:

```dotenv
FRONTEND_ORIGIN=https://silent-terror.andylabs.site,http://localhost:4200,http://127.0.0.1:4200
```

Jika sudah ada origin lain yang diperlukan, pertahankan juga dan pisahkan dengan koma. Tidak ada slash penutup. Di terminal VPS:

```bash
cd ~/GamesSilentTerror
nano .env.azure
```

Simpan dengan Ctrl+O, Enter, lalu keluar Ctrl+X. Terapkan:

```bash
sudo docker compose --env-file .env.azure -f docker-compose.azure.yml up -d backend
```

Compose memuat perubahan env dengan membuat ulang backend. Pertandingan aktif di memori akan ter-reset, sedangkan riwayat database tetap ada; lakukan saat tidak ada pertandingan berjalan. Jangan membuka port MySQL untuk frontend.

Untuk tombol Google Login, tambahkan `http://localhost:4200` dan `http://127.0.0.1:4200` ke **Authorized JavaScript origins** pada OAuth Web Client yang dipakai backend. Pertahankan origin produksi. Client ID diambil frontend dari backend, jadi tidak perlu env Google di Docker frontend. Alur popup saat ini tidak membutuhkan redirect URI baru. Login akun biasa dapat dipakai untuk menguji tanpa Google.

## 3. Jalankan frontend

Dari `frontend/docker`:

```bash
docker compose --env-file .env -f docker-compose.yml up -d --build
docker compose --env-file .env -f docker-compose.yml logs -f frontend
```

Tunggu kompilasi Angular selesai, lalu buka **http://localhost:4200**. Ctrl+C pada tampilan log hanya menghentikan tampilan log; container tetap berjalan. Docker pertama kali mengunduh image dan dependency sehingga lebih lama.

Edit file di `frontend/src` atau `frontend/public` memakai editor di laptop. Docker membaca perubahan lewat bind mount dan Angular memperbarui halaman. Dependency dipasang di image, terpisah dari `node_modules` laptop. Konfigurasi ini untuk pengembangan lokal, bukan server publik.

Jika mengubah package.json/package-lock.json, angular.json, script, atau Dockerfile, ulangi `up -d --build`. Jika mengubah `.env`, ulangi `up -d` agar container dibuat ulang. File `src/environments/environment.vercel.ts` dibuat otomatis saat container mulai dan diabaikan Git; jangan edit manual. Hindari menjalankan build Vercel pada checkout yang sama ketika container ini aktif karena memakai file generated yang sama.

## 4. Perintah harian

Jalankan dari `frontend/docker`, supaya tidak menjalankan stack backend di folder root repo:

```bash
# Status
docker compose --env-file .env -f docker-compose.yml ps
# Berhenti dan hapus container frontend lokal
docker compose --env-file .env -f docker-compose.yml down
# Setelah mengambil update repo
git pull
docker compose --env-file .env -f docker-compose.yml up -d --build
```

Kerjakan perubahan pada branch sendiri agar push teman tidak langsung men-deploy produksi: dari folder repo, `git switch -c frontend/nama-fitur`, lalu buat pull request ke main.

## 5. Jika koneksi gagal

- UI terbuka tetapi API/CORS gagal: pastikan langkah CORS VPS sudah diterapkan, lalu buka tepat `http://localhost:4200`.
- WebSocket gagal: izin origin backend juga dipakai Socket.IO. Pastikan HTTPS backend bisa dijangkau dan port 443 VPS terbuka.
- Google menampilkan origin mismatch: cek Authorized JavaScript origins sesuai alamat browser, termasuk port.
- Port 4200 terpakai: ubah FRONTEND_PORT (misalnya 4201), lalu tambahkan origin `http://localhost:4201` pada CORS dan Google sebelum menjalankan ulang.
- Perubahan src tidak muncul: lihat log kompilasi; polling file aktif setiap 1 detik. Pastikan folder repo diizinkan untuk Docker Desktop.
- Backend tidak bisa dihubungi: buka `https://backendthesis.andylabs.site/ready`. VM harus menyala.

Referensi: [Docker Compose](https://docs.docker.com/reference/cli/docker/compose/) dan [konfigurasi environment Angular](https://angular.dev/tools/cli/environments).

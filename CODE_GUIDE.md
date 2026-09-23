# Panduan membaca kode

Mulai dari alur di bawah sebelum membuka detail implementasi. Backend menentukan
izin, fase, role, dan kemenangan. Frontend menampilkan snapshot serta mengirim
permintaan pengguna.

## Peta folder

| Lokasi | Tanggung jawab |
| --- | --- |
| `frontend/src/app/features/` | Halaman login, menu utama, lobby, dan permainan |
| `frontend/src/app/core/` | Request API, sesi, guard navigasi, dan komponen profil |
| `frontend/src/app/app.routes.ts` | Route frontend dan guard yang harus dilalui |
| `frontend/docker/start.mjs` | Menjalankan frontend lokal menggunakan konfigurasi publik |
| `backend/main.py` | Startup FastAPI, Socket.IO, model analisis, dan lifecycle server |
| `backend/controller/controller_main.py` | Daftar router HTTP yang aktif |
| `backend/controller/api/` | Validasi request, autentikasi route, dan respons HTTP |
| `backend/services/` | Aturan aplikasi, pertandingan, analisis, dan transaksi |
| `backend/models/` | Kueri SQL berparameter |
| `backend/realtime/socket_handlers.py` | Autentikasi socket, chat, dan pengiriman balasan NOX |
| `backend/config/` | Konfigurasi environment, database, dan kebijakan upload |
| `backend/controller/middleware/` | Autentikasi request, batas percobaan login, dan CORS |
| `backend/module/` | Koneksi database, klien AI, helper upload, dan CLI akun |
| `backend/public/panel/` | Halaman administrasi yang disajikan backend |
| `backend/scripts/` | Penyiapan environment deployment dan kredensial panel |
| `backend/tests/` | Unit/integration test serta skrip smoke test manual |

Daftar router di `controller_main.py` adalah acuan endpoint aktif. Modul admin,
history, dan checker lama masih memiliki pemeriksaan kompatibilitas; keberadaan
file saja tidak berarti route tersebut dibuka pada aplikasi utama.

## Alur utama

1. **Login dan registrasi:** komponen `Auth` mengirim request ke controller auth.
   Service akun/autentikasi memvalidasi identitas dan menyimpan hash token sesi.
   Google memakai nonce sekali pakai dan verifikasi token di backend.
2. **Pemulihan sesi:** guard dan `ActiveMatchService` mencari pertandingan aktif
   dari server. Pointer ruangan di browser membantu navigasi; role dan izin tetap
   berasal dari snapshot privat backend.
3. **Lobby:** `Lobby` → `RoomService` frontend → controller rooms → `RoomService`
   backend. Keanggotaan dan pertandingan aktif tersimpan di memori proses backend.
   Restart backend menghapus ruangan aktif, sedangkan arsip database tetap ada.
4. **Permainan:** `GameService` mengirim aksi ke server. `Match` memvalidasi role,
   target, fase, dan cooldown; menyelesaikan malam/Tribunal; kemudian menentukan
   hasil. `snapshot(viewer)` membatasi informasi sesuai pemain yang melihatnya.
   Aturan kemenangan dijelaskan lebih lengkap di `GAME_CONCEPT.md`.
5. **Chat dan AI:** handler socket memeriksa sesi serta hak chat, menyimpan pesan,
   menjalankan analisis intent dan fuzzy, lalu meminta balasan provider AI.
   Handler memeriksa konteks permainan sebelum mengirim balasan yang terlambat.
6. **Logout:** `ProfileMenu` → `SessionService` → endpoint logout. Setelah token
   dicabut atau sudah tidak berlaku, data sesi browser dibersihkan dan pengguna
   diarahkan ke login. Kegagalan jaringan ditampilkan agar dapat dicoba ulang.
7. **Panel:** sesi administrator terpisah dari pemain. Panel membaca arsip dan
   menyimpan konfigurasi AI; nilai API key tidak dikirim kembali ke browser.

## Aturan penulisan

- Python memakai empat spasi dan Black dengan lebar target 100 karakter.
- TypeScript, JavaScript, HTML, JSON, dan YAML memakai Prettier, dua spasi,
  serta lebar target 100 karakter.
- Komentar di atas fungsi menjelaskan tujuan, batasan, atau efek pentingnya.
  Docstring yang sudah menjelaskan kontrak fungsi tetap dipertahankan.
- Beri komentar di dalam fungsi untuk urutan yang penting, misalnya penyimpanan
  sebelum broadcast, pencegahan respons basi, dan pemeriksaan informasi privat.
- Nama test menjelaskan skenario dan hasil yang diuji; helper test menyiapkan
  data tiruan tanpa memanggil layanan produksi.
- CSS/SCSS dan isi CSS embedded tidak masuk perapian ini. Dependency, hasil build,
  lockfile, environment lokal, upload pengguna, dan model biner juga dikecualikan.
- Sebelum menghapus simbol, periksa route, binding template, decorator, event,
  entry point CLI/deployment, dan test. Referensi dinamis tidak selalu terlihat
  sebagai pemanggilan fungsi biasa.

## Formatter dan pemeriksaan

Pasang dependency frontend dengan `npm install` dari root. Untuk lingkungan
pengembangan Python, gunakan virtual environment lalu pasang
`python -m pip install -r backend/requirements-dev.txt`.

```sh
npm run format
npm run format:check
python -m ruff check backend
npm --prefix frontend test -- --watch=false
```

Jalankan suite Python dari folder backend:

```sh
python -m unittest discover -s tests -p "test_*.py"
```

Skrip `live_auth_smoke.py`, `live_match_smoke.py`, dan `mysql_smoke.py` adalah alat
manual yang dapat mengakses layanan/database sesuai konfigurasinya; skrip ini
tidak dijalankan oleh pola `test_*.py` di atas.

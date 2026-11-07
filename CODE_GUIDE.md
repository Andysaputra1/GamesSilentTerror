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
| `backend/app/` | Semua kode aplikasi: entry point, controller, socket, service, game, bot, model, konfigurasi |
| `backend/app/main.py` | Startup FastAPI, Socket.IO, model analisis, dan lifecycle server |
| `backend/app/controllers/routes.py` | Daftar router HTTP yang aktif |
| `backend/app/controllers/` | Validasi request, autentikasi route, dan respons HTTP |
| `backend/app/services/` | Aturan login dan Google (`auth_service.py`), panel (`panel_service.py`), chat manusia (`chat_service.py`), penyimpanan chat dan jejak (`persistence_service.py`), room dan tindakan bot (`room_service.py`), password, survei, checker, konfigurasi AI, dan klien Ollama |
| `backend/app/game/match_engine.py` | Engine pertandingan: role, fase, skill, vote, kemenangan, snapshot privat |
| `backend/app/bot/` | Bot NPC: `bot_controller.py` (urutan langkah bot dan otak bersama), `nlu.py` (IndoBERT membaca chat), `fuzzy_1.py` (Fuzzy Mamdani [FUZZY 1]: menilai pemain), `fuzzy_2.py` (Fuzzy Mamdani [FUZZY 2]: memilih tindakan), `nlg.py` (kalimat dan rantai penulis LLM), `penjelasan.py` (penjelasan untuk panel), `simulasi.py` (simulasi panel) |
| `backend/app/models/` | Kueri SQL berparameter |
| `backend/app/sockets/server.py` | Membuat `sio`, mencatat sambungan, dan mengirim ke room (`emit_room`) |
| `backend/app/sockets/chat.py` | Event `connect`, `disconnect`, dan `send_chat`; penolakan chat dikirim sebagai `system_alert` |
| `backend/app/config/` | Konfigurasi environment, koneksi database, dan daftar skin |
| `backend/app/middleware/` | Autentikasi request, batas percobaan login, CORS, dan respons validasi |
| `backend/public/panel/` | Halaman administrasi yang disajikan backend |
| `backend/scripts/` | CLI akun, penyiapan environment deployment, dan kredensial panel |
| `backend/tests/` | Unit/integration test, skenario bot (`test_skenario_fuzzy.py`, `test_skenario_nlg.py`), alat jejak keputusan bot (`jejak/`), serta skrip smoke test manual |

Daftar router di `controllers/routes.py` adalah acuan endpoint aktif. Modul admin,
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
   Chat tim malam memakai `POST /api/rooms/{code}/team-chat`: pesannya hanya di memori
   `Match` dan `me.team_messages`, sengaja tanpa socket, database, NLU, atau `@traced`.
   Aturan kemenangan dijelaskan lebih lengkap di `GAME_CONCEPT.md`.
5. **Chat dan AI:** `services/chat_service.py` memeriksa sesi/hak chat, lalu menyimpan dan
   menyiarkan pesan; sesudah terkirim IndoBERT membacanya lewat `catat_nlu`. Pada pertandingan,
   `NPCService` (`bot/bot_controller.py`) mengambil langkah mandiri dari timer untuk setiap bot:
   `room_service.lihat_untuk_bot` (snapshot privat) -> `Ingatan.sinkron_snapshot` -> `nlu.baca_chat_baru`
   (IndoBERT) -> `fuzzy_2.putuskan` -> vote/aksi lewat `room_service.pilihan_bot` -> kalimat `nlg.py` yang
   dicek aturan -> `room_service.chat_bot` -> `emit_room`. Bot memakai service yang sama dengan pemain dan
   tidak mengubah `Match` langsung. Fase diperiksa ulang sebelum keputusan diterapkan. Vote/aksi langsung
   diterapkan; chat bot melewati
   "lantai bicara" (`NPCService._ambil_giliran_bicara`): paling banyak `LANTAI_MAKS` (3) bot
   menyusun/mengetik bersamaan per pertandingan tanpa rencana kembar (intent + target
   sama), dan rencana yang lebih tua dari chat bot lain dibatalkan lalu diputuskan
   ulang. Utility AI dan Behavior Tree diarsipkan di luar
   repo, di `../arsip_bt_utility_2026-11-03/` (cara menariknya kembali ada di README folder
   itu). Nilai lama `campuran`, `utility`, dan `bt` di `.env` atau `panel_configuration`
   dibaca sebagai `fuzzy`, dan jejak lama tetap bisa dibuka di panel. Angka keseimbangan di
   `GAME_CONCEPT.md` sudah diukur ulang dengan Fuzzy saja (6 November 2026).
   Setelah Mulai, `Match` berada di fase `preparing` sampai otak bot siap.
6. **Logout:** `ProfileMenu` → `SessionService` → endpoint logout. Setelah token
   dicabut atau sudah tidak berlaku, data sesi browser dibersihkan dan pengguna
   diarahkan ke login. Kegagalan jaringan ditampilkan agar dapat dicoba ulang.
7. **Panel:** sesi administrator terpisah dari pemain. Panel membaca arsip dan
   menyimpan konfigurasi AI; nilai API key tidak dikirim kembali ke browser.
   Checker per room menampilkan penjelasan setiap langkah bot yang dibuat
   `backend/app/bot/penjelasan.py` di `BrainRuntime.langkah` (identitas, parameter,
   penalaran fuzzy, keputusan) dan dilengkapi hasil engine/NLG di
   `isi_jejak` (`bot/bot_controller.py`). Daftar jejak hanya membawa `ringkas`; penjelasan lengkap
   diambil per jejak lewat `GET /api/panel/checker/{code}/jejak/{id}`.

## Mengubah logika bot

Kode bot di `backend/app/bot/` adalah sumber logikanya dan diubah langsung di sana. Notebook skripsi
(`training/prethesis/ai_2_dataset_baru/npc_fuzzy.ipynb` dan `npc_nlg.ipynb`) hanya untuk laporan; tidak ada
lagi ekspor notebook ke backend. Bila logika bot berubah, perbarui juga notebook supaya skripsi tetap
menggambarkan game.

- Otak Fuzzy terbagi dua file. `bot/fuzzy_1.py` [FUZZY 1] menilai pemain: mesin Mamdani, `Ingatan` dan bahan
  bukti, kecurigaan dari sudut pandang warga (7 sistem), serta ancaman dan kambing hitam untuk Hitman (4 sistem).
  `bot/fuzzy_2.py` [FUZZY 2] memilih tindakan per sesi (Diskusi, Tribunal, Aksi Malam; tiap sesi semua role dulu,
  lalu per role) dengan 10 sistem keputusan, lalu `putuskan` menggabungkan semuanya. `fuzzy_2` mengimpor
  `fuzzy_1`, tidak sebaliknya; sistem [FUZZY 2] didaftarkan ke mesin `fuzzy_1` lewat `daftarkan_sistem`.
- Pembacaan chat: `bot/nlu.py`. Kalimat dan pemeriksa aturan: `bot/nlg.py`.
- Urutan satu langkah bot dan penjadwalannya: `bot/bot_controller.py`.

Sebelum dan sesudah mengubah atau merapikan kode bot:

```sh
cd backend
python -m unittest tests.test_skenario_fuzzy tests.test_skenario_nlg
python tests/jejak/rekam_jejak.py --cek
```

`test_skenario_fuzzy.py` berisi 328 skenario berlabel dari notebook, `test_skenario_nlg.py` pengujian
payload, pemeriksa aturan, templat, dan prompt. `rekam_jejak.py --cek` membandingkan sidik keputusan bot
pada seed tetap dengan `tests/jejak/sidik.json`. Perapian yang tidak mengubah logika harus memberi sidik
yang sama. Perubahan logika yang disengaja mengubah sidik; setelah skenario lulus dan perubahan diterima,
simpan sidik baru dengan `--tulis`.

## Profil dan manajemen akun

- Form daftar memakai username, nama lengkap, password, dan konfirmasi password.
  Email dari frontend lama tetap diterima API selama transisi deployment.
- Akun Google baru memakai username acak dan nama dari token Google terverifikasi.
  Login ulang tidak menimpa nama/username yang sudah diedit pengguna.
- Ikon pensil profil menyimpan nama dan username melalui `POST /api/auth/me`.
  Username hanya dapat diganti setelah keluar dari ruangan. ID akun dan identitas
  Google tetap sama; nama pengirim pada arsip chat tetap sesuai saat pesan dikirim.
- Menu Manajemen user di `/panel` memakai controller `controllers/users.py` dan service
  `services/user_service.py`. Hanya sesi administrator panel yang diizinkan.
- Tambah user membuat akun username/password dengan nama lengkap, tanpa membuat
  sesi login pemain. Akun Google dibuat melalui alur Google yang terverifikasi.
- Edit user mengubah nama/username lewat panel. Rename ditolak jika masih di room;
  rename mencabut sesi lama, sementara identitas Google dan arsip chat tetap utuh.
- Reset password hanya untuk akun lokal dan mencabut seluruh sesi akun tersebut.
  Akun Google harus mengelola password melalui Google.
- Penghapusan memerlukan konfirmasi username dan user harus keluar dari ruangan.
  Yang dihapus hanya akun, identitas login, dan sesi. Chat, analisis, serta jejak
  checker tetap disimpan. Fitur ini memakai tabel yang sudah ada, tanpa migrasi baru.

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

Filter riwayat panel dan download CSV memakai tanggal WIB, room, dan sender_kind yang sama (all/human/bot/legacy). Legacy tidak ditebak sebagai manusia atau bot. CSV berisi teks_chat dan chat_id, lalu bacaan IndoBERT saat game
berjalan: intent, confidence, target, dan konteks (maks 12 chat sebelumnya yang ikut dibaca; kosong untuk pesan lama).

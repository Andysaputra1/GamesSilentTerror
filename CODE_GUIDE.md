# Panduan kode

File ini untuk orang yang akan membaca atau mengubah kode. Isinya susunan folder, aturan antarlapisan, alur utama,
letak otak bot, gaya penulisan kode, serta cara menjalankan tes dan simulasi. Aturan permainan dan perilaku bot ada di
[GAME_CONCEPT.md](GAME_CONCEPT.md); cara menjalankan aplikasi ada di [README.md](README.md).

## Prinsip dasar

- **Backend sumber kebenaran.** Izin, fase, role, dan kemenangan ditentukan engine di
  `backend/app/game/match_engine.py`. Frontend hanya menampilkan snapshot dan mengirim permintaan pengguna.
- **Bot adalah pemain tanpa browser.** Bot memakai service yang sama dengan pemain (`services/room_service.py`) dan
  tidak mengubah `Match` langsung.
- **Pertandingan hidup di memori satu proses.** MySQL menyimpan akun, arsip chat, jejak, dan survei, bukan state
  pertandingan. Lihat [Batas implementasi](#batas-implementasi).

Istilah yang sering muncul:

| Istilah | Arti |
| --- | --- |
| `Match` | Objek engine untuk satu pertandingan: roster, role, fase, aksi, vote, pemenang |
| Snapshot | Data pertandingan yang dibuat engine untuk **satu** pemain (`Match.snapshot(nama)`); informasi privat pemain lain tidak ikut |
| Token fase | Pasangan `match_id`, `round_number`, dan `phase` yang dikirim bersama aksi. Aksi dengan token basi ditolak |
| Ingatan | Catatan satu bot selama pertandingan (`bot/ingatan.py`): chat, vote, dan fakta yang pernah dilihat |
| Jejak (trace) | Catatan tahap dan durasi satu chat manusia atau satu langkah bot, ditampilkan di panel Checker |
| Sidik | Hash sha256 dari keputusan bot pada seed tetap (`tests/jejak/sidik.json`), untuk membuktikan logika tidak berubah |

## Peta folder

```text
backend/
  app/
    main.py                 Entry point ASGI (app.main:asgi_app): pasang Socket.IO, muat konfigurasi, otak bot, jam 0,5 detik
    config/                 settings.py (environment), mysql.py, database.py (pool, jalankan_transaksi), skins.py
    controllers/            API HTTP; routes.py menggabungkan router yang aktif
      auth.py health.py rooms.py survey.py users.py panel.py panel_npc.py
    middleware/             auth.py (bearer token), auth_limits.py (batas percobaan), cors.py, safe_validation.py (422 tanpa isi input)
    sockets/                server.py (membuat sio, emit_room), chat.py (event connect, disconnect, send_chat)
    services/               Aturan aplikasi dan transaksi
      auth_service.py         login, daftar, Google, sesi pemain
      room_service.py         lobby, lock, tindakan pemain dan bot ke Match
      chat_service.py         chat manusia: cek → simpan → kirim → IndoBERT membaca
      survey_service.py       survei, arsip peserta, urutan pertanyaan
      panel_service.py        sesi admin, konfigurasi, arsip room, riwayat dan CSV
      persistence_service.py  simpan chat, jejak, arsip room per transaksi
      user_service.py password_service.py checker_service.py activity_service.py
      ai_config_service.py npc_config_service.py ai_diagnostics.py ollama_client.py
    models/                 SQL langsung: auth_queries, game_queries, panel_queries, survey_queries
    schemas/                Validasi request dan respons (Pydantic)
    game/match_engine.py    Engine murni: role, fase, skill, vote, kemenangan, snapshot privat
    bot/                    Otak bot (lihat Otak bot di kode)
  public/panel/             Halaman panel administrator (HTML, CSS, JS)
  public/dokumen/           Dokumen web panel menu 08 (salinan dari communicationfolder/)
  artifacts/indobert/       Model IndoBERT intent dan target (disalin manual, diabaikan Git)
  migrations/               Skema SQL V01–V11
  deployment/               Dockerfile.azure dan Caddyfile
  scripts/                  Alat operasional: create_user.py, setup_panel.py, setup_azure.py
  tests/                    Tes, tiruan, rekaman jejak, simulasi (lihat Tes dan simulasi)
frontend/src/app/
  features/                 Halaman: auth, main-page, lobby, game, panel (pengalih ke /panel backend)
  core/                     Request API, sesi, guard navigasi, profil, survei, pemulihan pertandingan aktif
  app.routes.ts             Route frontend dan guard
frontend/docker/start.mjs   Menjalankan frontend lokal dengan konfigurasi publik (npm start dari root)
proxy/nginx.conf            Gateway lokal: backend, Socket.IO, dan phpMyAdmin di port 8000
ai-docker/                  LLM di laptop + tunnel untuk VM
```

`controllers/routes.py` adalah acuan endpoint yang aktif. Daftar endpoint juga terlihat di http://localhost:8000/docs.

## Aturan lapisan

| Lapisan | Tugas | Larangan |
| --- | --- | --- |
| `controllers/` | Validasi request lewat `schemas/`, autentikasi route, panggil service, terjemahkan error ke HTTP | Tidak membuka transaksi database dan tidak menulis SQL |
| `middleware/` | Bearer token, batas percobaan login, CORS, respons 422 | Tidak berisi aturan permainan |
| `sockets/` | Event Socket.IO. Socket hanya untuk chat publik; aksi dan snapshot lewat HTTP | Tidak memutuskan hak chat sendiri; memanggil `chat_service` |
| `services/` | Aturan aplikasi, lock, dan batas transaksi (`jalankan_transaksi`) | Tidak mengimpor `fastapi`, karena dipakai controller maupun bot |
| `models/` | SQL langsung dengan `sqlalchemy.text` dan parameter terikat | Tidak berisi aturan HTTP dan tidak menulis respons API |
| `game/` | Aturan murni pertandingan | Tidak bergantung pada HTTP, Socket.IO, MySQL, atau LLM |
| `bot/` | Berpikir: membaca snapshot, memutuskan, menulis kalimat | Tanpa SQL; bertindak lewat `services/room_service.py` |

Tiga aturan pertama diuji `tests/test_structure.py`: SQL `text` hanya di `models/` (kecuali `SELECT 1` pemeriksa
koneksi di `config/database.py`), controller tidak membuka transaksi, dan service tidak mengimpor `fastapi`.

Arah panggilan:

```text
HTTP       -> controllers -> services -> game (Match) / models (SQL) -> MySQL
Socket.IO  -> sockets/chat.py -> services/chat_service.py -> models -> MySQL -> emit_room
Jam 0,5 dtk (main.py) -> room_service.perbarui_fase_semua_room       (fase yang habis berganti)
                      -> npc_service.jalankan_bot_yang_sudah_waktunya (bot yang sudah waktunya melangkah)
```

Contoh SQL di model dan pemakaiannya dari service ada di [backend/README.md](backend/README.md#pola-sql-di-model).

## Alur utama

1. **Login dan daftar.** Komponen `Auth` memanggil `controllers/auth.py`; `auth_service` memvalidasi identitas dan
   menyimpan hash token sesi. Rinciannya di [Akun, sesi, dan login](#akun-sesi-dan-login).
2. **Pemulihan sesi.** Guard dan `ActiveMatchService` menanyakan pertandingan aktif ke server
   (`GET /api/rooms/active`). Akun yang masih bertanding dikembalikan ke `/game`, dari tab mana pun. Role dan izin
   tetap berasal dari snapshot backend, bukan storage browser.
3. **Lobby.** `Lobby` → `RoomService` frontend → `controllers/rooms.py` → `room_service`. Keanggotaan ruangan ada di
   memori proses backend.
4. **Mulai.** Host memanggil `POST /api/rooms/{code}/start`. `Match` dibuat (role acak) dan berada di fase
   `preparing` sampai otak bot siap atau batas tunggu habis.
5. **Aksi pemain.** `GameService` mengirim aksi ke `POST /api/rooms/{code}/play` bersama token fase. `room_service`
   memajukan fase, mencocokkan token, lalu memanggil `Match.act` atau `Match.vote`. Engine memeriksa role, target,
   fase, dan cooldown. Browser membaca `GET /api/rooms/{code}/game` tiap 1 detik; `snapshot(viewer)` membatasi
   informasi sesuai pemain yang melihat.
6. **Chat tim malam.** `POST /api/rooms/{code}/team-chat`. Pesannya hanya di memori `Match` dan
   `me.team_messages`, sengaja tanpa socket, database, NLU, atau `@traced`.
7. **Chat publik manusia.** `sockets/chat.py` (`send_chat`) → `chat_service.kirim_chat_pemain`: cek pesan dan sesi →
   cek hak chat (`can_chat`) → simpan ke MySQL → kirim `receive_chat` ke room → IndoBERT membacanya lewat
   `catat_nlu`. Penolakan dikirim ke pengirim sebagai `system_alert`. Sebelum broadcast, `emit_room` mengeluarkan
   socket yang sudah keluar room atau sesinya dicabut.
8. **Langkah bot.** Lihat [Satu langkah bot](#satu-langkah-bot).
9. **Panel.** Sesi administrator terpisah dari pemain. Checker menampilkan penjelasan tiap langkah bot yang dibuat
   `bot/penjelasan.py` di `BrainRuntime.langkah`, dilengkapi hasil engine dan NLG di `isi_jejak`
   (`bot/bot_controller.py`). Daftar jejak hanya membawa `ringkas`; penjelasan lengkap diambil per jejak lewat
   `GET /api/panel/checker/{code}/jejak/{id}`. Nilai API key tidak pernah dikirim balik ke browser.
10. **Logout.** `ProfileMenu` → `SessionService` → `POST /api/auth/logout`. Sesudah token dicabut atau kedaluwarsa,
    data sesi browser dibersihkan dan pengguna diarahkan ke login. Logout tidak menghentikan pertandingan.

## Otak bot di kode

Semua logika bot ada di `backend/app/bot/`. Kode inilah sumber logika game; notebook skripsi hanya laporan.

| File | Isi |
| --- | --- |
| `bot_controller.py` | `NPCService` (jadwal dan urutan satu langkah bot, lantai bicara) dan `BrainRuntime` (otak bersama: memuat NLU, fuzzy, dan penulis; ingatan dan persona tiap bot) |
| `nlu.py` | IndoBERT membaca chat: intent, lalu target; aturan nama untuk pesan netral; memo bersama semua bot |
| `ingatan.py` | Bahan: `Ingatan` satu bot, lalu chat, vote, dan fakta menjadi angka bukti 0–1 per pemain (`hitung_bukti`, `pengetahuan_peran`, `fitur_hitman`, `fitur_lindung`). Tidak ada fuzzy di sini |
| `fuzzy_controller.py` | Main controller: `putuskan` dan semua logika di sekitar pemanggilan fuzzy, berurutan [FUZZY 1] → Tribunal → Diskusi → Malam → bungkus keputusan |
| `fuzzy/` | Fungsi fuzzy saja: satu sistem = satu fungsi. `mesin.py` berisi kurva, pembangun sistem Mamdani, cache, dan `SEMUA_SISTEM` |
| `nlg.py` | Penulis kalimat: rantai LLM (OpenRouter, lalu link LLM sendiri), templat, pemeriksa aturan, chat tim |
| `penjelasan.py` | Penjelasan keputusan bot untuk panel Checker |
| `simulasi.py` | Simulasi panel menu 07 dengan engine, otak, NLU, dan NLG yang sama |

Arah impor: `fuzzy_controller` mengimpor `ingatan` dan `fuzzy/`; `ingatan` tidak mengimpor file bot lain; file di
`fuzzy/` hanya mengimpor `fuzzy/mesin.py`. `BrainRuntime._muat` memuat modul otak saat server menyala.

### Satu langkah bot

Jam di `main.py` memanggil `NPCService.jalankan_bot_yang_sudah_waktunya` tiap 0,5 detik. Untuk bot yang sudah
waktunya:

1. `room_service.lihat_untuk_bot`: snapshot privat bot dan token fase yang ia lihat.
2. `BrainRuntime.langkah`: `Ingatan.sinkron_snapshot` mencatat snapshot → `nlu.baca_chat_baru` membaca chat baru
   dengan IndoBERT → `fuzzy_controller.putuskan`.
3. `room_service.pilihan_bot`: vote atau aksi rahasia diterapkan hanya bila fase yang dilihat bot belum berganti.
4. Chat tim bila ada rekan manusia (`room_service.chat_tim_bot`), tanpa lantai bicara, database, siaran, atau NLU.
5. Chat publik: `NPCService._ambil_giliran_bicara` (lantai bicara, paling banyak `LANTAI_MAKS` = 3 bot menyusun
   bersamaan tanpa rencana kembar) → kalimat `nlg.py` yang dicek aturan → `room_service.chat_bot` (simpan) →
   `emit_room("receive_chat")`.
6. Jejak untuk panel (`isi_jejak`), lalu IndoBERT membaca kalimat bot itu.

### Urutan `putuskan`

`putuskan(ingatan, view)` adalah satu-satunya fungsi keputusan yang dipanggil game dan simulasi. Docstring di atas
`fuzzy_controller.py` menuliskan isinya berurutan; ringkasnya:

1. **[FUZZY 1] Menilai pemain.** Warga: `hitung_bukti` → pohon kecurigaan (7 sistem) → fakta pasti menimpa
   (`terapkan_pengetahuan`). Hitman: bukti publik → kecurigaan → `fitur_hitman` → ancaman dan kambing hitam
   (4 sistem).
2. **Tribunal.** Pindah suara saat waktu tambahan, vote pasti (hasil Peek), lalu `keputusan_vote` (warga:
   `keyakinan_vote` → `kesiapan_vote` → ambang → paksa vote) atau `keputusan_vote_hitman`.
3. **Sesi Diskusi.** `chat_pasti` bila hasil Peek harus diungkap, selain itu `keputusan_chat`: calon chat →
   sistem `fuzzy/diskusi.py` → urutkan → `AMBANG_CHAT`.
4. **Aksi Malam.** `keputusan_aksi`: calon Hostage, Gag, Guard, atau Peek → sistem `fuzzy/malam.py` (Gag, Peek) →
   pilih.
5. **Bungkus.** `format_npc` (untuk engine), `siapkan_nlg` (untuk penulis kalimat), `siapkan_nlg_tim` (chat tim).

Di dalam tiap sesi, logika untuk semua role ditulis dulu, lalu per role.

### Daftar sistem fuzzy

Semua sistem memakai dua input 0–1, tiga tingkat (`rendah`, `sedang`, `tinggi`), 9 aturan, dan keluaran centroid
0–100. Kurvanya `MF_INPUT` dan `MF_OUTPUT` di `fuzzy/mesin.py`. Urutan impor di `fuzzy/__init__.py` menjadi urutan
`SEMUA_SISTEM`.

| File | Tahap | Sistem |
| --- | --- | --- |
| `fuzzy/kecurigaan.py` | [FUZZY 1], warga | `sentimen_sosial`, `perilaku_mencurigakan`, `jejak`, `kejanggalan`, `ucapan`, `bukti_keras`, `kecurigaan` |
| `fuzzy/ancaman.py` | [FUZZY 1], Hitman | `ancaman_langsung`, `ancaman_peran`, `ancaman`, `kambing` |
| `fuzzy/diskusi.py` | [FUZZY 2], chat | `tuduh`, `bela_orang`, `ajak_bicara`, `tanya_info`, `h_tuduh`, `klaim_palsu` |
| `fuzzy/tribunal.py` | [FUZZY 2], vote warga | `keyakinan_vote`, `kesiapan_vote` |
| `fuzzy/malam.py` | [FUZZY 2], aksi malam | `gag`, `intip` |

Total 21 sistem. Rangkaian sistem (mis. `sentimen_sosial` dan `perilaku_mencurigakan` → `ucapan` → `kecurigaan`)
ditulis di `fuzzy_controller.py` sebagai panggilan biasa.

### Mengubah logika bot

1. Ubah kode langsung di `backend/app/bot/`.
2. Jalankan skenario dan sidik sebelum dan sesudah mengubah (perintahnya di
   [Skenario bot dan sidik keputusan](#skenario-bot-dan-sidik-keputusan)). Perapian yang tidak mengubah logika harus
   memberi sidik yang sama. Perubahan logika yang disengaja mengubah sidik; sesudah skenario lulus dan perubahan
   diterima, simpan sidik baru dengan `--tulis`.
3. Perbarui notebook skripsi di `../training/prethesis/ai_2_dataset_baru/` (`npc_fuzzy.ipynb`, `npc_nlg.ipynb`)
   supaya laporan tetap menggambarkan game. Yang wajib sama: logika (input, aturan, fakta yang menimpa), hitungan
   (kurva, centroid, rumus), urutan, serta nama fungsi, variabel, konstanta, parameter, dan kunci data. Susunan dan
   letak kode notebook boleh berbeda dari backend. Tidak ada lagi ekspor notebook ke backend.
4. Perbarui [GAME_CONCEPT.md](GAME_CONCEPT.md) bila perilaku bot berubah, dan dokumen panel menu 08 yang terdampak
   (sumbernya di `communicationfolder/`).

### Menambah atau mengubah satu fuzzy

1. Buka file kelompoknya di `bot/fuzzy/`. File kelompok baru harus diimpor di `bot/fuzzy/__init__.py`; urutan impor
   di sana menjadi urutan `SEMUA_SISTEM`.
2. Tulis tabel aturan sebagai konstanta `ATURAN_<NAMA>` tepat di atas fungsinya: 3 baris × 3 kolom dari `"rendah"`,
   `"sedang"`, `"tinggi"`. Baris = tingkat input pertama, kolom = tingkat input kedua.
3. Tulis fungsinya dengan dekorator `@sistem_fuzzy(ATURAN_<NAMA>, "arti satu kalimat")`. Nama fungsi menjadi nama
   sistem, dan nama parameter menjadi nama input yang tampil di panel (mis. `tekanan=tinggi DAN dukungan=rendah`).
   Badannya cukup `return hitung("<nama>", input_pertama, input_kedua)`.

   Contoh dari `bot/fuzzy/malam.py`:

   ```python
   # Membungkam warga yang sedang menggalang suara dan memang berbahaya bagi Hitman.
   # Alur: 1 ancaman_sekarang dan ancaman jadi rendah/sedang/tinggi -> 2 cek tabel aturan -> 3 centroid -> 4 angka 0–100
   ATURAN_GAG = [                        # baris = ancaman_sekarang, kolom = ancaman (rendah, sedang, tinggi)
       ["rendah", "rendah", "rendah"],   # ancaman_sekarang rendah
       ["rendah", "sedang", "tinggi"],   # ancaman_sekarang sedang
       ["sedang", "tinggi", "tinggi"],   # ancaman_sekarang tinggi
   ]

   @sistem_fuzzy(ATURAN_GAG, "Membungkam penggalang suara yang memang berbahaya bagi Hitman.")
   def gag(ancaman_sekarang, ancaman):
       return hitung("gag", ancaman_sekarang, ancaman)
   ```

4. Panggil fungsinya di `bot/fuzzy_controller.py`. Bila keluarannya menjadi input fuzzy lain, bagi 100 dulu. Sistem
   yang dipilih per kandidat (chat, Gag, Peek) dipanggil lewat nama dengan `nilai_sistem(nama, input_kandidat)`.
5. Mengubah tabel atau kurva mengubah perilaku bot; mengubah arti hanya mengubah teks penjelasan panel. Keduanya
   mengubah sidik, jadi ikuti langkah [Mengubah logika bot](#mengubah-logika-bot).

## Gaya kode

### Formatter dan lint

- Python: empat spasi, Black dan Ruff dengan lebar 100 karakter (`pyproject.toml`). Ruff hanya memeriksa impor dan
  variabel yang tidak terpakai (`F401`, `F841`).
- TypeScript, JavaScript, HTML, JSON, dan YAML: Prettier, dua spasi, lebar 100. CSS/SCSS tidak ikut diformat.
- Dependency, hasil build, lockfile, environment lokal, upload pengguna, dan model biner tidak diformat.

```sh
npm install                                      # dari root; memasang dependency frontend juga
python -m pip install -r backend/requirements-dev.txt
npm run format          # Prettier + Black
npm run format:check
python -m ruff check backend
```

### Susunan fungsi dan komentar

- **Fungsi yang dipanggil ditulis di atas pemanggilnya**, jadi file terbaca dari atas ke bawah.
- **Di atas fungsi**: komentar 1–2 kalimat tentang gunanya. Bila fungsinya punya beberapa langkah, tambahkan baris
  `Alur:` bernomor. Fungsi satu langkah cukup kalimat penjelasan. Contoh dari `services/survey_service.py`:

  ```python
  # Simpan urutan baru dari panel (seret atau ▲▼). Daftar memuat semua pertanyaan, termasuk yang
  # nonaktif, tepat sekali; posisinya ditulis ulang 10, 20, 30, … dalam satu transaksi.
  # Alur: 1 tolak id dobel -> 2 baca semua id -> 3 tolak id asing/kurang -> 4 tulis posisi baru
  def reorder_questions(self, daftar_id: list[int]):
  ```

  Di dalam fungsi yang panjang, langkah alur ditandai komentar bernomor di atas barisnya (mis. `# 4 simpan`).
- **Docstring modul** menjelaskan guna file dan "Alurnya" bernomor, seperti di `bot/bot_controller.py`,
  `services/room_service.py`, dan `services/chat_service.py`.
- Komentar di dalam fungsi hanya untuk maksud yang tidak terlihat dari kode, misalnya penyimpanan sebelum broadcast,
  pencegahan respons basi, dan pemeriksaan informasi privat.
- **Dipakai sekali → tulis langsung di pemakainya.** Fungsi atau file sendiri hanya untuk kode yang dipakai di dua
  tempat atau lebih.
- Nama dan komentar baru memakai bahasa Indonesia tanpa singkatan. Nama lama berbahasa Inggris (mis. di engine dan
  model) tetap dipakai.
- Nama test menjelaskan skenario dan hasil yang diuji; helper test menyiapkan data tiruan tanpa memanggil layanan
  produksi.
- Sebelum menghapus simbol, periksa route, binding template, decorator, event, entry point CLI atau deployment, dan
  test. Referensi dinamis (mis. `patch("app...")` atau nama sistem fuzzy dalam teks) tidak selalu terlihat sebagai
  pemanggilan fungsi biasa.

## Akun, sesi, dan login

- **Daftar:** username 3–40 huruf, angka, atau underscore; nama lengkap 1–100 karakter; password 10–128 karakter
  dan konfirmasinya. Password disimpan sebagai PBKDF2-SHA256. Username duplikat ditolak. Sesudah daftar, pengguna
  langsung mendapat sesi. API masih menerima email dari frontend lama; konfirmasi email itu bukan verifikasi.
- **Login:** username, atau email untuk akun yang punya identitas email. Sesi pemain berlaku `AUTH_SESSION_HOURS`
  jam (bawaan 24). Hanya hash token yang disimpan. Sesi kedaluwarsa dihapus di transaksi tersendiri sesudah login,
  daftar, atau login Google berhasil, supaya dua login bersamaan tidak saling mengunci (deadlock). Gagal membersihkan
  tidak menggagalkan login.
- **Google:** Google Identity Services popup. Backend memverifikasi signature, audience, issuer, expiry, email
  verified, dan nonce sekali pakai (5 menit). Identitas memakai Google `sub`; email yang sama tidak otomatis menautkan
  atau mengambil alih akun lama. Akun Google baru memakai username acak dan nama dari token. Token Google tidak
  disimpan.
- **Batas percobaan:** 15 per menit per IP klien dan endpoint, di memori satu worker. Lokal, semua pemain terlihat
  sebagai IP gateway sehingga berbagi batas. Di Azure, uvicorn memakai `--proxy-headers` sehingga IP berasal dari
  Caddy.
- **Profil:** ikon pensil menyimpan nama dan username lewat `POST /api/auth/me`. Username hanya bisa diganti sesudah
  keluar ruangan. ID akun dan identitas Google tetap; nama pengirim di arsip chat tetap seperti saat pesan dikirim.
- **Avatar:** 6 skin (`arthur`, `dexter`, `eloise`, `jenny`, `kiera`, `sadie`), disimpan lewat `PUT /api/auth/skin`
  (bawaan `dexter`). Di pertandingan, skin yang sudah dipakai pemain yang masuk lebih dulu diganti skin yang masih
  kosong; lebih dari 6 peserta boleh kembar.
- **Manajemen user di panel** (`controllers/users.py`, `services/user_service.py`): tambah akun username/password
  tanpa membuat sesi; ubah nama atau username (ditolak bila masih di ruangan, dan mencabut sesi lama); reset password
  hanya untuk akun lokal dan mencabut semua sesinya; hapus akun dengan konfirmasi username dan hanya bila user sudah
  keluar ruangan. Yang dihapus hanya akun, identitas login, dan sesi; chat dan jejak checker tetap.
- `ADMIN_USERNAMES` dan `HISTORY_ADMIN_USERNAMES` di `.env` hanya daftar username yang dicadangkan (tidak boleh
  dipakai akun game). Nama bot juga dicadangkan.
- Belum ada reset password mandiri, verifikasi email, atau penautan akun.

## Tes dan simulasi

### Susunan `backend/tests/`

| Lokasi | Isi |
| --- | --- |
| `test_*.py` | Unit dan integration test, dijalankan `unittest discover` |
| `test_skenario_fuzzy.py` | 328 skenario berlabel dari notebook: patokan perilaku penalaran bot |
| `test_skenario_nlg.py` | Payload, pemeriksa aturan, templat per jenis, dan prompt penulis kalimat, tanpa LLM dan IndoBERT |
| `palsu/` | Tiruan untuk tes: `arsip_palsu.py` (arsip bot), `socket_palsu.py` (Socket.IO), `nlu_palsu.py` (pengganti IndoBERT yang cepat dan tidak butuh file model) |
| `jejak/` | `rekam_jejak.py` dan `sidik.json`: sidik keputusan bot pada seed tetap |
| `simulasi/` | `simulasi_keseimbangan.py` dan `uji_ab_vote.py`: pertandingan bot melawan bot |
| `panel_ui.test.mjs` | Tes UI panel dengan jsdom |
| `live_match_smoke.py`, `live_auth_smoke.py`, `mysql_smoke.py` | Alat manual yang menyentuh server atau database sungguhan; tidak ikut pola `test_*.py` |

Tes otomatis mencakup 4–10 pemain dan komposisinya, Syndicate (Hostage bersama, Gag bersama, larangan menarget
rekan, privasi rekan, pengumuman Hitman tersisa), permainan tanpa pemenang melewati ronde 25, Guard, Peek, Gag,
Hostage, waktu tambahan Tribunal, rekan Spy, chat tim beserta privasinya, kemenangan, privasi snapshot, voting,
reconnect, scheduler bot, penulis LLM dan cadangan templat dengan model tiruan, layar persiapan, survei, dan
pertandingan multi-bot penuh melawan engine asli. Tes tidak membuktikan kualitas taktik atau latensi provider
produksi, dan bukan bukti koneksi AI eksternal sedang aktif.

### Menjalankan tes

Python di host biasanya tidak punya dependency backend, jadi cara termudah lewat container yang sedang jalan (dari
root repo):

```sh
docker compose exec -T ai-engine python -m unittest discover -s tests -p "test_*.py" -v
docker compose exec -T frontend npm test -- --watch=false
docker compose exec -T frontend npm run build
node --test backend/tests/panel_ui.test.mjs      # dari root; butuh frontend/node_modules
```

Dengan virtual environment sendiri (`pip install -r backend/requirements-dev.txt`), jalankan suite dari folder
`backend`: `python -m unittest discover -s tests -p "test_*.py"`. Tes yang butuh MySQL akan gagal tersambung bila
tidak ada database.

### Skenario bot dan sidik keputusan

Jalankan dari folder `backend`, sebelum dan sesudah mengubah atau merapikan kode bot:

```sh
python -m unittest tests.test_skenario_fuzzy tests.test_skenario_nlg
python tests/jejak/rekam_jejak.py --cek
```

`rekam_jejak.py` merekam tiga bagian, masing-masing dengan sidik sendiri: (a) semua hasil `putuskan` di room 4–10
bot, (b) kalimat templat, prompt LLM, dan chat tim, (c) satu langkah bot penuh lewat `BrainRuntime.langkah` dengan NLU
tiruan. Pilihan: tanpa opsi mencetak sidik, `--cek` membandingkan dengan `sidik.json` (keluar 1 bila berbeda),
`--tulis` menyimpan sidik baru, `--simpan FOLDER` menulis jejak lengkap untuk mencari selisih.

### Tes manual dengan server atau database

```sh
# Pertandingan nyata 6 akun QC sementara sampai warga menang; hanya akun milik tes yang dibersihkan.
docker compose exec -T ai-engine python -m tests.live_match_smoke

# Hanya untuk database MySQL sementara yang sudah diberi migrasi (tes ini menulis data).
STRUCTURE_TEST_DB=1 python -m unittest discover -s tests -p mysql_smoke.py -v
```

Jangan menjalankan tes yang menulis data ke database pengguna atau ke deployment publik.

### Simulasi keseimbangan dan uji A/B

Dua skrip di `tests/simulasi/` memainkan pertandingan dengan semua kursi bot (otak Fuzzy, label NLU sempurna dari
rencana pengirim) melawan engine asli. Jalankan dari folder `backend`; argumen pertama adalah folder backend (`.`).

```sh
# <jumlah game per sel> <langkah keputusan per fase> <ukuran:hitman/spy/stalker> ...
python tests/simulasi/simulasi_keseimbangan.py . 200 6 "7:2/2/1" "8:2/2/1"

# Paksa vote saat warga kritis aktif lawan mati: <jumlah game> <langkah per fase> [jumlah pemain, bawaan 6]
python tests/simulasi/uji_ab_vote.py . 200 6 7
```

Keluarannya win rate warga ± CI95, rata-rata ronde, pertandingan tanpa pemenang, dan aksi ilegal (uji A/B juga
akurasi vote warga). Seed tetap, jadi hasil bisa diulang. Kedua skrip memakai paling banyak separuh core CPU;
`SIM_PROSES` boleh menurunkannya lagi. Hasil terakhir dicatat di
[GAME_CONCEPT.md](GAME_CONCEPT.md#keseimbangan-komposisi).

## Batas implementasi

- Lobby, engine, role, aksi, vote, timer, dan ingatan bot ada di memori **satu proses** backend. Reload atau
  reconnect browser memulihkan snapshot dan 100 pesan terbaru selama proses itu hidup. Restart atau recreate backend
  menghapus pertandingan aktif; arsip chat dan jejak di MySQL tetap ada, tetapi tidak memulihkan pertandingan.
- Jangan menjalankan lebih dari satu worker backend sebelum ada state bersama. Ruangan, nonce Google, dan batas
  percobaan login hanya ada di satu proses.
- Belum ada penggantian otomatis pemain yang offline.

# Silent Terror

Game deduksi sosial berbasis percakapan: Hitman menyusup di antara warga, sementara pemain mencari identitasnya melalui alibi dan observasi chat. **Zero economy** — tanpa budget, pembelian item, atau tebusan.

Repository ini bernama `GamesSilentTerror`. Database (`shadow_heist`), container (`shadow_*`), dan sebagian kode masih memakai nama proyek lama, Shadow Heist.

## Penelitian

Game ini adalah bagian dari skripsi. Naskah penelitiannya ada di sini:
[Naskah skripsi Silent Terror (OneDrive BINUS)](https://binusianorg-my.sharepoint.com/personal/andy_saputra001_binus_ac_id/_layouts/15/guestaccess.aspx?share=IQDKQcDT5f1NSIhXTwwSsCgVAUckMBzh9nTX9KbN52iZ1sE&e=RmW4Ck).

## Status proyek

Sudah dapat dimainkan dari awal sampai akhir:

- Login username/email + password, daftar akun, login Google, dan pilihan avatar (6 skin karakter, tersimpan per akun).
- Main page, buat/gabung ruangan, 4–10 peserta, bot opsional untuk mengisi kursi kosong. Hanya pembuat ruangan yang mengatur bot dan memulai game.
- Role acak dari server, layar persiapan, timer Day → Tribunal → Night (ronde 1 tanpa Tribunal) tanpa batas ronde (berakhir hanya saat salah satu kubu menang), skill/cooldown, voting, eksekusi, dan kondisi kemenangan.
- Survei singkat setelah pertandingan; jawabannya dipakai untuk menilai bot per metode penalaran.
- Panel administrator terpadu di `/panel`: Konfigurasi AI, Checker, Riwayat chat, Manajemen user, Otak NPC, Survei, Simulasi, dan Dokumen (ERD dan Proses AI).

Role: **Hitman** (Hostage/Gag Order), **Spy** (Guard), **Stalker** (Peek), dan **Civilian** (observasi). Korban Hostage tetap hidup tetapi kehilangan semua aksi permanen (chat, voting, dan skill malam); identitas target tidak diumumkan.

Engine backend menjadi sumber kebenaran, bukan browser atau AI. Engine memvalidasi setiap aksi/vote/chat bot; fallback aturan mengisi aksi yang kosong jika otak bot gagal. Baca [aturan, alur kode, dan batas implementasi](GAME_CONCEPT.md) serta [panduan membaca kode](CODE_GUIDE.md).

## Cara kerja AI

Semua AI ada di **otak bot** (NPC yang ikut bermain). Chat manusia hanya diotorisasi, disimpan, dan disiarkan; bot membacanya sendiri lewat IndoBERT.

| Komponen | Dipakai untuk | Kapan berjalan |
| --- | --- | --- |
| **IndoBERT** (2 model: intent + target) | NLU otak bot: membaca chat publik menjadi intent (menuduh, membela, dll.) dan siapa yang dituju | Setiap kali bot mengambil langkah, untuk chat terbaru di ruangan (satu model dipakai bersama semua bot, hasilnya di-cache per pesan) |
| **IndoBERT** (validasi ulang) | Memastikan kalimat yang ditulis bot memang terbaca sesuai rencana (misalnya benar-benar menuduh X) | Setiap kali bot akan mengirim chat, sebelum kalimat dikirim (`NPC_VALIDATE_NLG=true`) |
| **Fuzzy / Utility AI / Behavior Tree** | Penalaran bot: memilih tuduhan, pembelaan, vote, dan skill malam | Setiap langkah bot. `NPC_METHOD=campuran` membagi metode antar bot dalam satu pertandingan; metode tiap bot dicatat di tabel `match_bots` |
| **NLG** (rantai penulis LLM atau templat) | Mengubah rencana bot menjadi kalimat | Saat bot memutuskan bicara. Jalur LLM yang gagal dilewati; tanpa jalur yang hidup, bot memakai templat |
| **LLM mode lama** (`NPC_METHOD=llm`) | Bot yang sepenuhnya digerakkan LLM, sebagai pembanding | Hanya bila mode ini dipilih |

Tanpa model IndoBERT, bot tetap bermain dengan NLU cadangan (SVM + nama yang disebut) yang kualitasnya lebih rendah; sumber NLU tercatat di trace dan terlihat di panel menu **Otak NPC**.

## Persiapan

- Git dan Docker dengan perintah `docker compose`. Jika memakai Docker Desktop, jalankan aplikasinya terlebih dahulu dan gunakan Linux containers.
- Koneksi internet untuk mengunduh image, dependency, dan model AI.
- Port lokal `4200`, `8000`, dan `3307` tersedia. Mode Ollama juga menggunakan `11435`.
- Untuk mode Ollama: RAM dan ruang disk yang mencukupi. Versi CPU tidak memerlukan GPU; versi NVIDIA memerlukan GPU dan driver/runtime yang dapat diakses Docker.

Tidak perlu memasang Python, Node.js, atau MySQL di host jika seluruh aplikasi dijalankan lewat Docker.

### 1. Clone repository

```sh
git clone https://github.com/Andysaputra1/GamesSilentTerror.git
cd GamesSilentTerror
```

Semua perintah Compose berikut dijalankan dari folder ini, tempat `docker-compose.yml` berada.

### 2. Siapkan environment

Windows PowerShell:

```powershell
Copy-Item .env.example .env
```

Linux/macOS:

```sh
cp .env.example .env
```

Lakukan penyalinan hanya saat setup awal; jangan menimpa `.env` yang sudah dikonfigurasi. File ini menyimpan konfigurasi lokal dan secret, sehingga tidak boleh di-commit.

### 3. Siapkan model SVM — untuk analisis pesan manusia

Minta artifact terlatih `intent_classifier.pkl` kepada pengelola proyek, lalu letakkan di:

```text
backend/artifacts/svm/intent_classifier.pkl
```

File `.pkl` sengaja diabaikan Git dan **tidak tersedia hanya dengan clone repository**. Gunakan hanya artifact tepercaya karena pemuatan pickle dapat menjalankan kode.

Tanpa model SVM, pesan pemain masih bisa diteruskan dan bot tetap bermain, tetapi analisis intent pesan manusia tidak tersedia, dan NLU cadangan bot (dipakai bila IndoBERT tidak ada) hanya menghasilkan intent netral. Lihat [panduan artifact SVM](backend/artifacts/svm/README.md).

### 4. Siapkan otak NPC (IndoBERT + fuzzy/utility/behavior tree + NLG)

Bot memakai logika notebook skripsi (`training/prethesis/ai_2_dataset_baru`). Kode logikanya sudah ada di `backend/app/services/npc_brain/generated/` (hasil ekspor, jangan diedit manual). Yang perlu disalin hanyalah dua folder model IndoBERT (±440 MB masing-masing, diabaikan Git):

```text
backend/artifacts/indobert/intent/   ← models/notebook_standalone/intent_classifier_transformer
backend/artifacts/indobert/target/   ← models/target_classifier/target_classifier_transformer
```

Folder target harus memuat `pair_builder.json` dan `ambang_target.json` hasil `nlu_target.ipynb`. Pada mesin pengembang yang menyimpan repo skripsi di `a_skripsi/training/prethesis`, backend juga menemukan model di sana secara otomatis.

Pengaturan di `.env` (lihat `.env.example`): `NPC_METHOD` (`campuran`, `fuzzy`, `utility`, `bt`, atau `llm` untuk mode lama), `NPC_WRITER` (`otomatis` atau `templat`), `NPC_WRITER_ORDER` (prioritas rantai penulis: `openrouter`, `tautan`), dan `NPC_OPENROUTER_MODEL`. Hanya dua LLM yang dipakai: OpenRouter dan LLM sendiri lewat link (Ollama di Docker yang dibuka lewat tunnel, lihat `ai-docker/`). Key OpenRouter dan link diambil dari panel **Konfigurasi AI**. Metode, urutan rantai, model OpenRouter, dan model link bisa diubah dari panel **Otak NPC** (tombol **Tes koneksi semua prioritas** memeriksa semua jalur).

Setelah mengubah logika bot di notebook, jalankan ulang notebook sampai skenario/pengujiannya lulus, lalu ekspor ulang:

```sh
cd backend
python scripts/ekspor_otak_npc.py --notebook-dir ../../training/prethesis/ai_2_dataset_baru
```

Tes `test_npc_brain` gagal bila hasil ekspor sudah tidak sama dengan notebook.

## Menjalankan aplikasi

Pilih **salah satu** mode berikut.

Ada dua file Compose **mandiri**, bukan base + override:

| File | Penggunaan |
| --- | --- |
| `docker-compose.yml` | CPU, tanpa syarat GPU NVIDIA; untuk MacBook atau mesin tanpa NVIDIA |
| `docker-compose.gpu.yml` | Akselerasi GPU NVIDIA pada mesin Docker yang mendukungnya |

Service, port, dan named volume pada kedua file sama. **Jangan menjalankan
keduanya sebagai dua stack bersamaan.** Pilih satu file dan gunakan pilihan
yang sama pada perintah berikutnya. File GPU dipakai dengan satu opsi
`-f docker-compose.gpu.yml`, tidak perlu menggabungkan kedua file.

### A. AI lokal melalui Ollama / Docker

Isi pengaturan berikut di `.env`:

```dotenv
AI_PROVIDER=docker
OLLAMA_MODEL=8
OLLAMA_MODELS_TO_PULL=qwen3:8b
```

MacBook / CPU (Ollama tetap di Docker, tidak perlu dipasang di macOS):

```sh
docker compose up -d --build
docker compose logs -f ollama-models
```

Atau mesin NVIDIA, termasuk konfigurasi pengembang utama:

```sh
docker compose -f docker-compose.gpu.yml up -d --build
docker compose -f docker-compose.gpu.yml logs -f ollama-models
```

CPU dapat sangat lambat, khususnya 14B. Mulai dari 8B dan pastikan alokasi
memori Docker cukup. Jika request kehabisan waktu, naikkan
`OLLAMA_TIMEOUT_SECONDS` (misalnya `600`) di `.env`, lalu recreate backend.
Menambah timeout tidak mengatasi RAM yang kurang; gunakan mode API jika mesin
tidak sanggup. Model yang tidak muat di memori bisa gagal, bukan hanya lambat.

Startup pertama mengunduh image dan model, sehingga dapat memakan waktu. Tunggu unduhan selesai sebelum mencoba chat. `Ctrl+C` keluar dari tampilan log tanpa mematikan container. Service `ollama-models` yang selesai dengan exit code `0` adalah normal: tugasnya hanya menyiapkan model.

Periksa model yang tersedia:

```sh
docker compose exec ollama ollama list
```

`OLLAMA_MODEL=8` memilih `qwen3:8b`; `OLLAMA_MODEL=14` memilih `qwen3:14b`. Untuk mengunduh hanya model 8B, isi `OLLAMA_MODELS_TO_PULL=qwen3:8b`. Pastikan model yang dipilih sudah diunduh. Model 14B memerlukan sumber daya lebih besar; kecepatan bergantung pada mesin.

### B. AI melalui OpenRouter, tanpa menjalankan Ollama

Ubah `.env` (key juga bisa diisi dari panel **Konfigurasi AI**):

```dotenv
AI_PROVIDER=api
OPENROUTER_API_KEY=isi_key_pribadi_di_sini
```

Jalankan hanya service aplikasi berikut, beserta dependency-nya:

```sh
docker compose up -d --build mysql phpmyadmin ai-engine gateway frontend
```

Jangan memakai `docker compose up` tanpa daftar service untuk mode ini jika ingin menghindari startup Ollama: kedua file tetap mendefinisikan service Ollama dan pengunduh model. Jika sebelumnya sudah menjalankan Ollama, service itu tidak otomatis berhenti saat provider diganti; hentikan dengan `docker compose stop ollama-models ollama` bila tidak diperlukan. Jika memakai file GPU, tambahkan `-f docker-compose.gpu.yml` pada perintah Compose.

API key hanya dibaca backend. Penggunaan API dapat menimbulkan biaya pada akun penyedia. Tidak ada perpindahan otomatis dari Ollama ke API jika model lokal gagal.

### Buka dan coba

| Tujuan | Alamat / akses |
| --- | --- |
| Aplikasi | http://localhost:4200 |
| Panel administrator | http://localhost:8000/panel |
| Status backend | http://localhost:8000/app-status |
| Dokumentasi API | http://localhost:8000/docs |
| phpMyAdmin | http://localhost:8000/phpmyadmin/ |
| MySQL dari host / DB client | `localhost:3307`, database `shadow_heist` |
| Ollama dari host (mode lokal) | http://localhost:11435 |

Untuk login phpMyAdmin, gunakan `MYSQL_USER` dan `MYSQL_PASSWORD` dari `.env`, bukan akun game. Backend dan phpMyAdmin berbagi port `8000` melalui gateway Nginx; port `3307` hanya untuk koneksi MySQL, bukan halaman web.

### Testing lewat LAN

Frontend development mengizinkan `localhost`, `127.0.0.1`, dan IP LAN pengembang `192.168.40.176`. Untuk IP lain, sesuaikan kedua daftar `allowedHosts` (build security dan serve) di `frontend/angular.json`, lalu tambahkan origin lengkap ke `.env`, misalnya `CORS_ORIGINS=http://localhost:4200,http://127.0.0.1:4200,http://192.168.40.176:4200`. Konfigurasi ini berlaku untuk HTTP API dan Socket.IO. Jangan menggunakan wildcard untuk membuka semua host/origin.

Jalankan `docker compose -f docker-compose.gpu.yml up -d --no-deps ai-engine frontend`, lalu `docker compose -f docker-compose.gpu.yml restart frontend gateway` setelah mengubah konfigurasi (pakai `docker-compose.yml` untuk CPU). Restart backend menghapus pertandingan dalam memori, bukan database/model. Teman satu jaringan membuka `http://192.168.40.176:4200`; jangan memakai IP adapter WSL. Jika masih timeout dari perangkat lain, periksa firewall dan isolasi klien Wi-Fi. Jangan membuka MySQL/admin ke internet atau mematikan firewall keseluruhan.

## Mencoba permainan

Login aplikasi development: **`user1` / `user132`**. Akun ini disiapkan oleh migration saat inisialisasi database baru.

Akun demo tambahan: **`janice` / `user132`** dan **`kimberly` / `user132`** melalui migration `V3__add_demo_players.sql`. Database lama perlu menerapkan V3; startup backend tidak otomatis menjalankan migration. Migration tidak menimpa password akun yang sudah ada. Ketiga akun/password bersama ini hanya untuk development, bukan deployment publik.

Alur mencoba: **Login → Main page → Enter Tribunal → Buat Ruangan / Gabung → + Bot → Mulai Permainan**. Bot mengisi semua kursi kosong sampai kapasitas pilihan host sehingga bisa dicoba sendiri. Tanpa bot, siapkan minimal 4 akun berbeda. Pemilik ruangan menekan Mulai; anggota lain menekan Masuk Permainan ketika game sudah dimulai.

Di game, buka role privatmu. Saat Day, diskusikan alibi; Hitman dapat memilih target Gag. Mulai ronde 2, Tribunal datang setelah Day: pilih kartu tersangka lalu kunci vote. Saat Night, pilih kartu target lalu kunci Hostage/Guard/Peek jika tersedia. Pemain yang tidak bisa bertindak tetap dapat menonton. Setelah selesai, isi survei, lalu kembali ke lobby → Keluar ruangan → Buat ruangan baru (satu ruangan hanya untuk satu pertandingan).

Timer mengikuti jumlah peserta awal. Contoh enam pemain: standar 120/30/75 detik; mode cepat 20/15/15 detik. Empat pemain: standar 80/20/60 detik. Durasi tetap selama pertandingan; rincian ada di GAME_CONCEPT.md. Keputusan atau balasan bot yang baru selesai setelah fase berubah **dibuang, tidak ditampilkan**, agar tidak menerobos malam atau efek bungkam; gunakan durasi standar untuk mencoba chat AI.

Saat Day, tombol **Setuju skip diskusi** mempercepat ke fase berikutnya (Night di ronde 1, Tribunal di ronde berikutnya) setelah seluruh manusia yang masih hidup setuju. Bot tidak dihitung. Pemain dibungkam/disandera tetap boleh menyetujui karena ini bukan chat atau vote Tribunal; status mereka tetap tidak dipublikasikan. Persetujuan tidak bisa ditarik pada ronde itu. Pemain offline belum dianggap setuju; timer normal tetap berjalan.

Selama pertandingan aktif, membuka halaman aplikasi lain/tab baru atau login ulang akan mengembalikan akun ke `/game` berdasarkan data backend, bukan hanya storage tab. Akun tidak bisa membuat/gabung pertandingan lain sebelum match selesai. Ini berlaku dalam aplikasi ini, bukan memaksa browser meninggalkan situs eksternal.

### Akun teman untuk multiplayer

Akun yang sama di beberapa tab tetap satu pemain. Teman bisa mendaftar sendiri lewat halaman login, ditambahkan dari panel **Manajemen user**, atau dibuat lewat CLI lokal (password diminta tersembunyi dan disimpan sebagai hash; akun lama tidak ditimpa):

```sh
docker compose exec ai-engine python -m app.services.create_user teman1 --name "Teman Satu"
```

Gunakan `-f docker-compose.gpu.yml` jika memakai stack NVIDIA. Setiap teman login dengan akun sendiri, lalu gabung memakai kode room yang sama. Pengujian lintas perangkat/LAN memerlukan konfigurasi CORS/host yang sesuai.

## Panel administrator

Panel terpadu ada di http://localhost:8000/panel. Alamat lama `/admin` dan `/history` otomatis diarahkan ke sana. Panel memakai akun administrator tersendiri, **bukan** akun game.

Siapkan password panel sekali dari root repository (membutuhkan Python dengan dependency backend, atau jalankan di container lalu salin hasilnya ke `.env`):

```sh
python backend/scripts/setup_panel.py .env
```

Script ini menulis `PANEL_USERNAME=administrator` dan `PANEL_PASSWORD_HASH`, serta membuat `PANEL_ENCRYPTION_KEY` bila belum ada. Pertahankan kunci itu: API key yang disimpan dari panel dienkripsi dengannya. Restart backend setelah menjalankannya. Sesi panel berlaku 8 jam dan otomatis tidak berlaku lagi bila password panel diganti.

| Menu | Isi |
| --- | --- |
| 01 Konfigurasi AI | Provider AI (`api`/`docker`), model, key OpenRouter, link LLM sendiri; tombol cek/tes koneksi |
| 02 Checker | Jejak setiap chat manusia (otorisasi → simpan → siar) dan setiap langkah bot (NLU, penalaran, penulis kalimat) per ruangan |
| 03 Riwayat chat | Arsip chat dari MySQL dengan filter dan ekspor CSV, termasuk intent dan target hasil IndoBERT tiap chat |
| 04 Manajemen user | Tambah user, reset password akun lokal, hapus akun tanpa menghapus riwayat chat |
| 05 Otak NPC | Metode penalaran, rantai penulis kalimat, status NLU IndoBERT |
| 06 Survei | Mengatur pertanyaan survei, ringkasan jawaban per metode bot, dan ekspor CSV |
| 07 Simulasi | Pertandingan tiruan dengan bot (metode dipilih per bot): chat seperti room asli, flowchart proses AI yang menyala sesuai tahap, dan kode asli tiap tahap |
| 08 Dokumen | ERD database dan penjelasan Proses AI (`backend/public/dokumen`: salinan hasil pembuat dokumen di `communicationfolder/`, folder yang tidak ikut repo) |

CSV (survei dan riwayat chat) memakai UTF-8 dengan BOM dan menyimpan jawaban persis seperti diketik pemain. Saat membuka di spreadsheet, impor kolom teks sebagai teks agar jawaban yang diawali `=`, `+`, `-`, atau `@` tidak dievaluasi sebagai formula.

`ADMIN_USERNAMES` dan `HISTORY_ADMIN_USERNAMES` di `.env` kini hanya menjadi daftar username yang dicadangkan (tidak boleh dipakai sebagai username akun game).

## Akun dan login Google

Halaman login menggunakan `auth.html` + `auth.scss` dari desain Kimberly.

- Register memakai username 3–40 huruf/angka/underscore, email, password 10–128 karakter dan kedua konfirmasi. Password disimpan sebagai PBKDF2; username/email duplikat ditolak. Setelah register berhasil pengguna mendapat sesi dan masuk main page.
- Login biasa menerima username atau email. Konfirmasi email di form **bukan verifikasi lewat email**. Reset password mandiri dan penautan akun belum tersedia; reset dilakukan administrator dari panel.
- Avatar dipilih dari 6 skin (`arthur`, `dexter`, `eloise`, `jenny`, `kiera`, `sadie`) lewat ikon gantungan di main page; pilihan disimpan di akun (`PUT /api/auth/skin`, bawaan `dexter`). Di pertandingan, skin yang sudah dipakai pemain yang masuk lebih dulu diganti skin yang masih kosong; lebih dari 6 peserta boleh kembar.
- Google memakai Identity Services popup + callback JavaScript. Isi `GOOGLE_CLIENT_ID=...apps.googleusercontent.com` di `.env`, lalu rebuild/recreate backend. Client Secret tidak digunakan, dan jangan menaruh JSON kredensial mentah di `.env`.
- Google Console: OAuth client jenis **Web application**, Authorized JavaScript origins `http://localhost:4200`; redirect URI tidak diperlukan untuk alur ini. Domain deployment harus HTTPS dan didaftarkan sebagai origin; IP LAN HTTP tidak didukung login Google. Login password tetap bisa digunakan lewat LAN.
- Backend memverifikasi signature/audience/issuer/expiry token Google, email verified, dan nonce sekali pakai (5 menit). Identitas memakai Google `sub`; email yang sama tidak otomatis menautkan/mengambil alih akun lama. Token Google tidak disimpan; sesi aplikasi tetap dapat dicabut lewat logout.
- Pembatasan percobaan 15/menit per alamat peer/endpoint dan nonce disimpan di memori untuk satu worker. Di belakang gateway beberapa pengguna bisa berbagi batas peer; sebelum production gunakan rate limiter bersama/proxy tepercaya, HTTPS, verifikasi email, reset password, dan audit lanjutan.

Panduan resmi: [Google Identity Services setup](https://developers.google.com/identity/gsi/web/guides/get-google-api-clientid) dan [verifikasi token backend](https://developers.google.com/identity/gsi/web/guides/verify-google-id-token).

## Database

MySQL menyimpan 14 tabel: akun & sesi login, arsip ruangan/pemain/chat/analisis, konfigurasi & sesi panel, jejak checker, serta survei dan metode bot per pertandingan. Pertandingan yang sedang berjalan (role, vote, timer) **tidak** disimpan di database, tetapi di memori backend.

SQL di `backend/migrations/` (V1–V8) dijalankan otomatis hanya saat volume database pertama kali dibuat. Untuk database lama, terapkan file yang belum dijalankan secara manual sesuai urutan versinya, tanpa menghapus volume; salinan untuk Azure ada di `backend/deployment/mysql/`. Lihat [catatan migration](backend/migrations/README.md).

## Mengelola container dan data

```sh
# Lihat status, termasuk initializer yang sudah selesai
docker compose ps -a

# Lihat log backend; Ctrl+C untuk keluar
docker compose logs -f ai-engine

# Berhenti tanpa menghapus volume database/model
docker compose down
```

Untuk menjalankan kembali, ulangi perintah `up` sesuai mode A atau B. Opsi `--build` berguna saat image/dependency berubah.

Semua contoh `docker compose ...` tanpa `-f` menggunakan versi CPU. Untuk
mempertahankan NVIDIA, gunakan `docker compose -f docker-compose.gpu.yml ...`,
terutama pada `up` dan recreate. Jangan tanpa sengaja memakai file CPU saat
memperbarui container Ollama yang sebelumnya memakai GPU.

Jika ingin berpindah versi, hentikan stack memakai file lama (`down` tanpa `-v`),
lalu jalankan `up` dengan file baru dari folder proyek yang sama. Named volume
tetap dipakai ulang sehingga data MySQL/model tidak dihapus. Ruangan/checker
di memori backend tetap hilang saat backend dihentikan.

Setelah mengubah `.env`, recreate backend agar environment baru diterapkan:

```sh
docker compose up -d --force-recreate ai-engine
docker compose restart gateway
```

Jika mengubah daftar model lokal yang harus diunduh, jalankan pula `docker compose up -d ollama ollama-models` dan periksa log unduhannya. Perubahan kode Python yang di-bind-mount memerlukan `docker compose restart ai-engine`; frontend memantau perubahan source saat development.

- Database disimpan di named volume `shadow_heist_mysql_data`.
- Model Ollama disimpan di named volume `games_ollama_data`.
- `down` biasa mempertahankan kedua volume. **Jangan gunakan `docker compose down -v` jika data/model masih diperlukan: opsi itu menghapus named volume beserta isinya.** Volume persisten bukan pengganti backup.
- Lobby, engine pertandingan, role/aksi/vote, dan konteks AI berada di memori satu proses backend. Reload/reconnect browser memulihkan snapshot dan 100 pesan terbaru selama proses yang sama hidup. Restart/recreate backend menghilangkan pertandingan aktif. Catatan chat/analisis di MySQL tetap tersimpan, tetapi belum memulihkan pertandingan. Jangan menjalankan beberapa worker backend sebelum menambahkan shared state/persistence engine.
- Menambah file migration atau mengganti password di `.env` tidak otomatis memperbarui database yang sudah berisi data.

## Jika belum berjalan

| Gejala | Pemeriksaan |
| --- | --- |
| Docker tidak dapat dihubungi | Pastikan Docker Engine/Desktop aktif; jalankan `docker info`. |
| Error perangkat/driver NVIDIA | Pastikan file GPU hanya dipakai pada mesin NVIDIA yang didukung; di Mac gunakan file CPU atau mode API. |
| Port sudah digunakan | Hentikan service lokal lain yang memakai port tersebut. Perubahan port juga perlu diselaraskan dengan URL frontend, CORS, dan proxy. |
| Login gagal / backend belum siap | Periksa `docker compose ps -a`, log `ai-engine` dan `mysql`, lalu status backend. Database lama mungkin belum memiliki migration akun. |
| Bot diam atau kualitasnya turun | Buka panel **Otak NPC**: pastikan NLU tertulis IndoBERT (bukan cadangan) dan minimal satu jalur penulis hidup (atau `NPC_WRITER=templat`). Periksa `database_ready=true` di `/app-status`. Untuk mode `llm`, periksa juga `ollama_ready`/key API. |
| Panel tidak bisa login | Pastikan `PANEL_PASSWORD_HASH` sudah dibuat dengan `setup_panel.py` dan backend sudah di-restart. |
| Ruangan tidak ditemukan | Buat ruangan baru setelah backend restart, atau periksa kembali kode undangan. |

## Struktur dan pengujian

```text
frontend/             Angular: login, main page, lobby, game/chat, survei
backend/              Python FastAPI + Socket.IO
  app/                Semua kode aplikasi Python
    __init__.py       Paket aplikasi
    main.py           Entry point ASGI (app.main:asgi_app)
    config/           Konfigurasi aplikasi, AI, MySQL
    controller/       Endpoint API dan middleware
    services/         Logika autentikasi/game, koneksi MySQL, klien AI, dan CLI akun
      npc_brain/      Runtime otak NPC; generated/ = ekspor notebook skripsi
    models/           Query SQL terparameterisasi
    realtime/         Event Socket.IO
    schemas/          Validasi request/response API
  public/panel/       Halaman panel administrator
  artifacts/svm/      Model intent SVM privat, disediakan terpisah
  artifacts/indobert/ Model IndoBERT intent + target untuk otak NPC (disalin manual)
  migrations/         Skema SQL V1–V8 dan akun development
  deployment/         Konfigurasi produksi Azure (Caddy, SQL salinan)
  scripts/            setup_panel.py, ekspor_otak_npc.py, setup_azure.py
proxy/                Gateway Nginx
ai-docker/            LLM penulis kalimat bot (Qwen3 4B/14B) di laptop + tunnel untuk VM; jalankan.bat
docker-compose.yml    Service development dan volume
```

Alur chat manusia: **pesan → otorisasi → validasi ulang fase/hak chat → penyimpanan MySQL → broadcast**. Secara terpisah, timer menjalankan bot: **snapshot privat → IndoBERT (baca chat) → fuzzy/utility/behavior tree → NLG → validasi IndoBERT → aksi/vote/chat** (mode `llm` lama tetap tersedia). Analisis lama SVM → agresivitas → fuzzy 2 input dan balasan NOX sudah dihapus; model SVM hanya dipakai sebagai NLU cadangan bila IndoBERT tidak ada.

Dengan container aplikasi sudah berjalan:

```sh
docker compose exec -T ai-engine python -m unittest discover -s tests -v
docker compose exec -T frontend npm test -- --watch=false
docker compose exec -T frontend npm run build

# Opsional: tes 4 akun sementara pada server/MySQL lokal sampai warga menang.
# Hanya akun QC yang dibuat tes akan dibersihkan; bukan akun pengguna.
docker compose exec -T ai-engine python -m tests.live_match_smoke
```

Tes otomatis bukan bukti koneksi AI eksternal sedang aktif; coba chat melalui UI untuk menguji provider sebenarnya. Tes database khusus hanya boleh diarahkan ke database percobaan.

Dokumentasi lanjutan: [panduan membaca kode](CODE_GUIDE.md), [konsep game](GAME_CONCEPT.md), [backend](backend/README.md), [Ollama](OLLAMA.md), [LLM laptop untuk VM](ai-docker/README.md), [pengaturan styling](frontend/STYLING.md), [deployment frontend](frontend/DEPLOYMENT.md), dan [deployment backend](backend/deployment/README.md).

## Mengembangkan frontend melalui Docker

Panduan menjalankan frontend dipusatkan di README ini; tidak perlu menjalankan
`ng serve` lagi di host. Service `frontend` sudah menjalankan development server
Angular di http://localhost:4200. Folder `frontend/src` dan `frontend/public`
dipasang ke container, sehingga perubahan source lokal dipantau otomatis.

Untuk membuat komponen baru, jalankan dari root repository saat container aktif:

```sh
docker compose exec frontend npx ng generate component features/nama-komponen
```

File komponen dibuat di source yang terhubung ke workspace. Gunakan perintah
test/build pada bagian sebelumnya untuk memeriksa perubahan. Hasil build masuk
ke `/app/dist/frontend` di container; folder hasil build tidak dipasang ke host
oleh Compose saat ini. Jangan mengedit `dist` sebagai source.

Jika dependency di `frontend/package.json` berubah, bangun ulang service:

```sh
docker compose up -d --build frontend
```

Untuk perubahan warna, padding, layout, dan responsive, gunakan
[panduan styling](frontend/STYLING.md). Belum ada target `ng e2e` yang
dikonfigurasi dalam `angular.json`; jangan menganggapnya sebagai tes siap pakai.

## Catatan keamanan

Endpoint checker publik lama `GET /api/rooms/{code}/checker` sudah ditutup (HTTP 410).
Trace/prompt hanya tersedia lewat `/panel` dengan sesi administrator. Data ini dapat
berisi role dan intel privat NPC, sehingga administrator harus dipisahkan dari peserta
eksperimen. Trace menunjukkan input/output aplikasi, bukan chain-of-thought internal model.
Jejak otak bot memuat `penjelasan` (role bot, kecurigaan, penalaran metode) dan hanya
dikembalikan oleh endpoint panel.

Compose ini untuk development lokal, bukan deployment publik siap pakai. Ganti kredensial default dan akun demo sebelum deployment; batasi akses port database/phpMyAdmin, serta siapkan HTTPS dan pengamanan deployment. Jangan commit `.env`, API key, file upload pengguna, atau artifact privat. Folder dokumen pribadi `communicationfolder/` juga diabaikan Git.

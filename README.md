# Silent Terror

Silent Terror adalah game deduksi sosial berbasis web. Hitman menyusup di antara warga, dan pemain mencari
Hitman lewat percakapan, alibi, dan voting. **Zero economy**: tanpa uang, pembelian item, atau tebusan. Bot NPC
boleh mengisi kursi kosong. Otaknya membaca chat dengan IndoBERT, menimbang dengan Fuzzy Mamdani, lalu menulis
kalimat lewat LLM atau templat.

File ini adalah pintu masuk repo: gambaran singkat, cara menjalankan di komputer sendiri, dan peta file penjelasan
lain. Aturan permainan ada di [GAME_CONCEPT.md](GAME_CONCEPT.md), sedangkan susunan kode ada di
[CODE_GUIDE.md](CODE_GUIDE.md).

Repo ini bernama `GamesSilentTerror`. Database (`shadow_heist`), container (`shadow_*`), dan sebagian kode masih
memakai nama proyek lama, Shadow Heist.

Game ini bagian dari skripsi. Naskah penelitiannya:
[Naskah skripsi Silent Terror (OneDrive BINUS)](https://binusianorg-my.sharepoint.com/personal/andy_saputra001_binus_ac_id/_layouts/15/guestaccess.aspx?share=IQDKQcDT5f1NSIhXTwwSsCgVAUckMBzh9nTX9KbN52iZ1sE&e=RmW4Ck).

## Peta file penjelasan

| File | Isi | Baca bila |
| --- | --- | --- |
| `README.md` (file ini) | Gambaran, menjalankan lokal, panel, container dan data | Baru pertama membuka repo |
| [GAME_CONCEPT.md](GAME_CONCEPT.md) | Aturan permainan, perilaku bot, angka keseimbangan komposisi role | Ingin tahu cara main atau cara bot bertindak |
| [CODE_GUIDE.md](CODE_GUIDE.md) | Susunan folder, aturan lapisan, gaya kode, mengubah otak bot dan fuzzy, tes dan simulasi | Akan mengubah kode |
| [backend/README.md](backend/README.md) | Variabel environment, pengaturan dari panel, menjalankan backend tanpa Docker, pola SQL di model | Mengatur `.env`, key, atau model |
| [backend/migrations/README.md](backend/migrations/README.md) | Daftar migrasi SQL dan cara menambah migrasi | Mengubah tabel |
| [backend/deployment/README.md](backend/deployment/README.md) | Update rutin backend di VM Azure: backup, migrasi, build | Memperbarui produksi |
| [backend/deployment/AZURE_SETUP.md](backend/deployment/AZURE_SETUP.md) | Pemasangan pertama VM Azure, DNS, Google OAuth, Vercel | Menyiapkan server baru |
| [OLLAMA.md](OLLAMA.md) | Ollama lokal dan link LLM untuk penulis kalimat bot | Memakai LLM sendiri |
| [ai-docker/README.md](ai-docker/README.md) | LLM di laptop yang dibuka ke VM lewat Cloudflare Tunnel | VM ingin memakai GPU laptop |
| [frontend/STYLING.md](frontend/STYLING.md) | Token warna, font, dan berkas CSS per halaman | Mengubah tampilan |
| [frontend/DEPLOYMENT.md](frontend/DEPLOYMENT.md) | Deploy frontend ke Vercel | Memasang frontend publik |
| [frontend/docker/README.md](frontend/docker/README.md) | Frontend lokal yang memakai backend produksi | Mengerjakan frontend saja |

**Dokumen web** ada di panel administrator, menu **08 Dokumen** (berkas `backend/public/dokumen/`). Mulailah dari
**Peta Dokumen**, yang menjelaskan isi dan urutan baca dokumen lain: Arsitektur Sistem, ERD, Proses AI, Bedah Alur
Backend, Diagram Alir NLU, Kode NLU Intent, Kode NLU Target, Diagram Alir Fuzzy Logic, Bedah Otak Fuzzy, Cara Kerja
Bot, dan Kode Fuzzy Logic. Berkas HTML di repo adalah salinan hasil pembangun dokumen di
`communicationfolder/<topik>-<tanggal>/`, folder lokal yang tidak ikut Git. Ubah sumbernya, bangun ulang, lalu
salin hasilnya ke `backend/public/dokumen/`.

**Notebook skripsi** ada di luar repo, di `../training/prethesis/ai_2_dataset_baru/` (`npc_fuzzy.ipynb`,
`npc_nlg.ipynb`, dan notebook NLU). Notebook hanya untuk laporan. Sumber logika bot adalah kode di
`backend/app/bot/`; lihat [CODE_GUIDE.md](CODE_GUIDE.md#mengubah-logika-bot).

## Fitur yang sudah jalan

- Daftar akun, login username dan password (email juga diterima untuk akun yang punya email), login Google, dan
  pilihan avatar (6 skin, tersimpan per akun).
- Main page, buat atau gabung ruangan untuk 4–10 peserta, dan bot opsional pengisi kursi kosong. Hanya pembuat
  ruangan yang mengatur bot dan memulai game.
- Role acak dari server, layar persiapan, ronde siang → Tribunal → malam (ronde 1 tanpa Tribunal) sampai salah satu
  kubu menang, skill dan cooldown, voting, eksekusi, chat tim malam, serta kondisi kemenangan.
- Survei setelah pertandingan, dengan pertanyaan yang diatur dari panel.
- Panel administrator di `/panel` dengan delapan menu (lihat [Panel administrator](#panel-administrator)).

Role: **Hitman** (Hostage, Gag Order), **Spy** (Guard), **Stalker** (Peek), dan **Civilian**. Rincian aturan,
durasi fase, dan perilaku bot ada di [GAME_CONCEPT.md](GAME_CONCEPT.md).

## Gambaran sistem

| Bagian | Teknologi | Letak |
| --- | --- | --- |
| Frontend | Angular 21 | `frontend/` |
| Backend | Python 3.11, FastAPI untuk HTTP, Socket.IO untuk chat | `backend/app/` |
| Database | MySQL 8.4, database `shadow_heist` | `backend/migrations/` (skema) |
| Otak bot | IndoBERT (membaca chat), Fuzzy Mamdani (21 sistem), NLG (LLM atau templat) | `backend/app/bot/` |
| Gateway | Nginx lokal (`proxy/nginx.conf`); Caddy di Azure | `proxy/`, `backend/deployment/` |

Backend adalah sumber kebenaran, bukan browser atau AI. Engine pertandingan memvalidasi setiap aksi, vote, dan chat,
termasuk milik bot. Bila otak bot gagal, aksi cadangan engine mengisi aksi yang kosong. Chat manusia hanya
diperiksa, disimpan, dan disiarkan; bot membacanya sendiri lewat IndoBERT.

Otak bot terdiri dari tiga tahap. Rinciannya ada di [GAME_CONCEPT.md](GAME_CONCEPT.md#npc-otak-bot), dan letak
kodenya di [CODE_GUIDE.md](CODE_GUIDE.md#otak-bot-di-kode).

| Tahap | Guna |
| --- | --- |
| NLU (IndoBERT, dua model: intent dan target) | Membaca chat menjadi intent (menuduh, membela, netral) dan siapa yang dituju |
| Penalaran (Fuzzy Mamdani) | Memilih tuduhan, pembelaan, vote, dan aksi malam |
| NLG (rantai penulis LLM, lalu templat) | Mengubah rencana menjadi kalimat. Jalur LLM yang gagal dilewati; tanpa jalur hidup, bot memakai templat |

Semua bot memakai otak Fuzzy. Metode lama yang sudah diarsipkan dicatat di
[GAME_CONCEPT.md](GAME_CONCEPT.md#metode-yang-diarsipkan).

## Menjalankan di komputer sendiri

### Persiapan

- Git dan Docker dengan perintah `docker compose`. Bila memakai Docker Desktop, jalankan aplikasinya dulu dan pakai
  Linux containers.
- Internet untuk mengunduh image, dependency, dan model.
- Port lokal `4200`, `8000`, dan `3307` kosong. Mode Ollama juga memakai `11435`.
- Untuk mode Ollama: RAM dan disk yang cukup. Versi CPU tidak butuh GPU; versi NVIDIA butuh GPU dan driver yang
  bisa diakses Docker.

Python, Node.js, dan MySQL tidak perlu dipasang di host bila semuanya dijalankan lewat Docker.

### Langkah

1. **Clone repo**, lalu jalankan semua perintah Compose dari folder ini (tempat `docker-compose.yml`):

   ```sh
   git clone https://github.com/Andysaputra1/GamesSilentTerror.git
   cd GamesSilentTerror
   ```

2. **Siapkan `.env`** sekali saja saat setup awal. Jangan menimpa `.env` yang sudah diisi; file ini berisi secret dan
   tidak boleh di-commit.

   ```powershell
   Copy-Item .env.example .env      # Windows PowerShell
   ```

   ```sh
   cp .env.example .env             # Linux/macOS
   ```

   Arti tiap variabel ada di [backend/README.md](backend/README.md#variabel-environment).

3. **Salin dua model IndoBERT** (sekitar 440 MB masing-masing, diabaikan Git). Tanpa model ini otak bot gagal
   dimuat: bot tidak chat dan hanya memakai aksi cadangan engine.

   ```text
   backend/artifacts/indobert/intent/  ← models/notebook_standalone/intent_classifier_transformer
   backend/artifacts/indobert/target/  ← models/target_classifier/target_classifier_transformer
   ```

   Sumbernya folder `models/` di `../training/prethesis/ai_2_dataset_baru/`. Folder target harus memuat
   `pair_builder.json` dan `ambang_target.json` hasil `nlu_target.ipynb`. Bila backend dijalankan langsung di host
   (bukan Docker) dan folder notebook itu ada di sebelah repo, backend juga menemukan modelnya di sana.

4. **Pilih file Compose.** Keduanya mandiri (bukan base + override), dengan service, port, dan volume yang sama.
   Jangan menjalankan keduanya bersamaan, dan pakai file yang sama pada semua perintah berikutnya.

   | File | Untuk |
   | --- | --- |
   | `docker-compose.yml` | CPU, termasuk MacBook dan mesin tanpa NVIDIA. Perintah tanpa `-f` memakai file ini |
   | `docker-compose.gpu.yml` | GPU NVIDIA. Tambahkan `-f docker-compose.gpu.yml` pada setiap perintah |

5. **Jalankan** dengan salah satu mode di bawah: [A. Ollama lokal](#a-llm-lokal-lewat-ollama) atau
   [B. OpenRouter](#b-llm-lewat-openrouter-tanpa-ollama).

6. **Siapkan login panel** sekali, dari root repo (butuh Python dengan dependency backend; bisa juga dijalankan di
   container lalu hasilnya disalin ke `.env`):

   ```sh
   python backend/scripts/setup_panel.py .env
   ```

   Skrip ini menulis `PANEL_USERNAME=administrator` dan `PANEL_PASSWORD_HASH`, serta membuat
   `PANEL_ENCRYPTION_KEY` bila belum ada. Simpan kunci itu baik-baik: API key yang disimpan dari panel dienkripsi
   dengannya. Sesudahnya recreate backend (lihat [Container dan data](#container-dan-data)).

7. **Buka aplikasi** di alamat pada tabel [Alamat lokal](#alamat-lokal), lalu ikuti
   [Mencoba permainan](#mencoba-permainan).

### A. LLM lokal lewat Ollama

Isi di `.env`:

```dotenv
AI_PROVIDER=docker
OLLAMA_MODEL=14
OLLAMA_MODELS_TO_PULL=qwen3:14b
```

```sh
# CPU atau MacBook (Ollama tetap di Docker, tidak perlu dipasang di macOS)
docker compose up -d --build
docker compose logs -f ollama-models

# Mesin NVIDIA
docker compose -f docker-compose.gpu.yml up -d --build
docker compose -f docker-compose.gpu.yml logs -f ollama-models
```

Startup pertama mengunduh image dan model, jadi bisa lama. `Ctrl+C` hanya keluar dari tampilan log. Service
`ollama-models` yang berhenti dengan exit code `0` itu normal: tugasnya hanya mengunduh model. Penulis kalimat bot
memakai Ollama ini sebagai jalur "LLM sendiri lewat link". Pilihan model (`4`, `8`, `14`), kecepatan CPU, dan
pemeriksaan model ada di [OLLAMA.md](OLLAMA.md).

### B. LLM lewat OpenRouter, tanpa Ollama

Isi di `.env` (key juga bisa diisi nanti dari panel **Konfigurasi AI**):

```dotenv
AI_PROVIDER=api
OPENROUTER_API_KEY=isi_key_pribadi_di_sini
```

Jalankan hanya service aplikasi dan dependency-nya:

```sh
docker compose up -d --build mysql phpmyadmin ai-engine gateway frontend
```

`docker compose up` tanpa daftar service ikut menyalakan Ollama dan pengunduh modelnya. Ollama yang sudah jalan tidak
berhenti sendiri saat mode diganti; hentikan dengan `docker compose stop ollama-models ollama`. API key hanya dibaca
backend, dan pemakaiannya bisa menimbulkan biaya di akun OpenRouter.

Model OpenRouter penulis kalimat diatur di panel **Otak NPC** (atau `NPC_OPENROUTER_MODEL`); bawaan kode
`qwen/qwen3-14b`. Model yang dipakai produksi tercatat di
[backend/deployment/README.md](backend/deployment/README.md#panel-dan-secret-di-vm).

### Alamat lokal

| Tujuan | Alamat |
| --- | --- |
| Aplikasi | http://localhost:4200 |
| Panel administrator | http://localhost:8000/panel |
| Status backend (database, provider, model) | http://localhost:8000/app-status |
| Kesiapan skema database | http://localhost:8000/ready |
| Dokumentasi API | http://localhost:8000/docs |
| phpMyAdmin | http://localhost:8000/phpmyadmin/ |
| MySQL dari host atau DB client | `localhost:3307`, database `shadow_heist` |
| Ollama dari host (mode A) | http://localhost:11435 |

Login phpMyAdmin memakai `MYSQL_USER` dan `MYSQL_PASSWORD` dari `.env`, bukan akun game. Backend dan phpMyAdmin
berbagi port `8000` lewat gateway Nginx; port `3307` hanya untuk koneksi MySQL.

## Mencoba permainan

Database baru tidak berisi akun. Buat akun lewat tombol daftar di halaman login, login Google, menu **Manajemen user**
di panel, atau CLI di bawah.

1. Login, lalu di Main page pilih **Enter Tribunal**.
2. **Buat Ruangan** (pilih kapasitas) atau **Gabung** dengan kode ruangan.
3. Pemilik ruangan menekan **+ Bot** bila ingin kursi kosong diisi bot. Dengan bot, game bisa dicoba sendirian;
   tanpa bot, siapkan minimal 4 akun.
4. Pemilik ruangan menekan **Mulai Permainan**; anggota lain menekan **Masuk Permainan**.
5. Sesudah pertandingan, isi survei, lalu kembali ke lobby → Keluar ruangan → buat ruangan baru. Satu ruangan hanya
   untuk satu pertandingan.

Untuk mencoba chat AI, pakai durasi standar. Keputusan atau kalimat bot yang baru selesai sesudah fase berganti
dibuang, jadi fase mode cepat yang singkat membuat banyak kalimat bot tidak tampil.

Akun yang sama di beberapa tab tetap satu pemain. Akun teman bisa dibuat lewat CLI lokal; password diketik
tersembunyi, disimpan sebagai hash, dan akun lama tidak ditimpa:

```sh
docker compose exec ai-engine python scripts/create_user.py teman1 --name "Teman Satu"
```

## Panel administrator

Panel ada di http://localhost:8000/panel dan memakai akun administrator tersendiri (langkah 6 di atas), **bukan** akun
game. Sesi panel berlaku 8 jam dan otomatis tidak berlaku lagi bila password panel diganti.

| Menu | Isi |
| --- | --- |
| 01 Konfigurasi AI | Provider (`api` atau `docker`), sumber key OpenRouter, URL dan token link LLM sendiri, model lokal |
| 02 Checker | Jejak tiap chat manusia (cek → simpan → kirim) dan tiap langkah bot (NLU, penalaran, penulis kalimat) per ruangan |
| 03 Riwayat chat | Arsip chat dari MySQL dengan filter dan ekspor CSV, termasuk intent, target, dan konteks bacaan IndoBERT |
| 04 Manajemen user | Tambah user, ubah nama atau username, reset password akun lokal, hapus akun tanpa menghapus riwayat chat |
| 05 Otak NPC | Penulis kalimat, urutan rantai penulis, model OpenRouter, model LLM link, tombol **Tes koneksi semua prioritas**, status NLU IndoBERT |
| 06 Survei | Pertanyaan survei, urutannya (seret ⋮⋮ atau tombol ▲▼), ringkasan jawaban, ekspor CSV, dan pembersihan jawaban |
| 07 Simulasi | Pertandingan tiruan admin + 3–9 bot dengan otak asli: chat, flowchart proses AI yang menyala per tahap, dan kode asli tiap tahap |
| 08 Dokumen | Dokumen web sistem, dimulai dari Peta Dokumen (lihat [Peta file penjelasan](#peta-file-penjelasan)) |

**Ekspor CSV.** Keduanya UTF-8 dengan BOM.

- Survei (`survei_silent_terror.csv`): teks yang diawali `=`, `+`, `-`, `@`, tab, atau CR diberi awalan `'` supaya
  spreadsheet tidak menjalankannya sebagai formula. Angka tetap angka.
- Riwayat chat (`riwayat-chat.csv`): isi pesan disimpan persis karena dipakai sebagai dataset NLU. Kolomnya
  `pengirim`, `teks_chat`, `label_intent`, `chat_sebelumnya`, `daftar_pemain`, `target`, `session_id`, `chat_id`,
  `room_code`, `confidence`, `sender_kind`, `waktu_utc`. Filter tanggal memakai hari WIB, dan filter pengirim
  `all`/`human`/`bot`/`legacy` (pesan lama tidak ditebak manusia atau bot). Saat membuka file ini di spreadsheet,
  impor `teks_chat` sebagai teks.

Pengaturan key, model, dan link dari panel dijelaskan di [backend/README.md](backend/README.md#pengaturan-dari-panel).

## Login Google

1. Di Google Cloud Console, buat OAuth client jenis **Web application** dengan Authorized JavaScript origins
   `http://localhost:4200`. Redirect URI tidak diperlukan karena alurnya popup.
2. Isi `GOOGLE_CLIENT_ID=...apps.googleusercontent.com` di `.env`, lalu recreate backend. Client Secret tidak dipakai;
   jangan menaruh JSON kredensial di `.env`.
3. Domain deployment harus HTTPS dan didaftarkan sebagai origin. IP LAN lewat HTTP tidak didukung login Google, tetapi
   login password tetap bisa dipakai lewat LAN.

Aturan akun, sesi, dan verifikasi token ada di [CODE_GUIDE.md](CODE_GUIDE.md#akun-sesi-dan-login). Panduan resmi:
[Google Identity Services setup](https://developers.google.com/identity/gsi/web/guides/get-google-api-clientid) dan
[verifikasi token backend](https://developers.google.com/identity/gsi/web/guides/verify-google-id-token).

## Container dan data

```sh
docker compose ps -a                 # status, termasuk initializer yang sudah selesai
docker compose logs -f ai-engine     # log backend; Ctrl+C untuk keluar
docker compose down                  # berhenti tanpa menghapus volume
```

Sesudah mengubah `.env`, recreate backend (restart saja tidak memuat environment baru):

```sh
docker compose up -d --force-recreate ai-engine
docker compose restart gateway
```

- Untuk menyalakan lagi, ulangi perintah `up` mode A atau B. `--build` perlu bila image atau dependency berubah.
- Kode Python di-bind-mount, jadi perubahan kode cukup `docker compose restart ai-engine`. Frontend memantau source
  sendiri.
- Untuk pindah file Compose, hentikan stack lama (`down` tanpa `-v`), lalu `up` dengan file baru dari folder yang
  sama. Volume dipakai ulang.
- Database disimpan di volume `shadow_heist_mysql_data`, model Ollama di `games_ollama_data`. **Jangan memakai
  `docker compose down -v` bila data atau model masih diperlukan**: opsi itu menghapus kedua volume. Volume bukan
  pengganti backup.
- Restart atau recreate backend menghapus pertandingan yang sedang jalan, karena state pertandingan hanya ada di
  memori ([Batas implementasi](CODE_GUIDE.md#batas-implementasi)). Arsip chat di MySQL tetap ada.
- SQL di `backend/migrations/` (V01–V11) hanya jalan otomatis saat volume database pertama kali dibuat. Database yang
  sudah berisi perlu menjalankan migrasi baru secara manual; lihat
  [backend/migrations/README.md](backend/migrations/README.md).

## Testing lewat LAN

Frontend development mengizinkan `localhost`, `127.0.0.1`, dan IP LAN pengembang `192.168.40.176`. Untuk IP lain:

1. Ubah kedua daftar `allowedHosts` (build dan serve) di `frontend/angular.json`.
2. Tambahkan origin lengkap ke `CORS_ORIGINS` di `.env`, mis.
   `CORS_ORIGINS=http://localhost:4200,http://127.0.0.1:4200,http://192.168.40.176:4200`. Daftar ini berlaku untuk
   HTTP API dan Socket.IO. Jangan memakai wildcard.
3. Terapkan: `docker compose up -d --force-recreate ai-engine frontend`, lalu `docker compose restart gateway`.
4. Teman di jaringan yang sama membuka `http://<IP-LAN>:4200`. Jangan memakai IP adapter WSL.

Bila perangkat lain masih timeout, periksa firewall dan isolasi klien Wi-Fi. Jangan membuka MySQL atau phpMyAdmin ke
internet, dan jangan mematikan firewall seluruhnya.

## Mengembangkan frontend lewat Docker

Service `frontend` sudah menjalankan development server Angular di http://localhost:4200, jadi `ng serve` tidak
perlu dijalankan di host. `frontend/src` dan `frontend/public` dipasang ke container, sehingga perubahan source
langsung dipantau.

```sh
# Membuat komponen baru (container harus aktif)
docker compose exec frontend npx ng generate component features/nama-komponen

# Setelah dependency di frontend/package.json berubah
docker compose up -d --build frontend
```

Hasil build ada di `/app/dist/frontend` di dalam container dan tidak dipasang ke host. Jangan mengedit `dist` sebagai
source. Belum ada target `ng e2e`. Perintah tes dan build ada di
[CODE_GUIDE.md](CODE_GUIDE.md#tes-dan-simulasi); gaya tampilan di [frontend/STYLING.md](frontend/STYLING.md).

## Jika belum berjalan

| Gejala | Pemeriksaan |
| --- | --- |
| Docker tidak bisa dihubungi | Pastikan Docker Engine atau Desktop aktif; jalankan `docker info` |
| Error perangkat atau driver NVIDIA | File GPU hanya untuk mesin NVIDIA; di Mac pakai file CPU atau mode B |
| Port sudah dipakai | Hentikan service lain di port itu. Mengubah port juga perlu menyesuaikan URL frontend, CORS, dan proxy |
| Login gagal atau backend belum siap | Periksa `docker compose ps -a`, log `ai-engine` dan `mysql`, lalu `/ready`. Database lama mungkin belum menjalankan migrasi terbaru |
| Bot diam atau kalimatnya kaku | Buka panel **Otak NPC**: NLU harus tertulis IndoBERT, dan minimal satu jalur penulis hidup (atau `NPC_WRITER=templat`). Periksa `database_ready` di `/app-status` |
| Panel tidak bisa login | Pastikan `PANEL_PASSWORD_HASH` dibuat dengan `setup_panel.py` dan backend sudah di-recreate |
| Ruangan tidak ditemukan | Backend mungkin baru restart; buat ruangan baru atau periksa kode undangan |

## Catatan keamanan

- Jejak checker dan prompt hanya tersedia lewat `/panel` dengan sesi administrator. Isinya bisa memuat role dan
  informasi privat bot (`penjelasan`: role, kecurigaan, penalaran), jadi administrator harus dipisahkan dari peserta
  eksperimen. Jejak menunjukkan masukan dan keluaran aplikasi, bukan chain-of-thought internal model.
- Compose ini untuk development lokal, bukan deployment publik. Ganti kredensial bawaan, batasi akses port database
  dan phpMyAdmin, serta siapkan HTTPS sebelum membuka ke publik. Deploy produksi ada di
  [backend/deployment/README.md](backend/deployment/README.md).
- Jangan commit `.env`, API key, file upload pengguna, model, atau artefak privat. `communicationfolder/` dan `plan/`
  juga diabaikan Git.

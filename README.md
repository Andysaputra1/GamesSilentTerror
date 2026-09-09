# Silent Terror

Game deduksi sosial berbasis percakapan: Hitman menyusup di antara warga, sementara pemain mencari identitasnya melalui alibi dan observasi chat. **Zero economy** — tanpa budget, pembelian item, atau tebusan.

Nama Silent Terror masih sementara. Nama repository, database, dan container masih menggunakan nama proyek lama, Shadow Heist.

## Status proyek

Sudah tersedia: login, main page, buat/gabung ruangan melalui kode, roster pemain, bot NOX opsional, dan chat melalui backend Python dengan respons AI. Hanya pembuat ruangan yang dapat mengatur bot; chat dipisahkan per ruangan.

Konsep role: **Hitman** (Hostage/Gag Order), **Spy** (Guard), **Stalker** (Peek), dan **Civilian** (observasi). Alur ronde yang direncanakan adalah Day → Night → Tribunal. Korban Hostage kehilangan chat dan voting tanpa pengumuman identitas target.

**Engine ronde, skill, cooldown, voting, dan kondisi kemenangan belum aktif.** Kartu peran pada halaman game masih pratinjau untuk latihan chat. Baca [konsep dan batas implementasi](GAME_CONCEPT.md).

## Persiapan

- Git dan Docker dengan perintah `docker compose`. Jika memakai Docker Desktop, jalankan aplikasinya terlebih dahulu dan gunakan Linux containers.
- Koneksi internet untuk mengunduh image, dependency, dan model AI.
- Port lokal `4200`, `8000`, dan `3307` tersedia. Mode Ollama juga menggunakan `11435`.
- Untuk mode Ollama: RAM dan ruang disk yang mencukupi. Versi CPU tidak memerlukan GPU; versi NVIDIA memerlukan GPU dan driver/runtime yang dapat diakses Docker.

Tidak perlu memasang Python, Node.js, atau MySQL di host jika seluruh aplikasi dijalankan lewat Docker.

### 1. Clone repository

```sh
git clone https://github.com/Andysaputra1/GamesShadowHeist.git
cd GamesShadowHeist
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

### 3. Siapkan model SVM — diperlukan untuk balasan bot

Minta artifact terlatih `intent_classifier.pkl` kepada pengelola proyek, lalu letakkan di:

```text
backend/artifacts/svm/intent_classifier.pkl
```

File `.pkl` sengaja diabaikan Git dan **tidak tersedia hanya dengan clone repository**. Gunakan hanya artifact tepercaya karena pemuatan pickle dapat menjalankan kode.

Pada implementasi saat ini, tanpa model SVM yang berhasil dimuat, pesan pemain masih bisa diteruskan tetapi jalur balasan NOX tidak memanggil LLM. Ini berlaku untuk mode Ollama maupun API. Lihat [panduan artifact SVM](backend/artifacts/svm/README.md).

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

### B. AI melalui API, tanpa menjalankan Ollama

Ubah `.env`:

```dotenv
AI_PROVIDER=api
OPENAI_API_KEY=isi_key_pribadi_di_sini
OPENAI_MODEL=gpt-5-mini
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
| Status backend | http://localhost:8000/app-status |
| Dokumentasi API | http://localhost:8000/docs |
| phpMyAdmin | http://localhost:8000/phpmyadmin/ |
| MySQL dari host / DB client | `localhost:3307`, database `shadow_heist` |
| Ollama dari host (mode lokal) | http://localhost:11435 |

Login aplikasi development: **`user1` / `user132`**. Akun ini disiapkan oleh migration saat inisialisasi database baru.

Alur mencoba: **Login → Main page → Enter Tribunal → Buat Ruangan / Gabung → + Bot → Mulai Diskusi**. Ketik pesan dan tunggu NOX membalas. Tanpa bot, chat hanya antar pemain.

Untuk login phpMyAdmin, gunakan `MYSQL_USER` dan `MYSQL_PASSWORD` dari `.env`, bukan akun game. Backend dan phpMyAdmin berbagi port `8000` melalui gateway Nginx; port `3307` hanya untuk koneksi MySQL, bukan halaman web.

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
- Lobby dan konteks AI masih berada di memori satu proses backend. Restart/recreate backend menghilangkan ruangan aktif dan konteks percakapan. Catatan chat di MySQL tetap tersimpan; pemulihan lobby/chat ke UI belum tersedia.
- SQL di `backend/migrations/` dijalankan saat database pertama kali diinisialisasi. Menambah file migration atau mengganti password di `.env` tidak otomatis memperbarui database yang sudah berisi data. Lihat [catatan migration](backend/migrations/README.md).

## Jika belum berjalan

| Gejala | Pemeriksaan |
| --- | --- |
| Docker tidak dapat dihubungi | Pastikan Docker Engine/Desktop aktif; jalankan `docker info`. |
| Error perangkat/driver NVIDIA | Pastikan file GPU hanya dipakai pada mesin NVIDIA yang didukung; di Mac gunakan file CPU atau mode API. |
| Port sudah digunakan | Hentikan service lokal lain yang memakai port tersebut. Perubahan port juga perlu diselaraskan dengan URL frontend, CORS, dan proxy. |
| Login gagal / backend belum siap | Periksa `docker compose ps -a`, log `ai-engine` dan `mysql`, lalu status backend. Database lama mungkin belum memiliki migration akun. |
| Pesan masuk tetapi NOX tidak membalas | Pastikan bot ditambahkan, `model_ready=true`, dan `database_ready=true` di `/app-status`. Untuk Ollama, periksa `ollama_ready=true` dan daftar model; untuk API, periksa key/provider dan log backend. Key terisi belum berarti key valid. |
| Ruangan tidak ditemukan | Buat ruangan baru setelah backend restart, atau periksa kembali kode undangan. |

## Struktur dan pengujian

```text
frontend/          Angular: login, main page, lobby, game/chat
backend/           Python FastAPI + Socket.IO
  config/          Konfigurasi aplikasi, AI, MySQL, upload
  controller/      Endpoint API dan middleware
  services/        Logika autentikasi, ruangan, analisis AI
  models/          Query SQL terparameterisasi
  module/          Konektor MySQL, klien Ollama, helper upload
  artifacts/svm/   Model intent privat, disediakan terpisah
  migrations/     Skema SQL dan akun development
proxy/             Gateway Nginx
docker-compose.yml Service development dan volume
```

Alur analisis chat: **pesan → SVM intent → bobot agresivitas → fuzzy suspicion → LLM NOX → penyimpanan MySQL → balasan chat**. Persentase diam pada fuzzy masih nilai tetap, bukan observasi diam pemain yang sesungguhnya.

Dengan container aplikasi sudah berjalan:

```sh
docker compose exec -T ai-engine python -m unittest discover -s tests -v
docker compose exec -T frontend npm test -- --watch=false
docker compose exec -T frontend npm run build
```

Tes otomatis bukan bukti koneksi AI eksternal sedang aktif; coba chat melalui UI untuk menguji provider sebenarnya. Tes database khusus hanya boleh diarahkan ke database percobaan.

Dokumentasi lanjutan: [backend](backend/README.md), [Ollama](OLLAMA.md), [pengaturan styling](frontend/STYLING.md), dan [konsep game](GAME_CONCEPT.md).

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

### Pipeline checker (development saja)

Buka `http://localhost:4200/games/checker`, masukkan kode ruangan, lalu kirim chat
melalui game di tab lain. Link **Buka pipeline checker** di game mengisi kode
secara otomatis. Monitor menampilkan pesan, intent SVM, bobot/agresivitas,
input/output fuzzy, prompt persis yang diberikan ke LLM, provider/model,
output/fallback, status proses, dan ID pesan MySQL. Ini bukan chain-of-thought
internal model; hanya input/output dan tahap aplikasi yang dapat diamati.

Auto refresh setiap 2 detik, dengan 100 jejak terbaru per ruangan di memori.
Jejak lama sebelum fitur aktif tidak direkonstruksi dari DB dan jejak hilang saat
backend restart. Silence fuzzy masih konstan 20%, bukan pengukuran pemain.

**Sesuai kebutuhan development, route ini dan GET `/api/rooms/{code}/checker`
tidak memakai guard/autentikasi.** Siapa pun dengan kode ruangan dapat membaca
chat dan prompt yang membocorkan role NOX. Jangan expose aplikasi/API ini ke
internet; wajib tambahkan pembatasan akses atau nonaktifkan checker sebelum
deployment publik. Monitor tidak mengirim token/API key konfigurasi ke browser.

Compose ini untuk development lokal, bukan deployment publik siap pakai. Ganti kredensial default dan akun demo sebelum deployment; batasi akses port database/phpMyAdmin, serta siapkan HTTPS dan pengamanan deployment. Jangan commit `.env`, API key, file upload pengguna, atau artifact privat. Folder referensi desain `communicationfolder/` juga diabaikan Git.

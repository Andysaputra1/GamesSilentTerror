# Silent Terror

Game deduksi sosial berbasis percakapan: Hitman menyusup di antara warga, sementara pemain mencari identitasnya melalui alibi dan observasi chat. **Zero economy** — tanpa budget, pembelian item, atau tebusan.

Nama Silent Terror masih sementara. Nama repository, database, dan container masih menggunakan nama proyek lama, Shadow Heist.

## Status proyek

Sudah dapat dimainkan: login, main page, buat/gabung ruangan, 4–10 peserta tanpa batas ronde (berakhir hanya saat salah satu kubu menang), bot opsional, role acak dari server, timer Day → Night → Tribunal, skill/cooldown, voting, eksekusi, dan kondisi kemenangan. Panel administrator menyediakan tambah user, reset password akun lokal, dan penghapusan akun tanpa menghapus riwayat chat. Hanya pembuat ruangan yang mengatur bot dan memulai game.

Role: **Hitman** (Hostage/Gag Order), **Spy** (Guard), **Stalker** (Peek), dan **Civilian** (observasi). Korban Hostage tetap hidup dan kehilangan chat serta voting permanen, tetapi skill malam tetap tersedia sesuai role/cooldown; identitas target tidak diumumkan.

Engine menjadi sumber kebenaran, bukan browser/LLM. NPC mengambil giliran mandiri: model terpilih memilih aksi, vote, dan percakapan dari konteks privat masing-masing. Engine memvalidasi keputusan; fallback aturan mengisi aksi yang kosong jika model gagal. Keputusan `wait` yang valid tetap dihormati. SVM/fuzzy menganalisis pesan manusia untuk arsip. Baca [aturan, alur kode, dan batas implementasi](GAME_CONCEPT.md).

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

### 3. Siapkan model SVM — untuk analisis intent dan balasan lobby lama

Minta artifact terlatih `intent_classifier.pkl` kepada pengelola proyek, lalu letakkan di:

```text
backend/artifacts/svm/intent_classifier.pkl
```

File `.pkl` sengaja diabaikan Git dan **tidak tersedia hanya dengan clone repository**. Gunakan hanya artifact tepercaya karena pemuatan pickle dapat menjalankan kode.

Tanpa model SVM, pesan pemain masih bisa diteruskan dan scheduler NPC pertandingan tetap dapat memanggil LLM. Analisis intent dan balasan reaktif NOX di lobby lama memerlukan SVM. Ini berlaku untuk mode Ollama maupun API. Lihat [panduan artifact SVM](backend/artifacts/svm/README.md).

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
| Panel backend development | http://localhost:8000/admin |

### Testing lewat LAN

Frontend development mengizinkan `localhost`, `127.0.0.1`, dan IP LAN pengembang `192.168.40.176`. Untuk IP lain, sesuaikan kedua daftar `allowedHosts` (build security dan serve) di `frontend/angular.json`, lalu tambahkan origin lengkap ke `.env`, misalnya `CORS_ORIGINS=http://localhost:4200,http://127.0.0.1:4200,http://192.168.40.176:4200`. Konfigurasi ini berlaku untuk HTTP API dan Socket.IO. Jangan menggunakan wildcard untuk membuka semua host/origin.

Jalankan `docker compose -f docker-compose.gpu.yml up -d --no-deps ai-engine frontend`, lalu `docker compose -f docker-compose.gpu.yml restart frontend gateway` setelah mengubah konfigurasi (pakai `docker-compose.yml` untuk CPU). Restart backend menghapus pertandingan dalam memori, bukan database/model. Teman satu jaringan membuka `http://192.168.40.176:4200`; jangan memakai IP adapter WSL. Jika masih timeout dari perangkat lain, periksa firewall dan isolasi klien Wi-Fi. Jangan membuka MySQL/admin ke internet atau mematikan firewall keseluruhan.

### Panel backend development

### Akun, desain Kimberly, dan login Google

Halaman login menggunakan `auth.html` + `auth.scss` dari desain Kimberly. File CSS lama dan duplikat `auth_kim.*` sudah digantikan; aset sumber lainnya tetap dipertahankan.

- Register memakai username 3–40 huruf/angka/underscore, email, password 10–128 karakter dan kedua konfirmasi. Password disimpan sebagai PBKDF2; username/email duplikat ditolak. Setelah register berhasil pengguna mendapat sesi dan masuk main page.
- Login biasa menerima username atau email. Konfirmasi email di form **bukan verifikasi lewat email**. Reset password dan penautan akun belum tersedia; hubungi pengelola.
- Database lama harus menerapkan `backend/migrations/V4__account_identities.sql` satu kali. Database baru membaca migrasi dari volume init MySQL. Jangan hapus volume untuk migrasi.
- Google memakai Identity Services popup + callback JavaScript. Isi `GOOGLE_CLIENT_ID=...apps.googleusercontent.com` di `.env`, lalu rebuild/recreate backend. Client Secret tidak digunakan, dan jangan menaruh JSON kredensial mentah di `.env`.
- Google Console: OAuth client jenis **Web application**, Authorized JavaScript origins `http://localhost:4200`; redirect URI tidak diperlukan untuk alur ini. Domain deployment harus HTTPS dan didaftarkan sebagai origin; IP LAN HTTP tidak didukung login Google. Login password tetap bisa digunakan lewat LAN.
- Backend memverifikasi signature/audience/issuer/expiry token Google, email verified, dan nonce sekali pakai (5 menit). Identitas memakai Google `sub`; email yang sama tidak otomatis menautkan/mengambil alih akun lama. Token Google tidak disimpan; sesi aplikasi tetap dapat dicabut lewat logout.
- Pembatasan percobaan 15/menit per alamat peer/endpoint dan nonce disimpan di memori untuk satu worker development. Di belakang gateway beberapa pengguna bisa berbagi batas peer; sebelum production gunakan rate limiter bersama/proxy tepercaya, HTTPS, verifikasi email, reset password, dan audit lanjutan.

Panduan resmi: [Google Identity Services setup](https://developers.google.com/identity/gsi/web/guides/get-google-api-clientid) dan [verifikasi token backend](https://developers.google.com/identity/gsi/web/guides/verify-google-id-token).

### Pengelolaan backend

Buka `/admin` pada port 8000, login dengan admin development `user1` / `user132`. Janice/Kimberly tidak memiliki akses admin. Atur daftar admin lewat `ADMIN_USERNAMES` (dipisahkan koma); panel hanya tersedia ketika `APP_ENVIRONMENT=development`. Kredensial demo ini **bukan pengamanan untuk deployment publik**: ganti akun/password dan nonaktifkan mode development sebelum deployment.

- Pilih provider `api` atau `docker`, serta model Ollama `8`/`14`. Backend memeriksa konfigurasi API/model tersedia sebelum menerima perubahan. Ketersediaan model tidak menjamin respons cepat; Docker CPU bisa lambat.
- Perubahan berlaku global untuk request AI berikutnya; request berjalan tetap menggunakan provider awal. Override hanya di memori, tidak menulis `.env`. Tombol reset atau restart backend mengembalikan konfigurasi environment.
- Pilih room untuk melihat aktivitas fungsi yang diinstrumentasi, parameter, hasil/status, dan trace SVM → fuzzy → prompt LLM → output → pengiriman chat. Ini bukan debugger semua fungsi Python. Event `running` adalah catatan saat fungsi mulai; lihat event akhir dengan `call_id` yang sama untuk hasilnya.
- Log aktivitas dibatasi 2.000 event dalam memori, endpoint menampilkan 200 terbaru. Restart menghapus log ini. Password/token/API key disensor, tetapi chat, prompt, dan informasi role dalam trace tetap sensitif dan hanya untuk admin.

Implementasi: `backend/controller/api/admin.py`, `backend/public/admin/`, `backend/services/ai_runtime_service.py`, dan `backend/services/activity_service.py`. Desain login/main page Angular tidak diubah.
| MySQL dari host / DB client | `localhost:3307`, database `shadow_heist` |
| Ollama dari host (mode lokal) | http://localhost:11435 |

Login aplikasi development: **`user1` / `user132`**. Akun ini disiapkan oleh migration saat inisialisasi database baru.

Akun demo tambahan: **`janice` / `user132`** dan **`kimberly` / `user132`** melalui migration `V3__add_demo_players.sql`. Database lama perlu menerapkan V3; startup backend tidak otomatis menjalankan migration. Migration tidak menimpa password akun yang sudah ada. Ketiga akun/password bersama ini hanya untuk development, bukan deployment publik.

Alur mencoba: **Login → Main page → Enter Tribunal → Buat Ruangan / Gabung → + Bot → Mulai Permainan**. Bot mengisi semua kursi kosong sampai kapasitas pilihan host sehingga bisa dicoba sendiri. Tanpa bot, siapkan minimal 4 akun berbeda. Pemilik ruangan menekan Mulai; anggota lain menekan Masuk Permainan ketika game sudah dimulai.

Di game, buka role privatmu. Saat Day, diskusikan alibi; Hitman dapat memilih target Gag. Saat Night, pilih kartu target lalu kunci Hostage/Guard/Peek jika tersedia. Saat Tribunal, pilih kartu tersangka lalu kunci vote. Pemain yang tidak bisa bertindak tetap dapat menonton. Setelah selesai, kembali ke lobby → Keluar ruangan → Buat ruangan baru.

Timer mengikuti jumlah peserta awal. Contoh enam pemain: standar 120/30/45 detik; mode cepat 20/15/15 detik. Empat pemain: standar 80/20/30 detik. Durasi tetap selama pertandingan; rincian ada di GAME_CONCEPT.md. Respons Ollama yang selesai setelah fase berubah **tidak ditampilkan** agar tidak menerobos malam atau efek bungkam; gunakan durasi standar untuk mencoba chat AI.

Saat Day, tombol **Setuju skip diskusi** mempercepat ke Night setelah seluruh manusia yang masih hidup setuju. Bot tidak dihitung. Pemain dibungkam/disandera tetap boleh menyetujui karena ini bukan chat atau vote Tribunal; status mereka tetap tidak dipublikasikan. Persetujuan tidak bisa ditarik pada ronde itu. Pemain offline belum dianggap setuju; timer normal tetap berjalan.

Selama pertandingan aktif, membuka halaman aplikasi lain/tab baru atau login ulang akan mengembalikan akun ke `/game` berdasarkan data backend, bukan hanya storage tab. Akun tidak bisa membuat/gabung pertandingan lain sebelum match selesai. Ini berlaku dalam aplikasi ini, bukan memaksa browser meninggalkan situs eksternal. Desain login dan main page tidak diubah.

### Akun teman untuk multiplayer

Akun yang sama di beberapa tab tetap satu pemain. Buat akun tambahan lewat CLI lokal (password diminta tersembunyi dan disimpan sebagai hash; akun lama tidak ditimpa):

```sh
docker compose exec ai-engine python -m module.create_user teman1 --name "Teman Satu"
```

Gunakan `-f docker-compose.gpu.yml` jika memakai stack NVIDIA. Setiap teman login dengan akun sendiri, lalu gabung memakai kode room yang sama. Pengujian lintas perangkat/LAN memerlukan konfigurasi CORS/host yang sesuai; QC lokal memakai beberapa sesi terpisah pada satu mesin.

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
- Lobby, engine pertandingan, role/aksi/vote, dan konteks AI berada di memori satu proses backend. Reload/reconnect browser memulihkan snapshot dan 100 pesan terbaru selama proses yang sama hidup. Restart/recreate backend menghilangkan pertandingan aktif. Catatan chat/analisis di MySQL tetap tersimpan, tetapi belum memulihkan pertandingan. Jangan menjalankan beberapa worker backend sebelum menambahkan shared state/persistence engine.
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

Alur chat pertandingan: **pesan → otorisasi → SVM/fuzzy → validasi ulang fase/hak chat → penyimpanan MySQL → broadcast**. Secara terpisah, timer menjalankan **NPC → konteks privat → LLM → validasi keputusan → aksi/vote/chat**. Persentase diam pada fuzzy masih nilai tetap, bukan observasi diam pemain yang sesungguhnya.

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

### Pipeline checker

Endpoint checker publik lama `GET /api/rooms/{code}/checker` sudah ditutup (HTTP 410).
Trace/prompt hanya tersedia lewat `/panel` dengan sesi administrator. Data ini dapat
berisi role dan intel privat NPC, sehingga administrator harus dipisahkan dari peserta
eksperimen. Trace menunjukkan input/output aplikasi, bukan chain-of-thought internal model.
Silence fuzzy masih konstan 20%, bukan pengukuran aktivitas pemain.

Compose ini untuk development lokal, bukan deployment publik siap pakai. Ganti kredensial default dan akun demo sebelum deployment; batasi akses port database/phpMyAdmin, serta siapkan HTTPS dan pengamanan deployment. Jangan commit `.env`, API key, file upload pengguna, atau artifact privat. Folder referensi desain `communicationfolder/` juga diabaikan Git.

# Migrasi MySQL

File ini menjelaskan folder SQL skema database: kapan file di sini dijalankan, isi tiap migrasi, dan cara menambah
migrasi baru. Perintah menjalankan migrasi di server produksi ada di
[backend/deployment/README.md](../deployment/README.md#menjalankan-migrasi-di-database-lama).

## Kapan migrasi dijalankan

- Folder ini dipakai lokal **dan** Azure. Compose memasangnya ke `/docker-entrypoint-initdb.d`, dan image MySQL
  menjalankan semua file berurutan **hanya saat volume database dibuat pertama kali**.
- Database yang sudah berisi data **tidak** menjalankan file baru. Backend juga tidak menjalankan migrasi saat
  menyala. Backup dulu, lalu jalankan file yang belum tercatat lewat MySQL client atau menu Import phpMyAdmin, sesuai
  urutan versi. Jangan mengulang semua SQL tanpa memeriksa isi database.
- Jangan memakai `docker compose down -v` untuk "mengulang migrasi": perintah itu menghapus volume database **dan**
  model Ollama. `docker compose down` biasa mempertahankan data.
- Folder ini tidak membuat akun apa pun. Akun dibuat lewat halaman daftar, login Google, menu Manajemen user di panel,
  atau `scripts/create_user.py`.

## Daftar migrasi

Nama file memakai nomor dua digit supaya MySQL menjalankannya berurutan pada volume kosong (tanpa itu `V10` jalan
sebelum `V1`). Versi yang dicatat di tabel `schema_migrations` ditulis di dalam file dan untuk file lama tanpa nol,
mis. `V5__chat_history`, supaya cocok dengan database yang sudah ada.

| File | Versi tercatat | Isi |
| --- | --- | --- |
| `V01__initial_schema.sql` | `V1__initial_schema` | `schema_migrations`, `game_sessions`, `players`, `chat_messages`, `ai_analyses` |
| `V02__add_authentication.sql` | `V2__add_authentication` | `user_accounts`, `auth_sessions` |
| `V04__account_identities.sql` | `V4__account_identities` | `account_identities`: email dan Google `sub` dengan constraint unik dan foreign key akun. Akun lama tetap bisa login dengan username |
| `V05__chat_history.sql` | `V5__chat_history` | Kolom riwayat di `chat_messages` (`sender_kind`, `match_id`, ronde, fase, …). Pesan lama ditandai `legacy` |
| `V06__admin_panel.sql` | `V6__admin_panel` | `panel_configuration`, `panel_sessions`, `checker_traces` |
| `V07__add_skin_preference.sql` | `V7__add_skin_preference` | Kolom `user_accounts.skin_id` (bawaan `dexter`) |
| `V07__survey_and_npc.sql` | `V7__survey_and_npc` | `survey_questions`, `survey_responses` (satu kiriman per akun per pertandingan, dengan salinan pertanyaan), `match_bots` (metode dan persona tiap bot). Enam pertanyaan awal diisi dengan `INSERT IGNORE` |
| `V08__fix_role_stalker_enum.sql` | `V8__fix_role_stalker_enum` | Enum role `players` memakai `stalker`, bukan `detective` |
| `V09__chat_nlu.sql` | `V9__chat_nlu` | Kolom `chat_messages.nlu`: bacaan IndoBERT tiap pesan untuk menu Riwayat chat |
| `V10__match_participants.sql` | `V10__match_participants` | `match_participants`: peserta manusia tiap pertandingan selesai, untuk survei kapan pun sesudahnya |
| `V11__survey_player_feedback.sql` | `V11__survey_player_feedback` | Lima pertanyaan survei pengalaman bermain; tidak mengubah struktur tabel |
| `V12__survey_formal.sql` | `V12__survey_formal` | Survei penelitian versi formal: sebelas pertanyaan lama diganti sepuluh pertanyaan baru, dan pengingat survei hanya untuk pertandingan mulai 13 November 2026; tidak mengubah struktur tabel |

Nomor V03 sudah tidak ada: dulu berisi akun demo yang dihapus pada 26 Oktober 2026. Hasil akhirnya 15 tabel,
termasuk `schema_migrations`. Pemakaian tiap tabel oleh backend ada di
[backend/deployment/README.md](../deployment/README.md#audit-tabel).

`/ready` hanya memeriksa V5 dan V6. Migrasi lain yang terlewat tidak membuat `/ready` gagal, tetapi fitur yang
memakainya gagal: tanpa V07 kolom `skin_id` dan tabel survei belum ada (login bisa gagal dengan 503), tanpa V08
peserta Stalker gagal diarsipkan, tanpa V09 menu Riwayat chat gagal dimuat, dan tanpa V10 arsip peserta gagal
disimpan sehingga survei sesudah keluar room hanya bisa dikirim selama 30 menit dari ingatan backend. Tanpa V11
dan V12 aplikasi tetap jalan, hanya pertanyaan survei yang tampil masih versi lama.

### Catatan V11

V11 menambah lima pertanyaan: pengalaman bermain, saran/kesan/pesan, kesenangan bersama Bot NPC (1–5), harapan untuk
Bot NPC, dan kesenangan bermain individu (1–5). Harapan Bot NPC opsional, dengan pilihan `Lebih cepat`,
`Lebih berempati`, dan `Lainnya`; empat pertanyaan lain wajib. Pada pertanyaan jenis `choice`, opsi bernama `Lainnya`
membuka isian bebas yang disimpan sebagai `Lainnya: <jawaban>`.

Kelima pertanyaan masuk paling bawah: posisinya posisi terbesar yang sudah ada ditambah 10, 20, …, 50 (pada database
baru 70–110), sama seperti pertanyaan baru dari panel. Urutan selanjutnya diatur dari menu Survei di panel (seret ⋮⋮
atau tombol ▲▼), yang menulis ulang posisi menjadi 10, 20, 30, …. Kode unik pertanyaan mencegah duplikasi bila file
dijalankan ulang. Pasang versi aplikasi yang mendukung isian `Lainnya` bersama migrasi ini; menyalakan ulang backend
saja tidak menambahkan pertanyaan.

### Catatan V12

V12 mengganti pertanyaan V07 dan V11 dengan sepuluh pertanyaan formal untuk penelitian. Delapan di antaranya adalah
pernyataan berskala 1–5 (`Sangat tidak setuju` sampai `Sangat setuju`), dan setiap pernyataan mengukur satu bagian bot:

| Kode | Pernyataan | Yang diukur |
| --- | --- | --- |
| `kesenangan_bermain` | Bermain Silent Terror bersama Bot NPC merupakan pengalaman yang menyenangkan. | Pengalaman bermain |
| `kemiripan_manusia` | Bot NPC berperilaku layaknya pemain manusia. | Kemiripan dengan manusia |
| `pemahaman_pesan` | Bot NPC memahami maksud pesan yang saya kirimkan dalam diskusi. | NLU (IndoBERT) |
| `kewajaran_bahasa` | Pesan yang ditulis Bot NPC menggunakan bahasa yang wajar dan sesuai dengan alur diskusi. | NLG |
| `ketepatan_keputusan` | Tuduhan, pembelaan, dan pilihan vote Bot NPC masuk akal berdasarkan kejadian dalam permainan. | Fuzzy |
| `kesesuaian_peran` | Tindakan Bot NPC sesuai dengan peran yang dimainkannya. | Fuzzy per role |
| `tingkat_tantangan` | Bot NPC memberikan tantangan yang sepadan, baik sebagai lawan maupun sebagai rekan satu tim. | Keseimbangan |
| `kecepatan_respons` | Bot NPC menanggapi pesan dan kejadian dalam permainan dengan cukup cepat. | Waktu tanggap |

Dua pertanyaan lainnya opsional. `aspek_perbaikan` adalah pilihan ganda tentang aspek bot yang paling perlu
ditingkatkan, dengan opsi `Lainnya` untuk isian bebas. `saran_masukan` adalah isian bebas untuk kesan, saran, atau
masukan.

Pertanyaan lama yang belum punya jawaban dihapus. Yang sudah punya jawaban hanya dinonaktifkan, karena foreign key
`survey_responses` menjaga jawaban itu tetap utuh. Jawaban lama bisa dibersihkan lewat menu Survei di panel.

V12 juga menghapus arsip `match_participants` untuk pertandingan yang selesai sebelum 13 November 2026 pukul 00.00 WIB.
Tabel itu hanya dipakai survei, jadi pengingat di Main dan pengiriman survei hanya berlaku untuk pertandingan mulai
hari itu. Ambil cadangan database sebelum menjalankan V12 di server.

## Menambah migrasi

1. Buat file dengan nomor dua digit berikutnya, mis. `V12__nama_singkat.sql`.
2. Tulis perubahan yang hanya menambah (`CREATE TABLE IF NOT EXISTS`, `ADD COLUMN`, `INSERT IGNORE`). Jangan
   menghapus data.
3. Akhiri dengan `INSERT IGNORE INTO schema_migrations (version) VALUES ('V12__nama_singkat');`.
4. Uji pada database kosong (volume baru) dan pada salinan database lama.
5. Catat file baru di tabel di atas, dan tambahkan perintahnya ke tabel migrasi di
   [backend/deployment/README.md](../deployment/README.md#menjalankan-migrasi-di-database-lama).
6. Ingatkan bahwa database lokal dan produksi yang sudah berisi harus menjalankan file ini secara manual.

`ALTER TABLE` di MySQL tidak bisa dibatalkan bersama `INSERT` penanda migrasi. Bila SQL gagal di tengah, periksa
struktur kolom sebelum mengulang.

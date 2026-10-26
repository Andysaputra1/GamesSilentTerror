# MySQL migrations

File SQL di folder ini dipakai lokal **dan** Azure: image MySQL menjalankannya berurutan saat volume
database dibuat untuk pertama kali. Beri nomor dua digit berikutnya, misalnya `V11__add_votes.sql`, agar
urutan nama file sama dengan urutan versi. Versi yang dicatat di `schema_migrations` tetap ditulis di dalam
file (file lama mencatat nama tanpa nol, mis. `V5__chat_history`). Folder ini tidak membuat akun apa pun.

Menambah file SQL tidak menjalankannya otomatis pada database yang sudah
diinisialisasi. Backend juga tidak menjalankan migration saat startup. Untuk
database lama, backup terlebih dahulu lalu terapkan SQL yang belum dijalankan
melalui MySQL client atau phpMyAdmin, sesuai urutan versinya. Jangan mengulang
semua SQL tanpa memeriksa perubahan dan data yang sudah ada.

Jangan gunakan `docker compose down -v` untuk pemakaian sehari-hari: perintah
itu menghapus volume database **dan model Ollama**, bukan hanya mengulang
migration. Gunakan `docker compose down` biasa untuk mempertahankan data.

Panduan setup database baru tersedia di [README utama](../../README.md).

`V04__account_identities.sql` menambah tabel email/Google subject, dengan constraint unik dan foreign key akun. Akun lama tetap bisa login username tanpa identitas tambahan. Jalankan pada database lama sebelum memakai registrasi atau login email/Google; tabel/akun lama tidak dihapus.

`V07__survey_and_npc.sql` menambah `survey_questions` (pertanyaan, jenis jawaban, skala, dan arti skala yang diatur dari panel), `survey_responses` (satu kiriman per akun per pertandingan, dengan salinan pertanyaan), dan `match_bots` (metode/persona tiap bot). Enam pertanyaan awal diisi dengan `INSERT IGNORE`. Cara menerapkannya di Azure: `backend/deployment/README.md`.

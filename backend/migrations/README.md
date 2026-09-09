# MySQL migrations

File SQL di folder ini dijalankan oleh image MySQL saat named volume
`mysql_data` dibuat untuk pertama kali. Gunakan pola nama berurutan, misalnya
`V2__add_votes.sql`.

Menambah file SQL tidak menjalankannya otomatis pada database yang sudah
diinisialisasi. Backend juga tidak menjalankan migration saat startup. Untuk
database lama, backup terlebih dahulu lalu terapkan SQL yang belum dijalankan
melalui MySQL client atau phpMyAdmin, sesuai urutan versinya. Jangan mengulang
semua SQL tanpa memeriksa perubahan dan data yang sudah ada.

Jangan gunakan `docker compose down -v` untuk pemakaian sehari-hari: perintah
itu menghapus volume database **dan model Ollama**, bukan hanya mengulang
migration. Gunakan `docker compose down` biasa untuk mempertahankan data.

Panduan setup database baru tersedia di [README utama](../../README.md).

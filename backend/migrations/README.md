# MySQL migrations

File SQL di folder ini dijalankan oleh image MySQL saat named volume
`mysql_data` dibuat untuk pertama kali. Gunakan pola nama berurutan, misalnya
`V2__add_votes.sql`.

Untuk mengulang seluruh migrasi pada lingkungan lokal, hapus volume database
(ini menghapus seluruh data lokal):

```powershell
docker compose down -v
docker compose up --build
```

Jangan gunakan `down -v` pada database yang datanya ingin dipertahankan.

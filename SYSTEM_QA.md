# Audit sistem permainan — 24 September 2026

## Ronde dan akhir permainan

- Sesuai koreksi aturan terbaru: **tidak ada batas ronde atau pilihan jumlah ronde**. Host hanya memilih kapasitas room.
- Setiap ronde berjalan **Siang → Malam → Tribunal**. Timer dan resolusi ditentukan backend.
- Warga menang setelah Tribunal mengeksekusi Hitman.
- Hitman menang selama masih hidup ketika warga hidup yang tidak Hostage tersisa paling banyak satu. Kondisi ini diperiksa setelah resolusi malam dan Tribunal.
- Game langsung berstatus `finished` hanya ketika salah satu dari dua kondisi kemenangan di atas terpenuhi. Aksi/chat/voting terkunci dan hasil mengikuti faksi, termasuk pemain yang dieksekusi atau menjadi Hostage.
- Jika belum ada pemenang, permainan berlanjut ke ronde berikutnya. Vote seri/tanpa suara tidak mengeksekusi siapa pun, tetapi bukan hasil seri pertandingan. Hasil kemenangan tidak berubah oleh tick berikutnya.

## Perbaikan dalam audit ini

1. Halaman game kini membersihkan pointer room lama, menghentikan polling/socket, dan kembali ke Lobby jika pengambilan snapshot ditolak karena room hilang, keanggotaan sudah tidak berlaku, atau match belum dimulai. Penolakan aksi karena pergantian fase dan gangguan jaringan tetap mempertahankan pemain di halaman game.
2. Skrip `backend/tests/live_match_smoke.py` diperbarui agar mengharapkan HTTP 410 dari checker publik lama, termasuk setelah game selesai. Endpoint ini memang ditutup; informasi pertandingan dibaca melalui snapshot privat dan checker administrator.
3. Ditambahkan integrasi HTTP dengan RoomService dan engine asli: 7 pertandingan melewati ronde 25 tanpa pemenang lalu diakhiri oleh kemenangan warga, 7 pertandingan warga menang pada Tribunal pertama, dan 7 pertandingan Hitman menang pada malam ketika tersisa satu warga bebas. Semua skenario memeriksa hasil pribadi, penguncian aksi, hasil final yang stabil, serta keluar dan pembersihan room.

## Verifikasi

| Pemeriksaan | Hasil |
| --- | --- |
| Seluruh unittest backend | 138 tes lulus |
| Seluruh tes frontend | 62 tes lulus, 12 berkas |
| UI panel (`node --test backend/tests/panel_ui.test.mjs`) | 4 tes lulus |
| Simulasi engine deterministik | 210 pertandingan: 4–10 pemain × 30 seed; hanya dua faksi pemenang |
| Integrasi HTTP lifecycle tambahan | 21 skenario dalam 3 tes backend di atas |
| Build produksi Angular + SSR/prerender | Berhasil, 7 route diprerender |
| Ruff backend | Lulus |
| Black untuk berkas Python yang diubah dan `git diff --check` | Lulus |

Suite mencakup akun/sesi, otorisasi room, kapasitas dan bot, role acak, Guard/Peek/Gag/Hostage, cooldown, voting, skip diskusi, kemenangan, informasi privat, reconnect, chat, scheduler/fallback NPC, history, panel, dan diagnostik AI. Cakupan tes bukan jaminan bahwa setiap kemungkinan interaksi telah diuji.

Backend diuji dengan dependensi yang sudah tersedia di `tmp/profile-test-deps` melalui `PYTHONPATH`, tanpa mengubah instalasi Python global. Tes memakai SQLite/fixture/mock sesuai masing-masing suite. Integrasi lifecycle memakai autentikasi dan arsip fixture, bukan akun atau database produksi. Respons provider pada suite otomatis menggunakan mock.

Build masih memberi peringatan ukuran stylesheet auth (10,43 kB, batas peringatan 10 kB) dan dependensi CommonJS Socket.IO. Tidak menghalangi build.

## Batas verifikasi dan operasional

- Docker daemon tidak berjalan ketika diperiksa. Smoke test live dengan server, MySQL, Socket.IO lintas browser, dan provider AI nyata belum dijalankan dalam audit ini. Login Google nyata, deployment, serta performa multiuser juga belum dibuktikan oleh suite lokal.
- State pertandingan aktif tersimpan di memori satu proses. Restart backend menghapus match; perbaikan frontend hanya memulihkan navigasi, bukan mengembalikan pertandingan. MySQL menyimpan arsip chat/analisis.
- Validitas keputusan AI dan fallback diuji, tetapi kualitas strategi, latensi provider nyata, dan ketahanan di bawah beban memerlukan uji live tersendiri.
- Perubahan ada di source workspace; audit ini tidak melakukan deployment.

# Frontend Vercel dari GitHub

Frontend Angular dibuild menjadi file statis. Backend Python, Socket.IO,
database, dan AI tetap dijalankan terpisah.

## Hubungkan sekali di Vercel

1. Buka https://vercel.com/new dan import `Andysaputra1/GamesSilentTerror`.
2. Pilih **Root Directory: frontend** dan **Framework Preset: Other**.
3. Gunakan Node.js **22.x**. Konfigurasi `vercel.json` menyediakan:
   - Install Command: `npm ci`
   - Build Command: `npm run build:vercel`
   - Output Directory: `dist/frontend/browser`
4. Deploy, lalu pastikan Production Branch pada pengaturan project adalah `main`.
   Push berikutnya ke `main` otomatis membuild dan memperbarui deployment produksi.

Tanpa `BACKEND_URL`, halaman frontend dapat dipublikasikan, tetapi login,
registrasi, dan game online belum berfungsi. Request API akan mendapat kegagalan
karena belum ada backend. Tidak ada server game atau database yang dibuat di Vercel.

## Setelah backend tersedia

- Isi environment variable Vercel `BACKEND_URL`, misalnya
  `https://api.example.com` (origin HTTPS saja, tanpa `/api` atau `/socket.io`).
  Pilih environment Production; Preview juga perlu nilai jika ingin diuji.
- Redeploy: nilai ini dimasukkan ke bundle saat build. Ini alamat publik,
  bukan tempat menyimpan password, token, atau API key.
- Backend harus mendukung HTTPS dan upgrade WebSocket pada `/socket.io/`.
- Tambahkan origin frontend produksi ke `CORS_ORIGINS` backend untuk HTTP
  dan Socket.IO. Preview memakai origin berbeda, sehingga perlu diizinkan
  secara eksplisit jika digunakan.
- Untuk login Google, daftarkan origin frontend pada Authorized JavaScript
  origins OAuth client. `GOOGLE_CLIENT_ID` tetap dikonfigurasi di backend.
- Jalankan backend dalam mode production; jangan publikasikan panel development,
  phpMyAdmin, atau port database. Jangan restart backend saat match berlangsung
  karena state pertandingan saat ini berada di memori backend.
- Verifikasi login, buat/join room dengan dua browser, chat realtime,
  perpindahan fase, serta reconnect setelah koneksi terputus.

## Lokal

`npm start` dan `npm run build` mempertahankan perilaku lokal/LAN: API dan
Socket.IO menggunakan hostname yang sama pada port `8000`.

`npm run build:vercel` menghasilkan `dist/frontend/browser`; konfigurasi
environment Vercel dihasilkan otomatis dan diabaikan Git.

Referensi: https://vercel.com/docs/git dan
https://vercel.com/docs/builds/configure-a-build.

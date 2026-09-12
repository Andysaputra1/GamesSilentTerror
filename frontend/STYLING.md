# Mengubah tampilan

Tema mengikuti kartu referensi lokal: kertas krem, tinta hitam, bingkai ganda,
sudut membulat, dan aksen biru/peach lembut. Referensi di communicationfolder
diabaikan Git dan tidak dijadikan aset publik.

Mulai dari **src/styles.css**, bagian DESIGN TOKENS:

| Variabel | Penggunaan |
|---|---|
| --page-padding | Jarak konten dari tepi halaman |
| --panel-padding | Padding kartu/panel |
| --layout-gap | Jarak antarkolom/panel |
| --content-width | Lebar maksimal Main dan Lobby |
| --color-bg / --color-panel | Latar halaman dan panel |
| --color-gold / --color-paper | Aksen emas dan panel krem |
| --radius-panel | Lengkungan sudut panel |

Setiap halaman memiliki HTML dan CSS terpisah di src/app/features/.
Tidak ada style inline di template Main atau Lobby.
CSS diformat multiline; bagian responsive ada di bawah file.

Di **game/game.css**, bagian GAME TOKENS menyediakan `--chat-size` untuk lebar
chat dan `--game-gap` untuk jarak kolom. Padding halaman ada di `.match-shell`,
padding panel ada di selector `.private-card, .action-panel, ...`. Warna malam
di `.match-shell.night`; pergantian warna langsung agar teks tidak kehilangan kontras.
Aturan breakpoint 950px menempatkan chat di bawah meja; 500px membuat kartu pemain
dua kolom. Perubahan file game ini tidak memengaruhi login/main page. Pada Main, 900px
mengubah menu tiga kartu menjadi satu kolom dan 760px menumpuk kartu role.
Lobby menjadi satu kolom pada 760px. Sesuaikan angka tersebut jika perlu.

Untuk mengecek perubahan, jalankan dari root repository ketika container frontend aktif:

```sh
docker compose exec -T frontend npm run build
```

Jangan edit `dist`: itu hasil build untuk deployment, bukan source tampilan.
Panduan setup, menjalankan aplikasi, dan pengujian dipusatkan di
[README utama](../README.md).

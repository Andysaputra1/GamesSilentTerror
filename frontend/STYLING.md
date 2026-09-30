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

Font Fraunces (judul) dan Patrick Hand (tulisan tangan) disimpan sendiri di
`public/assets/fonts` (lisensi OFL di folder yang sama) dan didaftarkan lewat `@font-face`
di awal **src/styles.css**, sehingga tampil tanpa internet atau layanan pihak ketiga.

Setiap halaman memiliki HTML dan CSS terpisah di src/app/features/.
Khusus auth sekarang memakai `auth.html` dan `auth.scss` dari desain Kimberly:
meja kayu, kertas register, dan binder login. Asetnya di `public/assets/`.
Ubah `--em`, padding `.register-sheet`/`.login-journal`, dan breakpoint 899px
untuk proporsi desktop/mobile. Google memakai tombol resmi GIS. Jangan mengedit
file `auth_kim.*` atau CSS lama karena sudah digantikan.
Tidak ada style inline di template Main atau Lobby.
CSS diformat multiline; bagian responsive ada di bawah file.

Halaman **game** memakai bahasa visual login (meja kayu, kertas 9-slice
`register-paper.png`, papan `btn-wood.png`, tombol kayu/kulit, font Fraunces dan
Patrick Hand) dan selalu satu layar (100dvh) tanpa scroll halaman; hanya isi panel
yang bergulir. Gayanya dibagi lima berkas karena batas 12 kB per stylesheet komponen:
`game.css` (token `--pad`/`--game-gap`, kertas, papan, tombol, HUD, panel kiri, kartu role),
`game-table.css` (papan tersangka, kartu pemain, efek vote, baki aksi, chat, tab HP),
`game-screens.css` (transisi fase, layar persiapan `.splash`), `game-end.css` (pengumuman
pemenang `.end-stage`, kuesioner `.survey`, modal aturan), dan `game-motion.css` (animasi,
responsif, `prefers-reduced-motion`). Panas vote diatur `--heat` (0–1) per kartu; jumlah kolom
meja dipilih `Game.tableColumns` dari ukuran papan. Karakter dan warna label pemain mengikuti
urutan kursi, bukan role. Komposisi role room (`snapshot.composition`) tampil sebagai chip
`.composition`/`.comp-chip` (gaya dasar di `game-screens.css`) di layar persiapan dan di tepi atas
papan (`.felt-composition`, ruangnya dipesan lewat padding `.table-felt.has-composition`; di HP tanpa
ikon). Di room multi-Hitman chip Hitman di tepi meja menampilkan "tersisa/total" dari
`snapshot.hitman_remaining` dan diberi kelas `.comp-chip.reduced` (merah) setelah ada Hitman yang
tereksekusi; pembaca layar mendapat teks `.sr-only` "Hitman tersisa x dari n". Penanda rekan Syndicate
hanya dirender untuk Hitman: `.ally-tag` di kartu rekan dan `.ally-pick` ("◆ Incaran") di kartu yang
dipilih rekan saat malam (keduanya di `game-screens.css` karena budget `game-table.css` hampir penuh),
serta `.ally-plan` di baki aksi (`game-table.css`).
Breakpoint 1099px: meja + chat dengan tab Meja/Kartu; 759px: satu panel
per tab (Meja/Chat/Kartu). Perubahan file game ini tidak memengaruhi login/main page. Pada Main, 900px
mengubah menu tiga kartu menjadi satu kolom dan 760px menumpuk kartu role.
Lobby menjadi satu kolom pada 760px. Sesuaikan angka tersebut jika perlu.

Untuk mengecek perubahan, jalankan dari root repository ketika container frontend aktif:

```sh
docker compose exec -T frontend npm run build
```

Jangan edit `dist`: itu hasil build untuk deployment, bukan source tampilan.
Panduan setup, menjalankan aplikasi, dan pengujian dipusatkan di
[README utama](../README.md).

# Konsep game — Silent Terror (judul sementara)

## Zero economy

Tidak ada budget, pembelian item, atau tebusan. Hitman menyusup dan menyandera warga secara diam-diam; warga mencari Hitman melalui observasi percakapan.

## Role

| Role | Tujuan dan kemampuan |
| --- | --- |
| Hitman | Menyandera semua warga. Malam: Hostage satu korban. Siang: Gag Order membungkam satu pemain, cooldown satu ronde. |
| Spy | Melindungi warga. Malam: Guard satu pemain; Hostage terhadap target itu gagal. Tidak boleh memilih target sama dua malam berturut-turut. |
| Stalker | Mencari informasi. Malam: Peek identitas asli satu pemain, sekali setiap dua ronde. |
| Civilian | Tidak punya skill malam. Berdebat, mengamati, dan menebak Hitman. |

## Alur ronde

Day (diskusi; Hitman dapat Gag Order) → Night (chat terkunci; aksi serentak dan tersembunyi) → Tribunal (rekap malam tanpa nama target; voting; suara terbanyak dieksekusi) → ronde berikutnya.

## Kubu, status, dan kemenangan

- **Kubu Hitman:** tepat satu pemain. Bot juga bisa mendapat role ini.
- **Kubu warga:** Spy, Stalker, dan semua Civilian, baik manusia maupun bot. Kemenangan mengikuti kubu, bukan jumlah manusia yang masih hidup.
- **Hidup (`alive`):** belum dieksekusi. Hostage tetap hidup dan tetap berada di roster.
- **Hostage:** permanen sampai game berakhir; tidak dapat chat, voting, atau aksi malam. Korban tetap anggota kubu warga dan tetap menang jika Hitman dieksekusi.
- **Gag Order:** hanya mengunci chat/voting sampai akhir Tribunal ronde itu. Aksi malam tetap tersedia. Gag tidak dihitung sebagai Hostage untuk kemenangan.
- **Dieksekusi:** tidak lagi hidup dan hanya menonton. Hasil pemain tetap mengikuti kubunya.

Backend memeriksa kemenangan setelah resolusi malam dan setelah eksekusi Tribunal, dengan urutan berikut:

1. Hitman dieksekusi → **seluruh kubu warga menang**, termasuk yang Hostage atau sudah dieksekusi.
2. Hitman hidup dan tidak ada warga hidup tersisa → **Hitman menang** karena semua lawan telah dieksekusi.
3. Hitman hidup dan seluruh warga yang masih hidup sudah Hostage → **Hitman menang**. Warga yang dieksekusi tidak perlu disandera.
4. Selain itu permainan berlanjut. Setelah Tribunal ronde 8, jika belum ada kemenangan normal → **seri**.

Tidak ada kemenangan otomatis karena jumlah Hitman dan warga seimbang, karena semua manusia gugur, atau karena semua lawan sedang Gag. Satu warga hidup yang belum Hostage masih mencegah kemenangan Hitman. Guard yang berhasil melindungi warga terakhir juga mencegah kemenangan malam itu.

Contoh: Spy dieksekusi, Stalker menjadi Hostage, Civilian masih bebas → pertandingan lanjut. Jika Civilian kemudian menjadi Hostage, Hitman menang. Jika Hitman justru dieksekusi di Tribunal, Spy, Stalker, dan Civilian semuanya menang.

Selama game, hanya status milik sendiri yang dijelaskan secara privat; roster lawan tidak membocorkan Hostage/Gag. Setelah selesai, layar hasil menjelaskan kubu pemenang, menang/kalah/seri untuk akun sendiri, alasan akhir, jumlah warga hidup/disandera/dieksekusi, serta role dan status akhir setiap pemain.

## Alur ruangan

Satu akun menempati satu ruangan. Buat/gabung → tunggu 4–6 peserta → host mulai → diskusi/malam/voting → hasil → keluar ruangan sebelum membuat atau bergabung lagi. Keanggotaan lobby dan ruangan selesai dipulihkan dari server melalui `GET /api/rooms/current`, termasuk setelah logout atau tab baru. Logout mengakhiri sesi akun, bukan meninggalkan atau menghentikan pertandingan. Login ulang memulihkan pertandingan aktif. Keluar sebelum mulai memindahkan host ke anggota berikutnya; ruangan tanpa anggota dibersihkan.

## Silent terror

Korban Hostage tidak mati, tetapi kehilangan kemampuan chat dan hak voting. Sistem tidak pernah mengumumkan siapa yang disandera. Diam dapat berarti Hostage, Gag Order, atau pilihan pemain sendiri. Rekap dan roster publik tidak boleh membocorkan status tersebut.

## Status implementasi

Sudah aktif: pembagian role server, timer, resolusi malam, cooldown, Hostage/Gag, voting, eksekusi, kemenangan, dan bot dengan aksi/vote. Login dan main page tidak diubah. Lobby/game membaca state dari backend; keputusan tidak dilakukan di frontend.

## Aturan operasional

- Peserta 4–6; tepat 1 Hitman, 1 Spy, 1 Stalker, sisanya Civilian. Semua termasuk bot mendapat role acak.
- Bot mengisi hingga minimal 4 peserta; dengan 4–5 manusia, opsi bot menambah satu bot. Roster terkunci setelah mulai. Anggota lama boleh reconnect, orang baru tidak boleh masuk.
- Durasi standar: Day 120s, Night 30s, Tribunal 45s. Mode cepat: 20/15/15s. Timer server terus berjalan walaupun browser ditutup.
- Skip diskusi hanya pada Day: semua manusia yang masih hidup harus setuju. Bot dan pemain mati tidak dihitung. Gag/Hostage tidak menghapus hak persetujuan ini (bukan chat/vote), supaya status rahasia tidak bocor lewat jumlah yang diperlukan. Persetujuan final per ronde, duplikat tidak menambah hitungan, reset saat ronde baru. Pemain offline tetap diperlukan; jika belum lengkap, timer normal berlaku. Persetujuan lengkap memajukan fase melalui engine yang sama dengan timer, termasuk kesempatan aksi siang bot.
- Satu akun hanya boleh mengikuti satu pertandingan aktif. Endpoint privat `GET /api/rooms/active` memulihkan room pada tab baru/login ulang. Route aplikasi dan pengecekan berkala/focus mengarahkan pemain ke `/game` selama match aktif. Tidak memaksa navigasi tab situs eksternal. Pemain mati tetap kembali sebagai penonton sampai pertandingan selesai.
- Gag aktif segera saat Day sampai Tribunal ronde itu selesai, lalu hilang pada Day berikutnya. Pemain terkena Gag tidak dapat chat/vote, tetapi masih bisa aksi malam. Dipakai ronde 1 → tersedia lagi ronde 3.
- Peek dipakai ronde 1 → tersedia lagi ronde 3. Hasil baru muncul setelah resolusi malam dan hanya untuk Stalker tersebut.
- Guard boleh memilih diri sendiri, tetapi tidak target yang sama pada dua malam berturut-turut. Guard diproses sebelum Hostage, terlepas urutan request.
- Hostage permanen sampai akhir game. Korban tetap hidup namun tidak dapat chat/vote/aksi malam. Ini asumsi implementasi untuk pemain yang sedang disandera.
- Setiap aksi malam dan vote hanya satu pilihan final. Boleh tidak memilih sebelum timer habis. Target harus hidup; hanya Guard boleh memilih diri sendiri.
- Suara terbanyak tunggal dieksekusi. Seri atau tanpa suara: tidak ada eksekusi.
- Warga menang jika Hitman dieksekusi. Hitman menang jika semua warga yang masih hidup sudah Hostage.
- Tidak ada pengumuman target Hostage, status bungkam publik, atau aksi malam orang lain dalam snapshot aktif. Selama Tribunal, vote yang sudah dikirim bersifat publik: jumlah dan nama pemilih per target, tanpa daftar siapa yang berhak voting. Tampilan maksimal 4 badge nama lalu +N dan daftar lengkap yang bisa dibuka. Role dan status Hostage dibuka untuk semua setelah game selesai. Status Hostage/Gag sendiri tersedia privat; hasil Peek tetap privat.
- Bot memilih target dari pemain hidup, tanpa membaca role/status rahasia lawan. Stalker bot boleh memakai hasil Peek miliknya sendiri saat voting. Aksi bot dijalankan di pertengahan fase.
- Bot chat menjawab pesan manusia yang diterima, bukan percakapan otomatis antarsesama bot. LLM tidak menentukan hasil aksi/vote. Bot bungkam/mati tidak boleh membalas; balasan yang terlambat melewati fase dibuang. Kegagalan LLM tidak menghentikan timer.

## Alur kode

```text
Lobby → POST /api/rooms /join /{code}/bot /{code}/start
                       ↓
controller/api/rooms.py → services/room_service.py (membership + lock)
                       ↓
services/match_engine.py (role, timer, aksi, vote, winner, snapshot privat)
                       ↓
GET /api/rooms/{code}/game → frontend/core/game.service.ts → game.ts/html/css

Tombol aksi/vote → POST /api/rooms/{code}/play
  → validasi match_id + round_number + phase → validasi aturan → snapshot baru

send_chat → realtime/socket_handlers.py → engine.can_chat
  → echo server → SVM → fuzzy → LLM sesuai role bot → MySQL → receive_chat
```

`main.py` menjalankan clock 0,5 detik. Frontend polling snapshot tiap 1 detik dan memakai Socket.IO untuk chat. Header bearer mengikat HTTP ke akun; Socket.IO memeriksa token dan membership. Username pada payload tidak dapat menyamar sebagai pemain lain. `/games/checker` tetap route development tanpa login, tetapi data room aktif ditolak HTTP 403 untuk melindungi Silent Terror.

Persetujuan skip: `POST /api/rooms/{code}/skip-discussion` → `RoomService.skip()` → `Match.skip_discussion()`. Payload membawa `match_id`, `round_number`, dan `phase: day`; permintaan fase lama ditolak. Pemulihan UI ada di `core/active-match.service.ts` (guard + lookup), dan `app.ts` mengecek setiap 3 detik ketika berada di halaman lain serta saat tab kembali aktif. Identitas persetujuan orang lain tidak dipublikasikan; snapshot hanya membawa total dan persetujuan akun sendiri.

## Batas versi development

Ruangan/role/aksi/vote disimpan di memori satu proses backend dan hilang ketika backend restart. Reload browser memulihkan pertandingan yang masih ada serta 100 pesan terakhir. MySQL mencatat chat/analisis, bukan snapshot pertandingan; pemulihan match setelah restart dan multi-worker belum tersedia. Pemain yang menutup tab tetap di roster dan melewatkan aksi/vote sampai kembali; belum ada bot pengganti otomatis.

Fuzzy masih memakai persentase diam tetap 20%, bukan pengukuran aktivitas nyata. Akurasi/balance SVM-fuzzy-LLM bukan jaminan hasil game. Aplikasi, checker, akun demo dan Compose ditujukan untuk pengembangan lokal, bukan deployment publik.

- Batas pertandingan 8 ronde. Setelah Tribunal ronde 8, kemenangan normal diprioritaskan; jika belum ada pemenang, hasil seri dan semua role dibuka.
- Permintaan AI pertama per fase diskusi/voting menyediakan sedikitnya 35 detik sejak permintaan diterima. Tambahan maksimal 35 detik per fase, tidak berulang untuk pesan berikutnya. Skip manual tetap berlaku.

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

## Silent terror

Korban Hostage tidak mati, tetapi kehilangan kemampuan chat dan hak voting. Sistem tidak pernah mengumumkan siapa yang disandera. Diam dapat berarti Hostage, Gag Order, atau pilihan pemain sendiri. Rekap dan roster publik tidak boleh membocorkan status tersebut.

## Status implementasi

Sudah tersedia: login, main page, buat/gabung kode ruangan, roster, bot opsional yang hanya dapat diatur pembuat ruangan, chat terisolasi per ruangan, dan respons NOX melalui backend.

Belum tersedia: pembagian role otoritatif dari server, timer fase, resolusi aksi malam, cooldown, efek Hostage/Gag, voting, eksekusi, serta kondisi akhir permainan. Kartu acak pada halaman game hanya pratinjau role warga untuk latihan chat dengan NOX.

Ruangan saat ini disimpan di memori satu proses backend dan hilang ketika backend restart. Riwayat chat disimpan di MySQL per kode ruangan; belum ada pemulihan lobby atau pemutaran ulang chat.

Sebelum implementasi engine, perlu ditetapkan: durasi fase/Gag Order, hasil voting seri, kondisi kemenangan warga, dan apakah korban Gag masih boleh voting saat Tribunal.

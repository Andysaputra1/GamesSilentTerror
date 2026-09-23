# Silent Terror — aturan permainan sesuai GDD

Silent Terror adalah multiplayer social deduction berbasis web, dengan hidden role asimetris dan NPC yang memakai LLM. Fokus permainan adalah deduksi dari percakapan, alibi, dan voting. Tidak ada ekonomi, pembelian item, atau tebusan.

Tambahan atas GDD awal: mode kecil 4/5 pemain dan durasi fase mengikuti jumlah peserta, sesuai permintaan terbaru.

## Ruangan dan role

- **4–10 peserta**, kombinasi manusia dan NPC. Host memilih kapasitas room; permainan dapat dimulai dengan sedikitnya empat peserta.
- **Batas 6, 8, atau 12 ronde**, dipilih saat membuat room. Kemenangan dapat terjadi lebih cepat.
- Tepat satu Hitman, satu Spy, satu Stalker, sisanya Civilian. Role diacak server untuk manusia maupun NPC.
- NPC mengisi kursi kosong sampai kapasitas. Manusia yang bergabung sebelum mulai menggantikan kursi NPC. Roster terkunci setelah mulai; anggota lama dapat reconnect.
- Satu akun menempati satu room. Keluar dari lobby/hasil sebelum pindah room. Logout mencabut sesi tanpa menghentikan pertandingan; login ulang memulihkan keanggotaan.

## Fase setiap ronde

| Fase | Interaksi dan resolusi |
| --- | --- |
| Siang | Diskusi publik. Hitman dapat menggunakan Gag Order secara instan. |
| Malam | Layar meredup, chat terkunci. Hostage, Guard, dan Peek dipilih privat, diselesaikan bersama saat timer habis. Guard diproses sebelum Hostage. |
| Tribunal | Rekap tanpa nama target atau hasil individual. Pemain yang punya hak suara memilih tersangka. Suara terbanyak tunggal dieksekusi. |

Durasi ditetapkan dari jumlah peserta awal N (manusia + NPC), tetap selama pertandingan. Standar: siang 20N detik, malam 5N detik, Tribunal dibulatkan ke atas dari 7,5N detik. Mode cepat: siang dibulatkan ke atas dari 10N/3 detik, malam dan Tribunal masing-masing dari 2,5N detik. Contoh standar: 4 pemain 80/20/30 detik; 6 pemain 120/30/45; 10 pemain 200/50/75. Timer server tetap berjalan walaupun tab ditutup. Chat kembali tersedia saat Tribunal bagi pemain yang masih boleh berbicara.

Semua manusia hidup dapat menyetujui skip siang. Hostage/Gag tetap boleh menyetujui karena ini bukan chat atau voting Tribunal. Hanya jumlah persetujuan dipublikasikan; jika belum lengkap, timer normal berlaku.

## Kemampuan dan status

| Role | Faksi | Kemampuan |
| --- | --- | --- |
| Hitman | Syndicate | Hostage satu pemain saat malam. Gag Order satu pemain saat siang, cooldown satu ronde penuh: ronde 1 lalu ronde 3. |
| Spy | Warga | Guard satu pemain, termasuk diri sendiri. Tidak boleh target sama dua malam berturut-turut. Guard mencegah serangan malam itu, tidak membebaskan Hostage lama. |
| Stalker | Warga | Peek role asli satu pemain setelah malam selesai. Hasil privat; sekali setiap dua ronde: ronde 1 lalu ronde 3. |
| Civilian | Warga | Tidak punya skill malam; mengamati, berdebat, dan voting. |

**Hostage:** tetap hidup di roster, kehilangan chat dan voting permanen. Sesuai pembatasan tertulis di GDD, skill malam tetap tersedia mengikuti role/cooldown. Korban tetap faksi warga.

**Gag Order:** hanya membatasi chat sampai akhir ronde penggunaan. Voting dan skill malam tetap tersedia. Gag tidak mengurangi suara warga dalam kondisi kemenangan.

**Dieksekusi:** tidak bisa chat, aksi, atau voting; menjadi penonton. Menang/kalah mengikuti faksi, termasuk bagi yang dieksekusi atau Hostage.

Aksi malam dan vote final, satu pilihan per fase. Target harus hidup; hanya Guard boleh memilih diri sendiri. Memilih pemain yang sudah Hostage diperbolehkan karena status lawan rahasia, tetapi tidak menambah korban baru.

## Kemenangan

Backend mengecek setelah resolusi malam dan Tribunal:

1. **Warga menang** jika Hitman dieksekusi.
2. **Hitman menang**, selama masih hidup, saat warga hidup yang tidak Hostage **paling banyak satu**. Suara warga tidak lagi melampaui satu suara Hitman. Warga dieksekusi/Hostage tidak dihitung; Gag tetap dihitung.
3. Tanpa pemenang setelah Tribunal pada batas ronde pilihan host: **seri**.

Contoh enam pemain: tiga dari lima warga Hostage, dua bebas → lanjut. Satu lagi disandera atau dieksekusi → Hitman menang. Guard berhasil sehingga dua warga tetap bebas → lanjut. Hitman dieksekusi pada Tribunal terakhir → kemenangan warga diprioritaskan atas seri.

Ketentuan pelengkap untuk bagian GDD yang belum merinci: vote seri/tanpa suara tidak mengeksekusi siapa pun; batas ronde tanpa kemenangan menghasilkan seri; role korban eksekusi dirahasiakan sampai akhir.

Hasil akhir menunjukkan faksi pemenang, alasan, menang/kalah/seri akun sendiri, jumlah warga hidup/Hostage/dieksekusi/masih punya suara, serta role dan status akhir semua peserta.

## Blind information

Snapshot aktif hanya memuat role, status, pilihan aksi, dan hasil Peek milik akun peminta. Roster lawan hanya berisi nama dan hidup/tidak. Tidak ada pengumuman target Hostage, Gag, Guard, atau Peek. Rekap malam sama untuk serangan berhasil, gagal, atau tanpa serangan.

Vote yang dikirim terlihat saat Tribunal, termasuk nama pemilih per target, tanpa daftar orang yang berhak voting. Diam bisa berarti strategi, Gag, Hostage, atau offline.

Label NPC tidak ditampilkan di roster pertandingan aktif. Lobby masih menampilkan kursi/konfigurasi NPC, sehingga versi ini **belum menjadi protokol eksperimen Turing Test tersamar penuh**. Eksperimen tersamar memerlukan penyamaran identitas lobby, prosedur rekrutmen, serta evaluasi tersendiri.

## NPC dan single LLM

`services/npc_service.py` menjalankan NPC dari timer tanpa menunggu pesan manusia. Setiap NPC mendapat satu giliran per fase relevan, memakai provider/model terpilih yang sama dari panel, dengan konteks privat terpisah.

Prompt terstruktur berisi aturan, role/status sendiri, intel sendiri, aksi/target legal, chat publik terakhir, event dan vote publik. Role/status/aksi rahasia lawan tidak masuk prompt. Chat pemain diperlakukan sebagai data tidak tepercaya, bukan instruksi sistem. Request antrean memperbarui konteks sebelum memanggil model agar melihat percakapan terbaru.

Model mengembalikan JSON `action`, `target`, `message`. Server memvalidasi JSON, room/match, ronde/fase, deadline, hak chat, dan legalitas aksi. Model memilih strategi; engine menentukan hasil. Balasan basi dibuang. Pesan disimpan sebelum disiarkan Socket.IO. Keputusan `wait` yang valid dihormati.

Maksimal tiga request NPC bersamaan; timeout dibatasi deadline fase. Jika model/jaringan gagal atau keputusan ilegal, engine mengisi aksi/vote kosong dengan fallback aturan pada deadline, tanpa mengarang percakapan. Fallback hanya memakai roster publik dan intel sendiri. Trace menandai kegagalan; **fallback harus dibedakan dari hasil keputusan LLM dalam analisis penelitian**. Mode cepat lebih mudah mengalami timeout.

SVM/fuzzy tetap menganalisis pesan manusia untuk arsip/checker. Jalur NPC memakai konteks di atas; tidak mengklaim skor fuzzy sebagai pengetahuan role. Persentase diam pada pipeline lama masih tetap 20%, bukan pengukuran aktivitas nyata. Kualitas taktik, deception, dan keberhasilan menyamar memerlukan uji model nyata serta evaluasi manusia.

## Alur kode

```text
Lobby -> POST /api/rooms {capacity, max_rounds} -> RoomService
Host mulai -> Match (role acak, timer, snapshot privat)
Timer 0,5 detik -> resolusi fase + NPCService.schedule
NPC -> prompt privat -> single LLM -> JSON tervalidasi -> Match.act/vote
Human -> HTTP /play -> validasi token fase + aturan -> Match.act/vote
Human chat -> Socket.IO -> otorisasi + can_chat -> analisis + MySQL -> echo
NPC chat -> can_chat + MySQL -> Socket.IO receive_chat
GET /game -> snapshot akun -> Angular (polling 1 detik)
```

RoomService mengunci perubahan state. HTTP memakai bearer session; Socket.IO memeriksa sesi dan keanggotaan. Checker publik lama ditutup; trace/prompt privat hanya untuk administrator panel.

## Batas operasional dan validasi

Room, role, aksi, vote, dan konteks pertandingan berada di memori satu proses. Restart menghapus pertandingan aktif; MySQL menyimpan chat/analisis, bukan pemulihan seluruh match. Multi-worker dan penggantian pemain offline otomatis belum tersedia.

Tes otomatis mencakup 4–10 pemain, 6/8/12 ronde, Guard/Peek/Gag/Hostage, dominasi suara, prioritas kemenangan, privasi, voting, reconnect, serta scheduler/validasi/fallback NPC dengan respons model tiruan. Tes ini tidak membuktikan kualitas taktik atau latensi provider produksi.

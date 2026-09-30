# Silent Terror — aturan permainan sesuai GDD

Silent Terror adalah multiplayer social deduction berbasis web, dengan hidden role asimetris dan NPC yang memakai LLM. Fokus permainan adalah deduksi dari percakapan, alibi, dan voting. Tidak ada ekonomi, pembelian item, atau tebusan.

Tambahan atas GDD awal: mode kecil 4/5 pemain dan durasi fase mengikuti jumlah peserta, sesuai permintaan terbaru.

## Ruangan dan role

- **4–10 peserta**, kombinasi manusia dan NPC. Host memilih kapasitas room; permainan dapat dimulai dengan sedikitnya empat peserta.
- **Tanpa batas ronde**. Host hanya memilih kapasitas; permainan berlanjut sampai salah satu kubu menang.
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

Tidak ada hasil seri pertandingan. Jika kedua kondisi kemenangan belum terpenuhi, lanjutkan ke ronde berikutnya.

Contoh enam pemain: tiga dari lima warga Hostage, dua bebas → lanjut. Satu lagi disandera atau dieksekusi → Hitman menang. Guard berhasil sehingga dua warga tetap bebas → lanjut. Hitman dieksekusi pada Tribunal ronde berapa pun → warga menang dan permainan selesai.

Ketentuan pelengkap untuk bagian GDD yang belum merinci: vote seri/tanpa suara tidak mengeksekusi siapa pun dan permainan dilanjutkan jika belum ada pemenang; role korban eksekusi dirahasiakan sampai akhir.

Hasil akhir menunjukkan faksi pemenang, alasan, menang/kalah akun sendiri, jumlah warga hidup/Hostage/dieksekusi/masih punya suara, serta role dan status akhir semua peserta.

## Blind information

Snapshot aktif hanya memuat role, status, pilihan aksi, dan hasil Peek milik akun peminta. Roster lawan hanya berisi nama dan hidup/tidak. Tidak ada pengumuman target Hostage, Gag, Guard, atau Peek. Rekap malam sama untuk serangan berhasil, gagal, atau tanpa serangan.

Vote yang dikirim terlihat saat Tribunal, termasuk nama pemilih per target, tanpa daftar orang yang berhak voting. Diam bisa berarti strategi, Gag, Hostage, atau offline.

Label NPC tidak ditampilkan di roster pertandingan aktif. Lobby masih menampilkan kursi/konfigurasi NPC, sehingga versi ini **belum menjadi protokol eksperimen Turing Test tersamar penuh**. Eksperimen tersamar memerlukan penyamaran identitas lobby, prosedur rekrutmen, serta evaluasi tersendiri.

## Persiapan pertandingan

Setelah host menekan Mulai, semua peserta masuk ke **layar persiapan** berisi panduan singkat (tujuan, siang, malam, Tribunal, bot AI, tips) dan progres pemuatan AI. Ronde 1 **belum berjalan** selama persiapan. Ronde 1 dimulai ketika otak bot siap **dan** (waktu baca minimal 8 detik lewat **atau** semua manusia menekan "Siap"). Jika AI gagal atau belum siap dalam 90 detik, permainan tetap dimulai dengan aksi cadangan engine. Room tanpa bot langsung siap; pemain tetap bisa membaca panduan atau menekan Siap.

## NPC: otak dari notebook skripsi

`services/npc_service.py` menjalankan NPC dari timer tanpa menunggu pesan manusia. Setiap bot punya **ingatan, metode, dan persona sendiri** (multi-bot aman; ingatan tidak dibagi). Logikanya adalah kode notebook skripsi yang diekspor apa adanya ke `services/npc_brain/generated/` oleh `scripts/ekspor_otak_npc.py`:

1. **NLU IndoBERT** (satu model untuk semua bot): intent (offend/defend/neutral) dan target per pemain untuk setiap chat publik. Karena nama pengguna bebas (mis. `tester`, `andy123`), nama pemain diganti nama yang dikenal model sebelum intent dibaca; tanpa itu tuduhan singkat seperti "curiga sama tester" terbaca netral. Hasil anotasi disimpan sekali karena identik untuk semua bot. Tanpa folder model, dipakai NLU cadangan (SVM lama + nama yang disebut) dan hal itu dicatat di trace.
2. **Penalaran**: bukti publik per pemain → Fuzzy Mamdani, Utility AI, atau Behavior Tree → rencana chat, vote, dan aksi rahasia (Gag, Hostage, Guard, Peek). `NPC_METHOD=campuran` membagi bot dalam satu room bergiliran ke tiga metode (urutan diacak per pertandingan); metode dan persona tiap bot dicatat di tabel `match_bots` untuk analisis survei.
3. **NLG**: rencana → kalimat. Penulis Claude (opsional, `ANTHROPIC_API_KEY` atau `AMAZON_API_KEY`) tidak menerima role asli bot; setiap kalimat diperiksa aturan (tidak mengaku bot/AI, tidak membocorkan role/aksi, target disebut) dan dibaca ulang IndoBERT. Gagal/tanpa key → templat bervariasi sesuai persona.

Bot mengambil langkah setiap `NPC_STEP_SECONDS` (bawaan 3 detik), digeser beberapa detik per bot. Vote dan aksi rahasia diterapkan begitu diputuskan, sedangkan kalimat melewati **lantai bicara**: dalam satu pertandingan hanya satu bot yang menyusun dan "mengetik" pada satu waktu. Rencana chat yang dibuat sebelum chat bot lain masuk dibatalkan, lalu bot memutuskan ulang dengan chat terbaru. Chat manusia tidak pernah ditahan. Di notebook, bot tidak ikut bertanya bila pemain lain baru saja bertanya, dan tidak menjadi suara ketiga yang mengulang tuduhan atau pembelaan yang sama di fase itu (anti-gema). Kalimat yang baru muncul di room juga tidak diulang bot lain. Hasilnya, bot tidak bertanya serentak dan tidak saling mengembari. Bot tidak menunggu manusia bicara: satu bot membuka diskusi, dan jika ruangan hening (tidak ada chat selama ≥ max(15 detik, 20% durasi fase), sekitar 24 detik di siang standar) bot boleh memancing percakapan lagi atau mengajak pemain yang belum bicara. Bot tetap tidak menuduh tanpa bukti. Keputusan diterapkan hanya jika ronde/fase belum berganti; aksi yang ditolak engine tidak mengubah state. Begitu otak memegang fase tertentu, "tunggu"/abstain miliknya dihormati; fallback acak engine hanya untuk bot yang otaknya gagal.

Kebijakan vote saat bukti lemah berbeda per metode (`PAKSA_VOTE_BUKTI_LEMAH`, dipilih lewat uji A/B melawan engine): bot Behavior Tree tetap memberi suara ke tersangka teratas di paruh akhir Tribunal, sedangkan bot Fuzzy dan Utility AI abstain bila belum yakin. Abstain membuat pemilih tunggal yang mengeksekusi warga (sering Hitman) mudah dicurigai pada ronde berikutnya.

Mode `NPC_METHOD=llm` mempertahankan cara lama (satu prompt LLM memutuskan aksi dan pesan) sebagai pembanding penelitian.

Label NPC tidak ditampilkan di roster pertandingan aktif. Lobby dan layar persiapan tetap menyebut jumlah bot, sehingga versi ini **belum menjadi protokol eksperimen Turing Test tersamar penuh**.

## Akhir pertandingan dan survei

Layar hasil menampilkan ucapan selamat (untuk pemenang pribadi atau kubu pemenang), daftar pemenang beserta role, dan statistik akhir. Di bawahnya ada **survei**: pertanyaan, jenis jawaban (bintang, skala angka, pilihan ganda, teks), rentang skala, dan arti nilai terkecil/terbesar diatur administrator di panel (menu **Survei**), bukan di frontend. Setiap akun manusia mengirim survei sekali per pertandingan; jawaban menyimpan salinan pertanyaan saat dijawab beserta role/kubu/hasil pemain. Panel menampilkan rata-rata per pertanyaan dan per metode bot, serta ekspor CSV.

## Alur kode

```text
Lobby -> POST /api/rooms {capacity} -> RoomService
Host mulai -> Match (role acak, timer, snapshot privat)
Timer 0,5 detik -> resolusi fase + NPCService.schedule
Host mulai -> layar persiapan -> otak NPC siap -> ronde 1
NPC -> snapshot privat -> IndoBERT -> fuzzy/utility/BT -> NLG tervalidasi -> Match.act/vote
Human -> HTTP /play -> validasi token fase + aturan -> Match.act/vote
Human chat -> Socket.IO -> otorisasi + can_chat -> analisis + MySQL -> echo
NPC chat -> can_chat + MySQL -> Socket.IO receive_chat
GET /game -> snapshot akun -> Angular (polling 1 detik)
```

RoomService mengunci perubahan state. HTTP memakai bearer session; Socket.IO memeriksa sesi dan keanggotaan. Checker publik lama ditutup; trace/prompt privat hanya untuk administrator panel.

Chat manusia diperiksa ulang setelah analisis, lalu disimpan bersama pembaruan riwayat di dalam lock agar perubahan fase/Gag tidak diterobos. Balasan reaktif dari lobby dibuang jika room atau pertandingan sudah berubah. Sebelum broadcast chat manusia maupun NPC, socket penerima yang sudah keluar room atau sesinya dicabut dikeluarkan dari kanal. Frontend mempertahankan echo chat baru yang tiba ketika polling masih berjalan, tanpa duplikasi dan dengan batas 100 pesan.

## Batas operasional dan validasi

Room, role, aksi, vote, dan konteks pertandingan berada di memori satu proses. Restart menghapus pertandingan aktif; MySQL menyimpan chat/analisis, bukan pemulihan seluruh match. Multi-worker dan penggantian pemain offline otomatis belum tersedia.

Tes otomatis mencakup 4–10 pemain, permainan tanpa pemenang melewati ronde 25, Guard/Peek/Gag/Hostage, dominasi suara, prioritas kemenangan, privasi, voting, reconnect, scheduler/validasi/fallback NPC mode LLM dengan respons model tiruan, layar persiapan, survei, serta pertandingan multi-bot penuh memakai otak hasil notebook melawan engine asli. Tes ini tidak membuktikan kualitas taktik atau latensi provider produksi.

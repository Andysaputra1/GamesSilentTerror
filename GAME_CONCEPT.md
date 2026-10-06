# Silent Terror — aturan permainan sesuai GDD

Silent Terror adalah multiplayer social deduction berbasis web, dengan hidden role asimetris dan NPC yang memakai LLM. Fokus permainan adalah deduksi dari percakapan, alibi, dan voting. Tidak ada ekonomi, pembelian item, atau tebusan.

Tambahan atas GDD awal: mode kecil 4/5 pemain dan durasi fase mengikuti jumlah peserta, sesuai permintaan terbaru.

## Ruangan dan role

- **4–10 peserta**, kombinasi manusia dan NPC. Host memilih kapasitas room; permainan dapat dimulai dengan sedikitnya empat peserta.
- **Tanpa batas ronde**. Host hanya memilih kapasitas; permainan berlanjut sampai salah satu kubu menang.
- Komposisi role mengikuti jumlah peserta (`KOMPOSISI_PERAN` di `match_engine.py`); Hitman dan Spy bisa lebih dari satu, Stalker selalu satu, sisanya Civilian. Role diacak server untuk manusia maupun NPC. Jumlah tiap role diketahui semua pemain (`composition` di snapshot); siapa pemegangnya tetap rahasia.

| Peserta | Hitman | Spy | Stalker | Civilian | Warga menang (simulasi bot, 2 / 6 langkah per fase) |
| --- | --- | --- | --- | --- | --- |
| 4 | 1 | 1 | 1 | 1 | 43,0% ± 6,9 / — |
| 5 | 1 | 1 | 1 | 2 | 46,5% ± 6,9 / — |
| 6 | 1 | 1 | 1 | 3 | 56,5% ± 6,9 / — |
| 7 | 1 | 1 | 1 | 4 | 73,0% ± 6,2 / 71,0% ± 6,3 |
| 8 | 2 | 2 | 1 | 3 | 47,0% ± 6,9 / 53,5% ± 6,9 |
| 9 | 2 | 2 | 1 | 4 | 54,0% ± 6,9 / 52,0% ± 6,9 |
| 10 | 2 | 2 | 1 | 5 | 57,0% ± 6,9 / 64,5% ± 6,6 |

Cara memilih: 200 pertandingan per sel, semua kursi bot otak notebook (metode campuran seperti `NPC_METHOD=campuran`) melawan engine ini, label NLU sempurna, dengan pengumuman jumlah Hitman tersisa (lihat Kemenangan). Aturan: jika ada komposisi dengan ≥ 2 Hitman yang win rate warganya 40–60%, dipilih yang paling dekat 50%; jika tidak ada, ukuran itu tetap satu Hitman. Jumlah Hitman dan Spy tidak boleh turun saat peserta bertambah; 4–6 pemain tetap satu Hitman. Pembanding yang ditolak: di 7 pemain dua Hitman + satu Spy 26,0% dan dua Hitman + dua Spy 37,5% (keduanya di bawah 40%, jadi tetap satu Hitman); dua Hitman + satu Spy di 8 dan 9 pemain 37,5% dan 39,0%; tiga Hitman di 9 dan 10 pemain 4–16%; di 10 pemain dua Hitman + satu Spy 46,5% lebih dekat 50%, tetapi Spy tidak boleh turun dari dua (9 pemain), jadi dipilih dua Spy (57,0%). Tanpa pengumuman jumlah Hitman, dua Hitman terlalu kuat: warga hanya menang 21–32% di 8–10 pemain. Seleksi diulang dengan 6 langkah keputusan per fase (lebih dekat ke runtime; bot melangkah tiap `NPC_STEP_SECONDS`), karena hasil 9–10 pemain sensitif terhadap jumlah langkah. Tabel tetap: 8 dan 9 pemain seimbang (53,5% dan 52,0%). Di 10 pemain tidak ada kandidat di 40–60% (2/2/1: 64,5%; 2/1/1: 61,5% dan Spy tidak boleh turun; 3/2/1: 29,0%; 3/1/1: 15,5%), jadi dipilih yang paling dekat 50% dan sesuai aturan monoton: 2/2/1, condong ke warga. 7 pemain sengaja tetap satu Hitman walau condong ke warga (71%), karena dua Hitman hanya 32–37,5%. Angka ini dari bot melawan bot, belum dari manusia, jadi tabel bersifat **sementara**; cukup diubah di satu tempat bila data pertandingan manusia menunjukkan hal lain.
- NPC mengisi kursi kosong sampai kapasitas. Manusia yang bergabung sebelum mulai menggantikan kursi NPC. Roster terkunci setelah mulai; anggota lama dapat reconnect.
- Satu akun menempati satu room. Keluar dari lobby/hasil sebelum pindah room. Logout mencabut sesi tanpa menghentikan pertandingan; login ulang memulihkan keanggotaan.

## Fase setiap ronde

| Fase | Interaksi dan resolusi |
| --- | --- |
| Siang | Diskusi publik. Hitman dapat menggunakan Gag Order secara instan. |
| Malam | Layar meredup, chat terkunci. Hostage, Guard, dan Peek dipilih privat, diselesaikan bersama saat timer habis. Guard diproses sebelum Hostage. |
| Tribunal | Rekap tanpa nama target atau hasil individual. Pemain yang punya hak suara memilih tersangka. Suara terbanyak tunggal dieksekusi. Di room dengan ≥ 2 Hitman, jumlah Hitman yang masih hidup diumumkan setelah eksekusi. |

Durasi ditetapkan dari jumlah peserta awal N (manusia + NPC), tetap selama pertandingan. Standar: siang 20N detik, malam 5N detik, Tribunal dibulatkan ke atas dari 7,5N detik. Mode cepat: siang dibulatkan ke atas dari 10N/3 detik, malam dan Tribunal masing-masing dari 2,5N detik. Contoh standar: 4 pemain 80/20/30 detik; 6 pemain 120/30/45; 10 pemain 200/50/75. Timer server tetap berjalan walaupun tab ditutup. Chat kembali tersedia saat Tribunal bagi pemain yang masih boleh berbicara.

Semua manusia hidup dapat menyetujui skip siang. Hostage/Gag tetap boleh menyetujui karena ini bukan chat atau voting Tribunal. Hanya jumlah persetujuan dipublikasikan; jika belum lengkap, timer normal berlaku.

## Kemampuan dan status

| Role | Faksi | Kemampuan |
| --- | --- | --- |
| Hitman | Syndicate | Para Hitman saling tahu (`me.allies`). Syndicate menyandera **satu** pemain per malam: setiap Hitman memilih, target = pilihan terbanyak, seri → pilihan yang paling awal (pilihan rekan terlihat lewat `me.ally_actions`). Gag Order satu pemain saat siang, **satu kali untuk seluruh Syndicate**, cooldown satu ronde penuh: ronde 1 lalu ronde 3. Hostage/Gag tidak boleh ke rekan; vote ke rekan boleh. |
| Spy | Warga | Guard satu pemain, termasuk diri sendiri. Tidak boleh target sama dua malam berturut-turut (berlaku per Spy). Guard mencegah serangan malam itu, tidak membebaskan Hostage lama. |
| Stalker | Warga | Peek role asli satu pemain setelah malam selesai. Hasil privat; sekali setiap dua ronde: ronde 1 lalu ronde 3. |
| Civilian | Warga | Tidak punya skill malam; mengamati, berdebat, dan voting. |

**Hostage:** tetap hidup di roster, kehilangan chat dan voting permanen. Sesuai pembatasan tertulis di GDD, skill malam tetap tersedia mengikuti role/cooldown. Korban tetap faksi warga.

**Gag Order:** hanya membatasi chat sampai akhir ronde penggunaan. Voting dan skill malam tetap tersedia. Gag tidak mengurangi suara warga dalam kondisi kemenangan.

**Dieksekusi:** tidak bisa chat, aksi, atau voting; menjadi penonton. Menang/kalah mengikuti faksi, termasuk bagi yang dieksekusi atau Hostage.

Aksi malam dan vote final, satu pilihan per fase. Target harus hidup; hanya Guard boleh memilih diri sendiri. Memilih pemain yang sudah Hostage diperbolehkan karena status lawan rahasia, tetapi tidak menambah korban baru.

## Kemenangan

Backend mengecek setelah resolusi malam dan Tribunal:

1. **Warga menang** jika **semua** Hitman dieksekusi.
2. **Hitman (Syndicate) menang**, selama masih ada Hitman hidup, saat warga hidup yang tidak Hostage **tidak lebih banyak dari Hitman yang hidup**. Suara warga tidak lagi melampaui suara Hitman. Warga dieksekusi/Hostage tidak dihitung; Gag tetap dihitung.

Tidak ada hasil seri pertandingan. Jika kedua kondisi kemenangan belum terpenuhi, lanjutkan ke ronde berikutnya.

Contoh enam pemain (satu Hitman): tiga dari lima warga Hostage, dua bebas → lanjut. Satu lagi disandera atau dieksekusi → Hitman menang. Guard berhasil sehingga dua warga tetap bebas → lanjut. Hitman dieksekusi pada Tribunal ronde berapa pun → warga menang dan permainan selesai.

Contoh sepuluh pemain (dua Hitman): satu Hitman dieksekusi → permainan lanjut dan diumumkan "Hitman tersisa: 1". Syndicate tinggal satu Hitman, jadi Syndicate menang bila warga bebas tinggal satu; warga menang begitu Hitman terakhir dieksekusi.

**Pengumuman jumlah Hitman (hanya room yang sejak awal punya ≥ 2 Hitman).** Setelah setiap eksekusi Tribunal, engine menulis event "Tribunal mengeksekusi X. Hitman tersisa: n. Role tetap dirahasiakan sampai permainan selesai." dan setiap snapshot (semua pemain, semua fase termasuk persiapan dan selesai) memuat `hitman_remaining` = jumlah Hitman yang masih hidup. Room satu Hitman berisi `hitman_remaining: null` dan teks eksekusinya tidak berubah. Alasannya: di room satu Hitman, warga sudah tahu apakah korban eksekusi Hitman (game selesai atau berlanjut). Pengumuman ini mengembalikan informasi yang sama untuk room multi-Hitman, jadi prinsip "role korban dirahasiakan" tetap berlaku: role korban tidak diumumkan langsung, hanya jumlah Hitman tersisa. Tanpa pengumuman ini, Syndicate dua Hitman terlalu kuat (lihat tabel komposisi). Angka hanya berubah karena eksekusi; Hostage, Gag, dan aksi malam tidak memengaruhinya.

Ketentuan pelengkap untuk bagian GDD yang belum merinci: vote seri/tanpa suara tidak mengeksekusi siapa pun dan permainan dilanjutkan jika belum ada pemenang; role korban eksekusi dirahasiakan sampai akhir.

Hasil akhir menunjukkan faksi pemenang, alasan, menang/kalah akun sendiri, jumlah warga hidup/Hostage/dieksekusi/masih punya suara, serta role dan status akhir semua peserta.

## Blind information

Snapshot aktif hanya memuat role, status, pilihan aksi, dan hasil Peek milik akun peminta. Roster lawan hanya berisi nama dan hidup/tidak. Tidak ada pengumuman target Hostage, Gag, Guard, atau Peek. Rekap malam sama untuk serangan berhasil, gagal, atau tanpa serangan. Jumlah tiap role (`composition`) publik untuk semua pemain, begitu juga jumlah Hitman tersisa (`hitman_remaining`) di room ≥ 2 Hitman. Hanya Hitman yang menerima daftar rekan (`me.allies`), pilihan Hostage rekan malam itu (`me.ally_actions`), dan cooldown Gag bersama (`me.next_gag`); warga selalu menerima `allies`/`ally_actions` kosong dan `next_gag` 1, sehingga tidak bisa menebak kapan Gag dipakai.

Vote yang dikirim terlihat saat Tribunal, termasuk nama pemilih per target, tanpa daftar orang yang berhak voting. Diam bisa berarti strategi, Gag, Hostage, atau offline.

Label NPC tidak ditampilkan di roster pertandingan aktif. Lobby masih menampilkan kursi/konfigurasi NPC, sehingga versi ini **belum menjadi protokol eksperimen Turing Test tersamar penuh**. Eksperimen tersamar memerlukan penyamaran identitas lobby, prosedur rekrutmen, serta evaluasi tersendiri.

## Persiapan pertandingan

Setelah host menekan Mulai, semua peserta masuk ke **layar persiapan** berisi panduan singkat (tujuan, siang, malam, Tribunal, bot AI, tips) dan progres pemuatan AI. Ronde 1 **belum berjalan** selama persiapan. Ronde 1 dimulai ketika otak bot siap **dan** waktu baca minimal 10 detik lewat. Tombol "Siap" mencatat kesiapan pemain tetapi tidak melewati waktu minimum. Jika AI gagal atau belum siap dalam 90 detik, permainan tetap dimulai dengan aksi cadangan engine. Room tanpa bot langsung siap, tetapi tetap menunggu waktu minimum. Splash memudar keluar dan meja permainan masuk secara halus; pengaturan reduced motion menonaktifkan animasi tersebut.

## NPC: otak dari notebook skripsi

`services/npc_service.py` menjalankan NPC dari timer tanpa menunggu pesan manusia. Setiap bot punya **ingatan, metode, dan persona sendiri** (multi-bot aman; ingatan tidak dibagi). Logikanya adalah kode notebook skripsi yang diekspor apa adanya ke `services/npc_brain/generated/` oleh `scripts/ekspor_otak_npc.py`:

1. **NLU IndoBERT** (satu model untuk semua bot): intent (offend/defend/neutral) dan target per pemain untuk setiap chat publik. Karena nama pengguna bebas (mis. `tester`, `andy123`), nama pemain diganti nama yang dikenal model sebelum intent dibaca; tanpa itu tuduhan singkat seperti "curiga sama tester" terbaca netral. Hasil anotasi disimpan sekali karena identik untuk semua bot. Tanpa folder model, dipakai NLU cadangan (SVM lama + nama yang disebut) dan hal itu dicatat di trace.
2. **Penalaran**: bukti publik per pemain → Fuzzy Mamdani, Utility AI, atau Behavior Tree → rencana chat, vote, dan aksi rahasia (Gag, Hostage, Guard, Peek). `NPC_METHOD=campuran` membagi bot dalam satu room bergiliran ke tiga metode (urutan diacak per pertandingan); metode dan persona tiap bot dicatat di tabel `match_bots` untuk analisis survei.
3. **NLG**: rencana → kalimat. Penulis LLM berupa **rantai prioritas** yang urutan dan jalur aktifnya diatur di panel Otak NPC (awal: `NPC_WRITER_ORDER`): Claude lewat Amazon Bedrock (`AMAZON_API_KEY`) → Claude API (`ANTHROPIC_API_KEY`) → OpenRouter (key di Konfigurasi AI; model `NPC_OPENROUTER_MODEL`, bawaan `anthropic/claude-opus-5.5`) → LLM sendiri lewat link (URL tunnel di Konfigurasi AI, mis. Ollama di Docker; dikenali sebagai Ollama atau server kompatibel OpenAI). Setiap jalur dicek dulu saat otak dimuat, saat konfigurasi berubah, atau lewat tombol **Cek ulang** (Claude: pesan 8 token; OpenRouter: key/model lalu satu pesan pendek dengan batas token yang sama seperti saat bermain agar saldo kurang langsung ketahuan; link: daftar model). Jalur yang ditolak (401/403/402/404) dilewati sampai dicek ulang; yang gagal sementara (429, error server, timeout) diistirahatkan 30 detik, berlipat dua bila gagal lagi (maks 5 menit). Penulis tidak menerima role asli bot; setiap kalimat diperiksa aturan (tidak mengaku bot/AI, tidak membocorkan role/aksi, target disebut) dan dibaca ulang IndoBERT. Semua jalur gagal/tanpa key → templat bervariasi sesuai persona. Jalur yang menulis dicatat di trace (`penulis`).

Bot mengambil langkah setiap `NPC_STEP_SECONDS` (bawaan 3 detik), digeser beberapa detik per bot. Vote dan aksi rahasia diterapkan begitu diputuskan, sedangkan kalimat melewati **lantai bicara**: dalam satu pertandingan hanya satu bot yang menyusun dan "mengetik" pada satu waktu. Rencana chat yang dibuat sebelum chat bot lain masuk dibatalkan, lalu bot memutuskan ulang dengan chat terbaru. Chat manusia tidak pernah ditahan. Di notebook, bot tidak ikut bertanya bila pemain lain baru saja bertanya, dan tidak menjadi suara ketiga yang mengulang tuduhan atau pembelaan yang sama di fase itu (anti-gema). Kalimat yang baru muncul di room juga tidak diulang bot lain. Hasilnya, bot tidak bertanya serentak dan tidak saling mengembari. Bot tidak menunggu manusia bicara: satu bot membuka diskusi, dan jika ruangan hening (tidak ada chat selama ≥ max(15 detik, 20% durasi fase), sekitar 24 detik di siang standar) bot boleh memancing percakapan lagi atau mengajak pemain yang belum bicara. Bot tetap tidak menuduh tanpa bukti. Keputusan diterapkan hanya jika ronde/fase belum berganti; aksi yang ditolak engine tidak mengubah state. Begitu otak memegang fase tertentu, "tunggu"/abstain miliknya dihormati; fallback acak engine hanya untuk bot yang otaknya gagal.

Kebijakan vote saat bukti lemah berbeda per metode (`PAKSA_VOTE_BUKTI_LEMAH`, dipilih lewat uji A/B melawan engine): bot Behavior Tree tetap memberi suara ke tersangka teratas di paruh akhir Tribunal, sedangkan bot Fuzzy dan Utility AI abstain bila belum yakin. Abstain membuat pemilih tunggal yang mengeksekusi warga (sering Hitman) mudah dicurigai pada ronde berikutnya.

Mode `NPC_METHOD=llm` mempertahankan cara lama (satu prompt LLM memutuskan aksi dan pesan) sebagai pembanding penelitian.

Label NPC tidak ditampilkan di roster pertandingan aktif. Lobby dan layar persiapan tetap menyebut jumlah bot, sehingga versi ini **belum menjadi protokol eksperimen Turing Test tersamar penuh**.

## Akhir pertandingan dan survei

Layar hasil menampilkan ucapan selamat (untuk pemenang pribadi atau kubu pemenang), daftar pemenang beserta role, dan statistik akhir. Di bawahnya ada **survei**: pertanyaan, jenis jawaban (bintang, skala angka, pilihan ganda, teks), rentang skala, dan arti nilai terkecil/terbesar diatur administrator di panel (menu **Survei**), bukan di frontend. Setiap akun manusia mengirim survei sekali per pertandingan (kiriman ganda bersamaan juga dijawab "sudah dikirim"); jawaban menyimpan salinan pertanyaan saat dijawab beserta role/kubu/hasil pemain. Pemain yang sudah keluar room tetap bisa mengirim survei pertandingan itu selama 30 menit (registri di memori server; restart menghapusnya). Panel menampilkan rata-rata per pertanyaan dan per metode bot: setiap jawaban dihitung sekali, ke metode tunggal pertandingan itu atau ke kelompok "campuran" bila botnya memakai beberapa metode. Ekspor CSV memakai UTF-8 dengan BOM dan menyimpan nilai persis; impor kolom teks sebagai teks di spreadsheet agar jawaban bebas tidak dievaluasi sebagai formula.

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

Tes otomatis mencakup 4–10 pemain, komposisi role per jumlah pemain, Syndicate (Hostage bersama, Gag bersama, larangan menarget rekan, privasi daftar rekan, pengumuman jumlah Hitman tersisa, menang/kalah dengan beberapa Hitman), permainan tanpa pemenang melewati ronde 25, Guard/Peek/Gag/Hostage, dominasi suara, prioritas kemenangan, privasi, voting, reconnect, scheduler/validasi/fallback NPC mode LLM dengan respons model tiruan, layar persiapan, survei, serta pertandingan multi-bot penuh memakai otak hasil notebook melawan engine asli. Tes ini tidak membuktikan kualitas taktik atau latensi provider produksi.

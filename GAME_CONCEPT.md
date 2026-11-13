# Silent Terror: aturan permainan dan perilaku bot

File ini adalah acuan aturan permainan, perilaku bot NPC, dan angka keseimbangan komposisi role. Letak kodenya
dijelaskan di [CODE_GUIDE.md](CODE_GUIDE.md); cara menjalankan game ada di [README.md](README.md).

Silent Terror adalah game social deduction multipemain berbasis web dengan hidden role yang asimetris. Fokusnya
deduksi dari percakapan, alibi, dan voting. Tidak ada ekonomi, pembelian item, atau tebusan. Aturan di sini mengikuti
GDD awal dengan beberapa perubahan (lihat [Perubahan atas GDD awal](#perubahan-atas-gdd-awal)).

## Istilah

| Istilah | Arti |
| --- | --- |
| Warga | Kubu Spy, Stalker, dan Civilian |
| Syndicate | Kubu Hitman |
| Hostage | Sandera malam oleh Syndicate. Korban tetap hidup, tetapi kehilangan semua aksi |
| Gag Order (Gag) | Bungkam chat publik satu pemain saat siang |
| Guard | Jaga satu pemain dari Hostage malam itu (Spy) |
| Peek | Intip role asli satu pemain (Stalker) |
| Tribunal | Fase voting untuk mengeksekusi satu tersangka |
| Snapshot | Data pertandingan yang dikirim server untuk satu pemain; informasi privat pemain lain tidak ikut |

## Perubahan atas GDD awal

| Sejak | Perubahan |
| --- | --- |
| Awal | Mode kecil 4 dan 5 pemain; durasi fase mengikuti jumlah peserta |
| 23 Oktober 2026 | Urutan ronde siang → Tribunal → malam (ronde 1 tanpa Tribunal). Hostage kehilangan semua aksi, termasuk skill malam |
| 26 Oktober 2026 | Setiap Hitman diberi tahu hasil Hostage tim tiap malam (berhasil, atau gagal karena Guard) |
| 1 November 2026 | Korban Hostage diumumkan ke semua pemain saat malam selesai, dan tandanya tampil sampai permainan selesai |
| 3 November 2026 | Guard boleh ke target yang sama berturut-turut; suara seri di Tribunal menambah waktu sekali; Spy di room ≥ 2 Spy saling tahu; Hitman dan Spy di room ≥ 2 pemain role itu punya chat tim saat malam |

## Ruangan dan role

- **4–10 peserta**, campuran manusia dan NPC. Host memilih kapasitas room; permainan bisa dimulai dengan sedikitnya
  empat peserta.
- **Tanpa batas ronde.** Permainan berlanjut sampai salah satu kubu menang.
- Komposisi role mengikuti jumlah peserta (`KOMPOSISI_PERAN` di `match_engine.py`). Hitman dan Spy bisa lebih dari
  satu, Stalker selalu satu, sisanya Civilian. Role diacak server untuk manusia maupun NPC. Jumlah tiap role
  diketahui semua pemain (`composition` di snapshot); siapa pemegangnya tetap rahasia.

| Peserta | Hitman | Spy | Stalker | Civilian | Warga menang (Fuzzy saja, 200 game, 6 langkah per fase, 7 Nov 2026) | Rata-rata ronde |
| --- | --- | --- | --- | --- | --- | --- |
| 4 | 1 | 1 | 1 | 1 | 47,0% ± 6,9 | 2,00 |
| 5 | 1 | 1 | 1 | 2 | 47,0% ± 6,9 | 2,39 |
| 6 | 1 | 1 | 1 | 3 | 46,0% ± 6,9 | 3,23 |
| 7 | 2 | 2 | 1 | 2 | 60,5% ± 6,8 (1000 game: 55,1% ± 3,1) | 3,88 |
| 8 | 2 | 2 | 1 | 3 | 52,5% ± 6,9 | 4,82 |
| 9 | 2 | 2 | 1 | 4 | 56,0% ± 6,9 | 6,05 |
| 10 | 2 | 2 | 1 | 5 | 59,5% ± 6,8 | 7,23 |

Cara angka ini diukur dan riwayatnya ada di [Keseimbangan komposisi](#keseimbangan-komposisi).

- NPC mengisi kursi kosong sampai kapasitas. Manusia yang bergabung sebelum mulai menggantikan kursi NPC. Roster
  terkunci sesudah mulai; anggota lama boleh reconnect. Pemain yang keluar di tengah pertandingan tidak bisa bergabung
  lagi ke pertandingan itu.
- Satu akun menempati satu room. Keluar dari lobby sebelum pindah room. Room yang pertandingannya sudah selesai
  dilepas otomatis saat pemain membuat atau bergabung ke room lain; survei pertandingan itu tetap bisa dikirim.
- Selama pertandingan aktif, membuka tab baru, halaman lain di aplikasi, atau login ulang mengembalikan akun ke
  `/game` berdasarkan data backend. Akun tidak bisa membuat atau bergabung ke pertandingan lain sebelum pertandingan
  itu selesai. Logout mencabut sesi tanpa menghentikan pertandingan; login ulang memulihkan keanggotaan.

## Fase setiap ronde

Urutan ronde: **siang → Tribunal → malam**. Ronde 1 tanpa Tribunal (siang langsung ke malam), karena belum ada
kejadian malam yang bisa dibahas sebelum voting. Tribunal pertama ada di ronde 2 dan selalu datang tepat sesudah
diskusi siang.

| Fase | Interaksi dan resolusi |
| --- | --- |
| Siang | Diskusi publik. Hitman bisa memakai Gag Order secara instan. |
| Tribunal | Mulai ronde 2. Pemain yang punya hak suara memilih tersangka; suara boleh dibatalkan dan dipilih ulang sampai waktu habis. Suara terbanyak tunggal dieksekusi. Di room dengan ≥ 2 Hitman, jumlah Hitman yang masih hidup diumumkan sesudah eksekusi. |
| Malam | Layar meredup dan chat publik terkunci (chat tim: lihat [Kemampuan dan status](#kemampuan-dan-status)). Hostage, Guard, dan Peek dipilih privat lalu diselesaikan bersama saat timer habis; Guard diproses sebelum Hostage. Hasil malam tampil di tirai pagi dan terlihat mulai siang ronde berikutnya. |

**Seri di Tribunal.** Bila saat waktu habis ada ≥ 2 pemimpin suara, waktu ditambah **sekali** per Tribunal: 30 detik
(mode cepat 10 detik). Tambahan ini diumumkan lewat catatan dan penanda publik `tribunal_extra`. Suara lama tetap
berlaku; manusia boleh membatalkan dan memilih ulang, termasuk ke nama yang tidak seri. Bila masih seri sesudah
tambahan, tidak ada eksekusi dan permainan lanjut ke malam. Tanpa suara sama sekali bukan seri, jadi tidak ada
tambahan dan tidak ada eksekusi.

**Rekap malam publik** hanya menyebut korban Hostage: "Malam selesai. X disandera: …", atau "Malam selesai. Malam
ini tidak ada yang disandera." bila Hostage dijaga Guard atau Syndicate tidak memilih. Target Hostage yang gagal,
Guard, dan Peek tidak diumumkan.

### Durasi fase

Durasi ditetapkan dari jumlah peserta awal N (manusia + NPC) dan tetap selama pertandingan. Waktu tambahan karena
seri hanya memundurkan `deadline` Tribunal itu. Timer server tetap berjalan walaupun tab ditutup.

| Mode | Siang | Tribunal | Malam |
| --- | --- | --- | --- |
| Standar | 20N detik | 7,5N dibulatkan ke atas, + 30 detik | 5N detik |
| Cepat | 10N/3 dibulatkan ke atas | 2,5N dibulatkan ke atas | 2,5N dibulatkan ke atas |

Tambahan 30 detik di Tribunal standar memberi waktu menimbang dan mengunci vote sesudah diskusi siang. Contoh durasi
standar (siang/Tribunal/malam): 4 pemain 80/60/20 detik, 6 pemain 120/75/30 detik, 10 pemain 200/105/50 detik. Contoh
mode cepat untuk 6 pemain: 20/15/15 detik.

Chat publik tersedia saat siang dan Tribunal bagi pemain yang masih boleh berbicara.

### Skip diskusi

Saat siang, tombol **Setuju skip diskusi** mempercepat ke fase berikutnya (malam di ronde 1, Tribunal di ronde
berikutnya) sesudah **semua manusia yang masih hidup** setuju. Bot tidak dihitung. Pemain yang di-Gag atau disandera
tetap boleh setuju, karena ini bukan chat atau vote. Persetujuan tidak bisa ditarik pada ronde itu, dan pemain offline
belum dianggap setuju. Hanya jumlah persetujuan yang dipublikasikan; bila belum lengkap, timer normal berlaku.

## Kemampuan dan status

| Role | Kubu | Kemampuan |
| --- | --- | --- |
| Hitman | Syndicate | Para Hitman saling tahu (`me.allies`). Syndicate menyandera **satu** pemain per malam: setiap Hitman memilih, dan target = pilihan terbanyak (pilihan rekan terlihat lewat `me.ally_actions`). Pada seri antara pilihan manusia dan bot, pilihan manusia yang dipakai; sesama manusia atau sesama bot memakai pilihan paling awal. Gag Order satu pemain saat siang, **satu kali untuk seluruh Syndicate**, dengan cooldown satu ronde penuh (ronde 1, lalu ronde 3). Hostage dan Gag tidak boleh ke rekan; vote ke rekan boleh. Sesudah malam, setiap Hitman tahu hasil Hostage tim (`me.syndicate_hostages`): berhasil, atau gagal karena target dijaga Guard. |
| Spy | Warga | Guard satu pemain, termasuk diri sendiri, dan boleh target yang sama berturut-turut. Guard mencegah Hostage malam itu, tetapi tidak membebaskan korban lama. Di room yang sejak awal punya ≥ 2 Spy, para Spy saling tahu (`me.spy_allies`) dan melihat pilihan Guard rekan malam itu (`me.spy_actions`). |
| Stalker | Warga | Peek role asli satu pemain; hasilnya privat dan keluar sesudah malam selesai. Sekali tiap dua ronde: ronde 1, lalu ronde 3. |
| Civilian | Warga | Tidak punya skill malam; mengamati, berdebat, dan voting. |

**Chat tim.** Hanya saat malam, untuk Hitman hidup di room yang sejak awal punya ≥ 2 Hitman, dan Spy hidup yang tidak
disandera di room yang sejak awal punya ≥ 2 Spy. Kanal Hitman dan Spy terpisah dan tidak saling terlihat. Pesan
dikirim lewat `POST /api/rooms/{code}/team-chat` (token match, ronde, fase; 1–1000 karakter), disimpan di memori
pertandingan (100 pesan terakhir per tim), dan dibaca lewat `me.team_messages` oleh pengirim dan rekan setim yang
berhak. Rekan yang sudah tersingkir atau disandera tidak lagi menerimanya. Gag tidak memengaruhi chat tim. Bot ikut
chat tim hanya bila ada rekan manusia yang hidup dan tidak disandera; sesama bot tidak mengobrol.

**Hostage.** Korban tetap hidup di roster, tetapi kehilangan **semua aksi** secara permanen: chat, voting, dan skill
malam. Ini lebih ketat dari GDD awal yang mempertahankan skill malam. Engine menolak aksinya, `can_act` di snapshot
selalu `false`, dan bot yang disandera juga tidak beraksi. Korban tetap kubu warga.

- Saat malam selesai, korban **diumumkan ke semua pemain**: roster publik memuat `hostage: true` dan `hostage_round`
  (malam korban disandera), dan cap *Disandera* menempel di kartu korban sampai pertandingan selesai.
- Korban yang sudah disandera tidak bisa disandera atau di-Gag lagi (engine menolak, UI menonaktifkan targetnya),
  jadi malam Syndicate tidak terbuang.
- Saat malam berjalan, hanya Hitman yang melihat cap *Disandera* pada korban tim malam itu. Target yang dijaga Guard
  tetap rahasia bagi warga; Hitman melihat cap *Disandera* bertanda *GAGAL* yang memudar pada siang berikutnya.

**Gag Order.** Hanya membatasi chat publik sampai siang berikutnya (melewati Tribunal ronde itu bila ada). Voting dan
skill malam tetap tersedia, dan Gag tidak mengurangi suara warga dalam kondisi kemenangan.

**Dieksekusi.** Tidak bisa chat, beraksi, atau voting; menjadi penonton. Menang atau kalah mengikuti kubu, termasuk
bagi yang dieksekusi atau disandera.

**Keluar di tengah pertandingan** (tombol Keluar, dengan konfirmasi). Diperlakukan sama dengan dieksekusi, dan
kemenangan langsung dicek ulang. Roster menandainya `left` ("Keluar"), dan catatannya "X meninggalkan permainan."
dengan akhiran yang sama seperti eksekusi (jumlah Hitman tersisa, role tetap rahasia). Vote dan aksi malam miliknya
dibuang; vote dan aksi yang menargetkannya juga dibuang sehingga pemilihnya boleh memilih ulang. Fase tidak menunggu
dia (skip diskusi dan layar persiapan dihitung ulang). Pemain kembali ke menu utama.

**Mengganti pilihan.** Satu pilihan per fase; untuk mengganti, batalkan dulu.

- Vote Tribunal: tombol **Batalkan vote** (`POST /api/rooms/{code}/cancel-vote`), lalu pilih ulang. Yang dihitung
  suara saat waktu habis.
- Hostage, Guard, dan Peek: tombol **Batalkan Sandera/Jaga/Intip** (`POST /api/rooms/{code}/cancel-action`), lalu
  pilih ulang. Yang diresolusikan pilihan saat malam habis.
- Gag Order tidak bisa dibatalkan karena langsung berlaku: target dibungkam dan cooldown tim berjalan saat dikirim.
- Target harus hidup; hanya Guard yang boleh memilih diri sendiri. Hostage dan Gag tidak boleh ke korban Hostage
  (statusnya publik). Guard, Peek, dan vote ke korban Hostage tetap boleh walau tidak berguna.

## Kemenangan

Backend mengecek kemenangan sesudah resolusi malam, sesudah Tribunal, dan saat pemain keluar:

1. **Warga menang** bila **semua** Hitman sudah dieksekusi (atau keluar).
2. **Syndicate menang**, selama masih ada Hitman hidup, saat warga hidup yang tidak disandera **tidak lebih banyak
   dari Hitman yang hidup**. Warga yang dieksekusi atau disandera tidak dihitung; warga yang di-Gag tetap dihitung.

Tidak ada hasil seri pertandingan. Bila belum ada pemenang, permainan lanjut ke ronde berikutnya. Vote yang masih seri
sesudah waktu tambahan, atau tanpa suara, tidak mengeksekusi siapa pun. Role korban eksekusi dirahasiakan sampai
akhir.

Contoh enam pemain (satu Hitman): tiga dari lima warga disandera, dua bebas → lanjut. Satu lagi disandera atau
dieksekusi → Hitman menang. Guard berhasil sehingga dua warga tetap bebas → lanjut. Hitman dieksekusi pada Tribunal
ronde berapa pun → warga menang.

Contoh sepuluh pemain (dua Hitman): satu Hitman dieksekusi → permainan lanjut dan diumumkan "Hitman tersisa: 1".
Syndicate tinggal satu Hitman, jadi Syndicate menang bila warga bebas tinggal satu; warga menang begitu Hitman terakhir
dieksekusi.

**Pengumuman jumlah Hitman (hanya room yang sejak awal punya ≥ 2 Hitman).** Sesudah setiap eksekusi Tribunal, engine
menulis "Tribunal mengeksekusi X. Hitman tersisa: n. Role tetap dirahasiakan sampai permainan selesai." Setiap
snapshot (semua pemain, semua fase termasuk persiapan dan selesai) memuat `hitman_remaining` = jumlah Hitman yang
masih hidup. Room satu Hitman berisi `hitman_remaining: null` dan teks eksekusinya tidak berubah. Alasannya: di room
satu Hitman, warga sudah tahu apakah korban eksekusi itu Hitman (game selesai atau berlanjut). Pengumuman ini
memberi informasi yang sama untuk room multi-Hitman tanpa membuka role korban. Tanpa pengumuman ini, Syndicate dua
Hitman terlalu kuat (lihat [riwayat pengukuran](#riwayat-pengukuran)). Angkanya hanya berubah karena eksekusi atau
pemain keluar.

Layar hasil menunjukkan kubu pemenang, alasannya, menang atau kalah akun sendiri, jumlah warga hidup, disandera,
dieksekusi, dan yang masih punya suara, serta role dan status akhir semua peserta.

## Informasi tersembunyi

- Snapshot aktif hanya memuat role, status, pilihan aksi, dan hasil Peek milik akun peminta. Roster pemain lain hanya
  berisi nama dan hidup atau tidak, ditambah `left` bagi yang keluar dan `hostage`/`hostage_round` bagi korban Hostage
  (keduanya sudah diumumkan).
- Tidak ada pengumuman target Gag, Guard, Peek, atau Hostage yang gagal. Serangan yang gagal dan malam tanpa serangan
  sama-sama diumumkan "tidak ada yang disandera", jadi hanya Syndicate yang tahu target yang dijaga Guard.
- Publik untuk semua pemain: jumlah tiap role (`composition`) dan, di room ≥ 2 Hitman, jumlah Hitman tersisa
  (`hitman_remaining`).
- Hanya untuk Hitman: daftar rekan (`me.allies`), pilihan Hostage rekan malam itu (`me.ally_actions`), korban Hostage
  tim malam itu (`me.syndicate_target`), hasil Hostage tim tiap malam (`me.syndicate_hostages`), target Gag ronde ini
  (`me.ally_gags`), dan cooldown Gag bersama (`me.next_gag`). Warga selalu menerima nilai kosong dan `next_gag` 1,
  sehingga tidak bisa menebak kapan atau ke siapa Gag dipakai.
- Hanya untuk Spy: rekan Spy (`me.spy_allies`) dan pilihan Guard rekan (`me.spy_actions`); kosong di room 4–6 dan
  bagi role lain. Kolom ini terpisah dari `me.allies` karena kode bot membaca `allies` sebagai rekan Syndicate.
- Pesan chat tim (`me.team_messages`) hanya dikirim saat malam ke pengirim dan rekan setim yang berhak. Pesan itu tidak
  masuk `messages`, `events`, riwayat chat, database, NLU, checker, jejak aktivitas panel, snapshot pemain lain, atau
  layar hasil, dan tidak memakai nomor urut chat publik.
- Pemain yang di-Gag hanya tahu status dirinya sendiri (`me.gagged`); status Hostage publik.
- Vote yang dikirim terlihat saat Tribunal, termasuk nama pemilih per target, tanpa daftar orang yang berhak voting.
  Diam bisa berarti strategi, Gag, atau offline.
- Metode otak bot tidak ditampilkan ke pemain; panel admin tetap menampilkannya. Lobby dan layar persiapan masih
  menyebut jumlah bot, jadi versi ini **belum menjadi protokol eksperimen Turing Test tersamar penuh**. Eksperimen
  tersamar memerlukan penyamaran identitas lobby, prosedur rekrutmen, dan evaluasi tersendiri.

## Persiapan dan tampilan pertandingan

Sesudah host menekan Mulai, semua peserta masuk **layar persiapan** dengan tiga kartu: role pribadi (karakter dan
aksesori seperti di Main), contoh aksi, dan target kemenangan. Barisan karakter peserta dan progres AI tampil di
bawahnya.

- Ronde 1 belum berjalan, dan waktu baca minimum **40 detik**. Membuka role atau menekan Siap tidak mempercepat
  countdown bersama.
- Saat tersisa **10 detik**, pemain yang belum membuka role mendapat pengingat; pada **5 detik terakhir**, kartu dibuka
  otomatis. Pembukaan pertama tetap memberi jeda baca lokal 3 detik, termasuk bila reconnect melewati countdown.
- Bila AI baru siap saat waktu baca hampir habis, countdown memberi hingga 10 detik tambahan, tanpa melewati batas
  tunggu **90 detik**. Pada batas itu permainan mulai dengan aksi cadangan engine. Room tanpa bot tetap menunggu
  minimum 40 detik.
- Saat ronde 1 dimulai, tirai transisi menaungi splash yang memudar dan meja yang muncul; reduced motion menonaktifkan
  animasi.

Selama pertandingan, chat ikut turun ke pesan terbaru bila pemain sedang di dasar daftar atau baru mengirim pesan.
Pemain yang sedang menggulir riwayat tidak ditarik turun; tombol "↓ n pesan baru" muncul sebagai gantinya. Pada 5
detik terakhir siang, malam, dan Tribunal, angka hitung mundur besar muncul di tengah layar tanpa menangkap klik, jadi
chat, vote, dan aksi tetap bisa dipakai.

## Akhir pertandingan dan survei

Layar hasil menampilkan ucapan selamat (untuk pemenang pribadi atau kubu pemenang), daftar pemenang beserta role, dan
statistik akhir. Di bawahnya ada **survei**.

- Pertanyaan, jenis jawaban (bintang, skala angka, pilihan ganda, teks), rentang skala, dan arti nilai terkecil dan
  terbesar diatur administrator di panel menu **Survei**, bukan di frontend.
- Pilihan bernama `Lainnya` pada pilihan ganda membuka isian bebas, disimpan sebagai `Lainnya: <isian>`.
- Pertanyaan baru selalu masuk paling bawah. Urutannya diatur dengan menyeret pegangan ⋮⋮ atau tombol ▲▼ (Alt+↑/↓),
  langsung tersimpan lewat `PUT /api/panel/survey/questions/order`, dan dipakai form pemain serta ekspor CSV.
- Setiap akun manusia mengirim survei sekali per pertandingan; kiriman ganda bersamaan juga dijawab "sudah dikirim".
  Jawaban menyimpan salinan pertanyaan saat dijawab beserta role, kubu, dan hasil pemain.
- Peserta manusia tiap pertandingan yang selesai diarsipkan di tabel `match_participants`, jadi survei tetap bisa
  dikirim sesudah keluar room, sesudah room dibersihkan, atau sesudah server dinyalakan ulang. Bila arsip itu gagal
  disimpan, backend masih mengingat peserta di memori selama 30 menit.
- Selama survei belum diisi, halaman Main menampilkan pengingat "Ayo isi survei untuk game ruangan …" di atas binder
  (satu baris per pertandingan, bisa digulir). Tombol X hanya menyembunyikannya sampai Main dibuka lagi.
- Panel menampilkan rata-rata per pertanyaan dan per metode bot. Setiap jawaban dihitung sekali: ke metode tunggal
  pertandingan itu, atau ke kelompok "campuran" untuk pertandingan lama yang botnya memakai beberapa metode.
- Menu Survei juga bisa menghapus permanen semua jawaban beserta arsip peserta (administrator mengetik BERSIHKAN),
  lalu menghapus pertanyaan yang sudah tidak punya jawaban. Ekspor CSV dijelaskan di
  [README.md](README.md#panel-administrator).

## NPC: otak bot

Setiap bot NPC punya **ingatan dan persona sendiri**; ingatan tidak dibagi antarbot. Bot melangkah dari timer tanpa
menunggu pesan manusia, dan semua bot memakai otak Fuzzy. Metode dan persona tiap bot dicatat di tabel `match_bots`
untuk analisis survei. Letak kodenya di [CODE_GUIDE.md](CODE_GUIDE.md#otak-bot-di-kode).

### Tiga tahap

1. **NLU (IndoBERT).** Satu model dipakai bersama semua bot dan hasilnya disimpan sekali per pesan. Model 1 membaca
   intent (`offend`, `defend`, `neutral`); Model 2 membaca target per pemain dengan 12 chat sebelumnya sebagai
   konteks. Karena nama pengguna bebas (mis. `tester`, `andy123`), nama pemain diganti nama yang dikenal model sebelum
   intent dibaca; tanpa itu tuduhan singkat seperti "curiga sama tester" terbaca netral. Untuk pesan netral, pemain
   yang disebut namanya menjadi target. Tanpa folder model, otak bot gagal dimuat: bot tidak chat dan hanya memakai
   aksi cadangan engine.
2. **Penalaran (Fuzzy Mamdani).** Bukti publik per pemain dihitung dari ingatan bot. [FUZZY 1] menilai pemain:
   kecurigaan dari sudut pandang warga, ancaman dan kambing hitam untuk Hitman. [FUZZY 2] memilih tindakan per sesi:
   Tribunal (vote), Diskusi (chat), dan Aksi Malam (Gag, Hostage, Guard, Peek). Hasilnya rencana chat, vote, dan aksi
   rahasia.
   - Bot Hitman membaca hasil Hostage tim dari server (`me.syndicate_hostages`), jadi tahu pasti korban yang berhasil
     dan target yang dijaga Spy; bila hasil itu tidak ada, pengumuman Hostage di roster dipakai.
   - Semua bot membaca korban Hostage dari roster publik (`players[].hostage`, `hostage_round`). Korban pasti warga:
     kecurigaan 0, tidak di-vote, tidak dijaga atau di-Peek, tidak disandera ulang, dan tidak dibela lewat chat karena
     statusnya sudah diumumkan. Pemain yang diam tanpa pengumuman tidak dianggap korban.
   - Bot Hitman meninggalkan target yang Hostage-nya sudah gagal dua kali sepanjang pertandingan (kemungkinan terus
     dijaga Spy) selama masih ada target lain. Tanpa aturan ini, sebagian pertandingan semua bot macet tanpa akhir.
   - Bot membaca ulang seluruh suara Tribunal di setiap langkah dan baru menguncinya saat fase berganti, jadi suara
     yang dibatalkan tidak dianggap bukti.
3. **NLG (penulis kalimat).** Rencana menjadi kalimat lewat **rantai prioritas** penulis LLM, lalu templat:
   - Jalur: OpenRouter (key di Konfigurasi AI) dan LLM sendiri lewat link (URL tunnel di Konfigurasi AI, mis. Ollama
     di Docker; dikenali sebagai Ollama atau server kompatibel OpenAI). Urutan dan jalur aktifnya diatur di panel
     **Otak NPC** (nilai awal `NPC_WRITER_ORDER`).
   - Model OpenRouter: bawaan kode `qwen/qwen3-14b`; produksi memakai `google/gemini-2.5-flash` yang dipilih di panel
     Otak NPC.
   - Tiap jalur dicek saat otak dimuat, saat konfigurasi berubah, atau lewat tombol **Tes koneksi semua prioritas**.
     OpenRouter dicek dengan key, model, lalu satu pesan pendek dengan batas token yang sama seperti saat bermain, agar
     saldo kurang langsung ketahuan; link dicek lewat daftar modelnya.
   - Jalur yang ditolak (401/403/402/404) dilewati sampai dicek ulang. Yang gagal sementara (429, error server,
     timeout) diistirahatkan 30 detik, berlipat dua bila gagal lagi (maksimal 5 menit).
   - Satu permintaan ke LLM dibatasi 20 detik. Percobaan kedua hanya dilakukan bila percobaan pertama selesai sebelum
     20 detik. Menulis satu kalimat dibatasi 25 detik; lewat dari itu, templat yang dipakai.
   - Penulis tidak menerima role asli bot. Setiap kalimat diperiksa aturan (tidak mengaku bot atau AI, tidak
     membocorkan role atau aksi, target disebut), lalu langsung dikirim; IndoBERT baru membacanya sesudah terkirim.
     Semua jalur gagal atau tanpa key → templat bervariasi sesuai persona. Jalur yang menulis dicatat di jejak
     (`penulis`).
   - Prompt memuat chat yang memicu kalimat (tuduhan, suara Tribunal, atau pertanyaan ke bot) dan kalimat bot itu
     sebelumnya, tanpa contoh kalimat templat, jadi bot menanggapi kejadian nyata dan boleh menyapa penuduh atau
     penanyanya. Kalimat LLM yang hanya parafrase tipis dari kalimat yang baru terdengar (kemiripan ≥ 0,75) ditolak
     lalu ditulis ulang.
   - Pembacaan ulang IndoBERT sebelum kirim diarsipkan pada 4 November 2026 karena lebih lama dari LLM-nya (median
     5,7 detik, p95 21 detik); arsipnya di luar repo, `../arsip_validasi_nlg_2026-11-04/`.

### Jadwal dan giliran bicara

- Bot melangkah setiap `NPC_STEP_SECONDS` (bawaan 3 detik), digeser sedikit per bot agar tidak serentak.
- Chat yang memanggil bot (target netral dari IndoBERT, atau nama/panggilan yang ditulis) atau menuduhnya membuat
  langkah bot itu dijadwalkan segera, minimal 1 detik dari langkah sebelumnya. Bot menjawab pertanyaan langsung
  sekali per panggilan, tetap lewat jatah, jeda, dan lantai bicara.
- Vote dan aksi rahasia diterapkan begitu diputuskan. Kalimat melewati **lantai bicara**: dalam satu pertandingan
  paling banyak 3 bot (`LANTAI_MAKS`) menyusun dan "mengetik" bersamaan, jadi permintaan ke LLM dikirim paralel. Bot
  tidak ikut menulis bila bot lain sedang menulis rencana kembar (intent dan target sama). Rencana chat yang dibuat
  sebelum chat bot lain masuk dibatalkan, lalu bot memutuskan ulang dengan chat terbaru. Rencana yang ditunda tetap
  tercatat di panel beserta masukan NLG-nya. Chat manusia tidak pernah ditahan.
- Selama menulis, kartu bot menampilkan awan berpikir 🤔 (`players[].thinking`); awan hilang begitu kalimatnya muncul.
- Kiri bawah kartu bot yang masih hidup menampilkan huruf tahap langkah terakhirnya (`players[].tahap`): **I**
  snapshot (input) sudah diterima, **L** logika dan penyusunan kalimat sedang berjalan, **O** output atau aksi
  selesai. Langkah yang gagal atau timeout tetap di **L** sampai langkah berikutnya. Bot melangkah di setiap fase apa
  pun role-nya, jadi huruf ini tidak membocorkan role.
- Bot tidak ikut bertanya bila pemain lain baru saja bertanya, tidak menjadi suara ketiga yang mengulang tuduhan atau
  pembelaan yang sama di fase itu (anti-gema), dan tidak mengulang kalimat yang baru muncul di room.
- Bot tidak menunggu manusia bicara: satu bot membuka diskusi, dan bila ruangan hening (tidak ada chat selama ≥
  max(15 detik, 20% durasi fase), sekitar 24 detik di siang standar 6 pemain) bot boleh memancing percakapan lagi atau
  mengajak pemain yang belum bicara. Bot tetap tidak menuduh tanpa bukti.
- Keputusan diterapkan hanya bila ronde dan fase belum berganti; aksi yang ditolak engine tidak mengubah state. Begitu
  otak memegang fase tertentu, "tunggu" atau abstain miliknya dihormati; aksi cadangan acak engine hanya untuk bot yang
  otaknya gagal.
- Jadwal bot dan simulasi panel menghitung lama fase lewat `Match.phase_length()`, jadi waktu tambahan tidak membuat
  fase tampak mundur.

### Aturan bot ringkas

Aturan ini berlaku sejak rombak otak Fase 1–9 (November 2026) dan mengikuti aturan permainan 3 November 2026.
Rinciannya ada di notebook `npc_fuzzy`, bagian Strategi per Role.

- **Chat siang dan Tribunal.** Bot memilih satu dari lima tindakan, masing-masing dengan jenis: `bela_diri` dan
  `jawab` (reaktif), `tuduh`, `bela_orang`, dan `tanya_info` (inisiatif), atau `tunggu`. Urutannya: ungkap hasil Peek
  Hitman → `bela_diri` → `jawab` → inisiatif bernilai tertinggi, minimal 40 → gali tersangka sebagai cadangan →
  `tunggu`. Jatah inisiatif 3 per siang dan 2 per Tribunal; reaktif paling banyak 8 dan 5. Satu pemicu dibalas sekali,
  dan pemicu baru dari orang yang sama menunggu 12% durasi fase. Bot tidak mengulang tuduhan atau pembelaan yang sudah
  disuarakan dua orang lain, kecuali klaim Stalker. Klaim Stalker sendiri (hasil Peek Hitman atau Peek bersih) paling
  banyak sekali per ronde: di Tribunal sesudah klaim siang, bot mengajak atau menjelaskan vote, atau membela tanpa
  menyebut Peek. Klaim Peek menyebut malam Peek yang sebenarnya; "semalam" hanya untuk malam terakhir.
- **Buka role** paling banyak sekali per game, hanya saat terdesak (porsi suara ke bot ≥ 0,3, tekanan ≥ 0,5, atau
  warga hampir kalah). Spy membawa bukti Guard semalam, dan Stalker membawa hasil Peek. Selain itu, bot membela diri
  dengan persuasi (terlalu awal, bahaya salah vote), menunjuk tersangka lain, atau sangkalan biasa. Hitman mengaku
  Civilian, atau Spy dengan Guard palsu saat risikonya tinggi.
- **Tuduhan.** Warga hanya menuduh dengan bukti: kecurigaan ≥ 0,40 dan alasannya bukan sekadar "banyak yang
  menuduh". Hitman menyerang korban Gag, balik menuduh penuduhnya, atau memelintir bukti publik; setiap jenis yang
  syaratnya cocok dinilai, dan yang nilainya tertinggi dipakai. Sekali per game, saat sudah dicurigai, Hitman mengaku
  Peek palsu dengan malam yang mungkin bagi Stalker (Peek tiap dua malam: malam 1, 3, 5, ...). Klaim role dari pemain
  yang sudah terbukti Hitman (dieksekusi atau keluar sebagai Hitman, atau hasil Peek bot) dianggap bohong, juga
  sesudah ia mati.
- **Tribunal.** `tanya_info` hanya untuk klaim bentrok dan gali tersangka. Bot boleh sekali mengajak vote (ajak pindah
  saat waktu tambahan, ajak menyatukan suara, atau menjelaskan vote), kecuali suaranya hasil paksa.
- **Gag** (Hitman, siang) selalu terpakai. Warga dengan ancaman ≥ 0,7 langsung di-Gag bila tidak ada rekan manusia
  yang hidup. Sebelum 60% siang, yang di-Gag hanya warga yang sudah bicara dengan nilai ≥ 60. Sesudah 60% siang, Gag
  wajib.
- **Vote warga.** Urutannya: hasil Peek Hitman → vote langsung; kesiapan ≥ 75 → langsung; sebelum separuh Tribunal →
  menunggu; kesiapan ≥ 45 → vote; ≥ 2 suara dan pemimpinnya dicurigai ≥ 0,35 → ikut. Saat warga kritis
  (`warga_terdesak` ≥ 0,75, `PAKSA_VOTE_KRITIS = True`), bot memaksa vote ke tersangka layak teratas. Bila semua
  nilainya sama, target diacak stabil per bot, dan pemain yang dibersihkan pengaku Stalker dilewati. Selain itu bot
  abstain. Vote warga tidak pernah ke korban Hostage atau pemain yang pasti baik.
- **Vote Hitman.** Hitman tidak pernah membuka vote. Ia ikut memilih rekan yang pasti dieksekusi, dan menyamakan suara
  pesaing terkuat saat dirinya atau rekannya memimpin. Bila tidak terdesak, ia menunggu sampai separuh Tribunal. Tanpa
  suara warga ia abstain; bila sudah ada, ia ikut pemimpin warga yang layak, atau memilih kambing hitam teratas.
- **Waktu tambahan seri.** Bot yang sudah vote menilai ulang sekali. Warga pindah hanya ke target layak yang
  kecurigaannya lebih tinggi; Hitman memakai aturan votenya sendiri, termasuk mempertahankan seri.
- **Malam.** Aksi malam selalu terpakai bila ada target. Bot terkunci 15 detik (mode cepat 10 detik) sebelum malam
  habis, sedangkan manusia boleh mengganti pilihan sampai waktu habis.
  - **Hostage:** saat terkunci, mengikuti Hitman manusia yang sudah memilih; selain itu mengikuti rekan bot yang sudah
    memilih, atau memilih warga dengan ancaman × (1 − 0,5 × jejak tuduhan) tertinggi. Seri diacak stabil per bot dan
    ronde.
  - **Guard:** diri sendiri bila role sudah terbuka dan bot masih diserang ronde ini. Selain itu, orang yang diyakini
    baik (rekan Spy, atau kecurigaan < 0,3) yang paling terancam, menghindari target rekan Spy; bila tidak ada, diri
    sendiri. Target sama boleh berulang, dan bot Hitman tidak menganggap target yang semalam dijaga pasti aman
    disandera malam ini. Bot yang belum terkunci pindah bila Spy manusia sudah menjaga target yang sama; antarbot, Spy
    dengan nama yang lebih akhir yang pindah.
  - **Peek:** pemain yang belum diperiksa, belum pasti baik, dan bukan korban, dengan nilai sistem `intip` tertinggi.
    Bila semua terlewat, Peek ke pemain hidup mana pun.
- **Chat tim** (Hitman dan Spy) hanya bila ada rekan manusia yang hidup dan tidak disandera, paling banyak 3 pesan
  per malam. Isinya target pilihan bot dan alasannya, setuju atau berbeda dengan pilihan rekan, atau pemberitahuan
  pindah target. Kalimat ditulis LLM atau templat tanpa IndoBERT. Isi chat tim tidak mengubah target.

### Metode yang diarsipkan

Utility AI dan Behavior Tree pernah dipakai bergantian dengan Fuzzy, lalu diarsipkan pada 3 November 2026 di luar repo,
di `../arsip_bt_utility_2026-11-03/` (commit terakhir yang memuat keduanya: `2d0e9b9`; cara menariknya kembali ada di
README folder itu). Data lama di `match_bots`, `checker_traces`, dan survei boleh tetap memuat nilai metode itu, dan
panel tetap bisa membukanya.

## Keseimbangan komposisi

Target: warga menang 40–60% di setiap ukuran room. Semua angka di bagian ini berasal dari bot melawan bot, jadi hanya
indikasi untuk pertandingan manusia. Komposisi cukup diubah di satu tempat (`KOMPOSISI_PERAN`) bila data pertandingan
manusia menunjukkan hal lain.

### Cara mengukur

- Skrip `backend/tests/simulasi/simulasi_keseimbangan.py` (cara menjalankan di
  [CODE_GUIDE.md](CODE_GUIDE.md#simulasi-keseimbangan-dan-uji-ab)).
- Semua kursi bot melawan engine asli, label NLU sempurna, pengumuman jumlah Hitman tersisa aktif, 6 langkah keputusan
  per fase (dekat dengan runtime, karena bot melangkah tiap `NPC_STEP_SECONDS`), 200 pertandingan per ukuran dengan
  seed tetap.
- Aturan memilih komposisi: bila ada komposisi dengan ≥ 2 Hitman yang win rate warganya 40–60%, dipilih yang paling
  dekat 50%. Jumlah Hitman dan Spy tidak boleh turun saat peserta bertambah, dan 4–6 pemain tetap satu Hitman.

### Angka sekarang (7 November 2026)

Tabel di [Ruangan dan role](#ruangan-dan-role) diukur pada 7 November 2026 dengan otak Fuzzy saja, sesudah tiga
perbaikan bot hari itu: semua jenis tuduh Hitman yang cocok dinilai, klaim Peek menyebut malam yang mungkin, dan klaim
Stalker tidak diulang di ronde yang sama. Aksi ilegal 0 dan pertandingan tanpa pemenang 0.

- Dibanding 6 November (`be1bf7f`, seed sama), 4–6 dan 10 pemain tidak berubah, sedangkan 7/8/9 pemain bergeser
  +2,5/−1,5/+1,0 poin (selisih berpasangan).
- **7 pemain (60,5%) sedikit di atas batas target di 200 game**, jadi diukur ulang dengan 1000 game (200 seed pertama
  sama): 55,1% ± 3,1. Sebelum perbaikan angkanya 54,6% ± 3,1 (selisih berpasangan +0,5 ± 1,1; 19 game berbalik ke
  warga, 14 ke Hitman). Komposisi tidak diubah.
- **10 pemain (59,5%) tetap dekat batas atas target.**
- Sebelum rombak otak (Fuzzy saja, `1f11806`) angkanya 40,0/65,5/70,0/25,0/28,0/41,0/46,5% untuk 4–10 pemain.

### Uji A/B paksa vote

`PAKSA_VOTE_KRITIS` aktif lawan mati, Fuzzy saja, 200 game per ukuran, 6 langkah per fase, seed sama untuk kedua
kebijakan. Diukur 6 November 2026 di `4a5e48f`, sebelum perubahan pemutus seri Hostage dan klaim pengaku yang terbukti
Hitman. Skrip pengulang: `backend/tests/simulasi/uji_ab_vote.py`.

| Warga menang | 4 | 5 | 6 | 7 | 8 | 9 | 10 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Tanpa paksa | 65,0% | 58,0% | 54,0% | 39,5% | 37,0% | 40,0% | 39,5% |
| Paksa saat kritis | 49,5% | 48,0% | 54,5% | 55,5% | 53,5% | 50,5% | 54,0% |

Tanpa paksa, 4 pemain di atas 60% dan 7–10 pemain di 40% atau lebih rendah. Dengan paksa, semua ukuran berada di
48–56%. Karena itu **paksa vote tetap aktif**. Alasannya sejalan dengan aturan: warga yang kritis lalu abstain
membiarkan satu suara lain, yang bisa milik Hitman, menentukan eksekusi.

Riwayat: uji lama (6 pemain, kebijakan `PAKSA_VOTE_BUKTI_LEMAH` tanpa syarat kritis, metode campuran masih ada)
memilih Fuzzy tanpa paksa (paksa → tanpa: 26 Oktober 50,5% → 58,5%; 1 November 52,0% → 60,0%).

### Riwayat pengukuran

Pengukuran sebelum 3 November 2026 memakai **metode campuran**: Fuzzy, Utility AI, dan Behavior Tree bergiliran
sebagai otak bot. Urutan di bawah dari yang terbaru.

- **1 November 2026** (sesudah korban Hostage diumumkan ke semua pemain dan bot Hitman pindah target sesudah Hostage
  ke target yang sama gagal dua malam berturut-turut): komposisi yang sama memberi 49,5/65,5/71,0/46,5/43,5/50,0/58,0%
  untuk 4–10 pemain. Komposisi tidak berubah: 7–10 pemain tetap di 40–60%, tanpa pertandingan yang macet. Uji A/B
  kebijakan vote juga diulang dan arahnya sama (Fuzzy tanpa paksa 60,0% vs paksa 52,0%; Utility AI paksa 81,0% vs
  30,5%; Behavior Tree paksa 97,5% vs 61,5%), jadi kebijakan per metode tidak berubah.
- **27 Oktober 2026** (sesudah bot Hitman tidak lagi membuka vote dan bot Utility AI memakai paksa vote): 7–10 pemain
  pertama kali semuanya di 40–60%: 47,5/42,5/56,5/59,5%; 4–6 pemain 47,5/61,5/70,0%. Pembanding: 7 pemain 1/1/1 64,0%
  dan 2/1/1 36,5%; 8 pemain 2/1/1 40,0%; 9 pemain 2/1/1 46,0% (Spy turun, tidak boleh) dan 3/2/1 19,0%; 10 pemain
  2/1/1 53,0% (Spy turun, tidak boleh), 3/2/1 27,5%, 3/1/1 27,0%.
- **23 Oktober 2026** (aturan baru: siang → Tribunal → malam, ronde 1 tanpa Tribunal, Hostage tanpa aksi, Tribunal
  +30 detik; 6 langkah per fase):
  - **7 pemain** pindah dari 1/1/1 (warga menang 75,0%) ke 2 Hitman + 2 Spy (42,0%); 2/1/1 hanya 26,0%.
  - **8 pemain** tetap 2/2/1 (48,5%; 2/1/1: 42,0%).
  - **9 dan 10 pemain** tetap 2/2/1 walau warga menang 64,5% dan 67,0%. Satu-satunya kandidat di 40–60% adalah 2/1/1
    (57,0% dan 59,5%) yang menurunkan jumlah Spy, sedangkan tiga Hitman terlalu kuat (9: 3/2/1 15,0%; 10: 3/2/1 29,5%,
    3/1/1 17,0%).
- **Seleksi awal** (urutan lama siang → malam → Tribunal). Bila tidak ada komposisi ≥ 2 Hitman di 40–60%, ukuran itu
  tetap satu Hitman.
  - Pembanding yang ditolak: di 7 pemain dua Hitman + satu Spy 26,0% dan dua Hitman + dua Spy 37,5% (keduanya di bawah
    40%, jadi tetap satu Hitman); dua Hitman + satu Spy di 8 dan 9 pemain 37,5% dan 39,0%; tiga Hitman di 9 dan 10
    pemain 4–16%; di 10 pemain dua Hitman + satu Spy 46,5% lebih dekat 50%, tetapi Spy tidak boleh turun dari dua
    (9 pemain), jadi dipilih dua Spy (57,0%).
  - Tanpa pengumuman jumlah Hitman, dua Hitman terlalu kuat: warga hanya menang 21–32% di 8–10 pemain.
  - Seleksi diulang dengan 6 langkah keputusan per fase, karena hasil 9–10 pemain sensitif terhadap jumlah langkah.
    Tabel tetap: 8 dan 9 pemain seimbang (53,5% dan 52,0%). Di 10 pemain tidak ada kandidat di 40–60% (2/2/1: 64,5%;
    2/1/1: 61,5% dan Spy tidak boleh turun; 3/2/1: 29,0%; 3/1/1: 15,5%), jadi dipilih yang paling dekat 50% dan sesuai
    aturan monoton: 2/2/1, condong ke warga. 7 pemain sengaja tetap satu Hitman walau condong ke warga (71%), karena
    dua Hitman hanya 32–37,5%.

# Panel dan pengujian AI — 24 September 2026

## Perubahan

- Konfigurasi dan pengujian AI ditata dua kolom di desktop, satu kolom di layar kecil.
- Manajemen user memakai tabel dengan tombol aksi berjarak, form tambah dua kolom, dan dialog terpisah untuk edit, reset password, serta konfirmasi hapus. Akun Google tidak mendapat tombol reset password aplikasi.
- Checker menampilkan ringkasan status, total waktu, waktu LLM, provider/model, serta HTTP. Input/output langsung terlihat; analisis, request, response, prompt, dan JSON lengkap bisa dibuka sesuai kebutuhan.
- Trace baru mencatat payload request sebenarnya dan respons terpilih (output, status, usage jika tersedia). Header autentikasi dan body error upstream tidak dicatat. Batas ukuran payload diterapkan; trace lama menampilkan “tidak tercatat”, bukan waktu perkiraan.
- Request bersamaan memakai konteks diagnostik terpisah. Respons UI dari sesi lama diabaikan. Hasil tes sebelumnya dibersihkan setelah konfigurasi berubah.
- Respons validasi endpoint panel/user tidak mengembalikan input password atau konteks input. Logout gagal tidak dinyatakan berhasil.

## Checker room: penjelasan keputusan bot (30 September 2026)

Menu **Checker** sekarang menjawab "bot ini siapa, membaca apa, menalar bagaimana, lalu memutuskan apa":

- **Ringkasan room**: status (Live/Selesai/Lobby/Arsip), ronde dan fase, komposisi role, jumlah manusia, lalu tabel bot (role, metode, persona, status, keputusan terakhir). Klik nama bot untuk memfilter linimasa; filter juga ada di pilihan **Tampilkan**.
- **Linimasa jejak**: setiap jejak otak menampilkan bot, metode, role, ringkasan keputusan (chat/vote/aksi), ronde/fase, dan tanda bila ditolak engine atau chat ditunda lantai bicara. Jejak lain (chat manusia, mode LLM) memakai laporan pipeline lama.
- **Kartu keputusan** bertab:
  - **Keputusan**: rencana chat/vote/aksi, yang diterapkan ke engine, kalimat akhir, ringkasan penalaran, dan alasan.
  - **Parameter**: 5 tersangka teratas beserta fitur bukti dan nilai antara metode, siapa yang menuduh/membela, tabel khusus role (ancaman bagi Hitman, kebutuhan Guard bagi Spy), konteks permainan, dan pengetahuan pasti bot.
  - **Penalaran**: Fuzzy (derajat keanggotaan rendah/sedang/tinggi, aturan yang menyala dan kekuatannya, keluaran centroid, ambang, hierarki kecurigaan), Utility AI (pertimbangan, bobot, utilitas per kandidat, komponen noisy-OR), atau Behavior Tree (jalur syarat/aksi yang dievaluasi dengan status ✓/✗, bendera merah dan poin).
  - **NLG**: sumber kalimat (LLM/templat/cadangan), jalur penulis LLM, persona, hasil validasi aturan dan IndoBERT (intent/target terbaca), pelanggaran, dan percobaan.
  - **Teknis**: laporan dan JSON lengkap jejak.
- **Legenda** "Arti parameter dan cara membaca tiap metode" menjelaskan setiap kolom; judul kolom bergaris titik punya keterangan saat disorot.

Data penjelasan dibuat `services/npc_brain/penjelasan.py` di thread keputusan (`BrainRuntime.langkah`) dari hasil `putuskan()` notebook, jadi angka yang tampil adalah angka yang benar-benar dipakai bot. Ukurannya dibatasi ≤ 12 KB per jejak (rata-rata 3,6–5 KB pada simulasi 6–10 bot); bagian yang gagal dibuat diganti catatan tanpa mengganggu permainan. Daftar jejak (`GET /api/panel/checker/{code}`) hanya membawa `ringkas` dan ringkasan room; penjelasan lengkap diambil saat jejak dibuka (`GET /api/panel/checker/{code}/jejak/{id}`) dan disimpan di cache browser, sehingga auto-refresh 5 detik tetap ringan. Penjelasan memuat role bot, sehingga hanya endpoint panel yang mengembalikannya; daftar jejak development `/api/admin/rooms/{code}/traces` membuangnya.

## Menjalankan tes dari panel

Login `/panel`, buka **Konfigurasi AI**, simpan provider yang dipilih, lalu gunakan **Uji skenario game**. Pilih diskusi, Tribunal, atau malam; masukkan teks; tekan **Jalankan pengujian**.

`POST /api/panel/test-ai` menerima:

```json
{
  "scenario": "discussion",
  "message": "Aku melihat Pemain_B menghindari pertanyaan. Apa alibimu?"
}
```

Tes memakai satu request provider dengan konfigurasi server pada awal request, dibatasi 35 detik. Ini bukan pertandingan nyata: tidak mengirim chat ke peserta atau mengubah room. SVM/fuzzy dianalisis sebagai pendamping; prompt keputusan NPC memakai aturan, informasi privat NPC, aksi legal, dan chat publik sesuai jalur pertandingan. SVM tidak diperlakukan sebagai pengetahuan role lawan.

Hasil memisahkan provider yang terhubung, output yang tersedia, dan keputusan yang valid. HTTP 200 saja bukan bukti AI menghasilkan keputusan yang dapat digunakan.

## Hasil provider nyata

Pengujian memakai konfigurasi lokal yang tersedia (OpenRouter, `qwen/qwen3-14b`), bukan konfigurasi database deployment. Runtime Docker memakai scikit-learn 1.9.0, sesuai artifact SVM. Tidak mengubah akun atau database pengguna.

Percobaan awal menerima HTTP 200 tetapi output kosong, `finish_reason=length`, setelah 6,05 detik. Adapter menambahkan `/no_think` di akhir prompt Qwen selain flag `reasoning.enabled=false`, mengikuti [dokumentasi Qwen](https://qwenlm.github.io/blog/qwen3/). Hasil tiga skenario setelah perbaikan:

| Skenario | Total proses | LLM | Keputusan | Valid |
| --- | ---: | ---: | --- | --- |
| Diskusi | 1.951 ms | 1.836 ms | `wait`, pesan alibi | Ya |
| Tribunal | 1.361 ms | 1.340 ms | `vote`, target `Pemain_A` | Ya |
| Malam | 1.540 ms | 1.518 ms | `guard`, target `Pemain_B`, pesan kosong | Ya |

Contoh output diskusi yang benar-benar diterima:

```json
{
  "action": "wait",
  "target": null,
  "message": "Aku cuma lewat dekat Pemain_B tadi, tapi tidak terlalu lama. Mungkin dia sedang menutupi sesuatu."
}
```

Input yang sama diklasifikasikan SVM sebagai `accusing`, bobot agresivitas 90, silence 20 (konstanta), dan skor fuzzy 50 (`SUS`). Output model merupakan ucapan dalam game, bukan fakta terverifikasi tentang pemain.

Ini masing-masing satu sampel; bukan benchmark throughput, jaminan latensi, atau evaluasi kualitas strategi. Tes tidak menguji Ollama nyata pada sesi ini. Rekaman lengkap lokal: `tmp/panel-ai-live-scenarios.json` (diabaikan Git).

## Verifikasi

- Suite backend termasuk autentikasi, akun, aturan game, diagnostik provider, isolasi request paralel, dan redaksi password.
- `node --test backend/tests/panel_ui.test.mjs`: rendering aman, respons basi setelah logout, kegagalan logout, dan dialog akun.
- Browser desktop dan lebar 390 px: login, hasil AI, checker, edit akun uji, logout. Tidak ada error JavaScript; checker mobile tidak mengalami overflow horizontal.
- Browser menggunakan server preview loopback dengan akun/data tiruan. Hasil AI pada preview merupakan rekaman panggilan nyata, bukan panggilan baru setiap klik. Operasi database/login produksi belum diuji end-to-end karena stack game sedang tidak berjalan.

Perubahan berada di source lokal; backend perlu restart/deploy agar endpoint dan trace baru tersedia. Jangan restart saat pertandingan aktif tanpa mempertimbangkan state game yang masih berada di memori.

# ai-docker: LLM penulis kalimat bot untuk VM

Folder ini menjalankan **Qwen3** di Docker pada laptop, lalu membukanya ke internet lewat Cloudflare Tunnel. Backend
game di VM memakainya sebagai jalur **"LLM sendiri lewat link"** (`tautan`) di rantai penulis kalimat bot. Folder ini
terpisah dari `docker-compose.yml` utama; untuk Ollama lokal biasa, lihat [OLLAMA.md](../OLLAMA.md).

```text
VM backend ──HTTPS + Bearer token──▶ Cloudflare tunnel ──▶ gerbang (nginx, cek token) ──▶ ollama
```

## Model

Dua model disiapkan. Model yang dipakai bot dipilih di panel → **Otak NPC** → **Model LLM link**.

| Model | Kapan dipakai |
| --- | --- |
| `qwen3:4b-instruct` | Disarankan. Diukur 1–2 detik per kalimat lewat tunnel (RTX 3060 6 GB), tanpa mode berpikir. |
| `qwen3:14b` | Diukur 6–9 detik per kalimat sesudah termuat. Model 10 GB ini tidak muat di VRAM 6 GB (64% jalan di CPU). Memuat pertama kali sekitar 80 detik. Qwen3 tidak punya versi 12B; ini ukuran terdekat. |

## Isi folder

| File | Isi |
| --- | --- |
| `jalankan.bat` | Nyalakan semuanya, tunggu model siap, uji link dari internet, lalu kirim link + token ke backend |
| `lihat-link.bat` | Tampilkan link dan token yang sedang aktif (tanpa menyalakan ulang), lalu kirim lagi ke backend |
| `uji-waktu.bat` | Ukur lama NLU → logika fuzzy → NLG/LLM per bot lewat simulasi panel; CSV di `communicationfolder/uji-waktu-<tanggal>/` |
| `hentikan.bat` | Matikan LLM dan tunnel (model tetap tersimpan) |
| `skrip/` | Skrip PowerShell yang dipanggil `jalankan.bat`, `lihat-link.bat`, dan `uji-waktu.bat`. `kirim-link.ps1` mengirim link ke backend; `bersama.ps1` berisi fungsi bersama (`.env`, link tunnel, login panel) |
| `docker-compose.yml` | Service `ollama`, `model` (unduh sekali), `gerbang`, `tunnel` |
| `docker-compose.gpu.yml` | Tambahan GPU NVIDIA, dipakai otomatis bila `nvidia-smi` ada |
| `gerbang.conf.template` | Hanya meneruskan `/api/tags`, `/api/show`, `/api/chat`, `/api/version` dengan token yang benar |
| `.env.example` | Contoh isi `.env` |
| `.env` | Dibuat otomatis: `LLM_TOKEN` acak, `LLM_MODELS`, dan login panel (`PANEL_USERNAME`, password terenkripsi DPAPI). Opsional `BACKEND_URL` (bawaan `https://backendthesis.andylabs.site`). Tidak masuk Git |

Hasil lama `uji-waktu.bat` diukur saat bot masih memakai metode campuran (Fuzzy, Utility AI, dan Behavior Tree), jadi
belum berlaku untuk otak Fuzzy sekarang.

## Pemakaian

1. Buka Docker Desktop, lalu klik dua kali `jalankan.bat`.
   - Model yang belum ada diunduh ke volume `silent_terror_ai_model`, sekitar 2,5 GB untuk 4B dan 9 GB untuk 14B.
   - Pertama kali, skrip menanyakan username dan password **panel admin**. Keduanya disimpan di `.env` (password
     terenkripsi DPAPI, hanya bisa dibuka akun Windows ini) dan tidak ditanya lagi, kecuali login ditolak.
   - Di akhir, skrip mengirim link + token ke backend lewat API panel (sama dengan mengisi **Konfigurasi AI** lalu
     Simpan), menjadikan "LLM sendiri lewat link" prioritas pertama di rantai penulis **Otak NPC** (jalur lain yang
     aktif tetap menjadi cadangan), lalu menampilkan hasil tes koneksi dari VM. Provider dan model yang sudah dipilih
     tidak diubah.
2. Pilih model link di panel → **Otak NPC** → **Model LLM link** (`qwen3:4b-instruct` cepat, `qwen3:14b` lebih
   pintar). Pilihan "Bawaan" memakai model dari Konfigurasi AI. Sesudah pindah ke `qwen3:14b`, tunggu sekitar 1–2
   menit sampai model termuat, lalu klik **Tes koneksi semua prioritas** lagi.
3. Bila pengiriman gagal (misalnya backend mati), link sudah ada di clipboard: tempel manual di panel →
   **Konfigurasi AI** lalu Simpan.

## Perlu diingat

- **Link berganti** setiap tunnel dinyalakan ulang, misalnya sesudah laptop restart atau `hentikan.bat`. Jalankan
  `jalankan.bat` (atau `lihat-link.bat` bila container masih jalan) supaya link baru terkirim. Token tetap sama selama
  `.env` tidak dihapus.
- Laptop harus tetap menyala dan Docker berjalan selama game dimainkan. Bila mati, bot memakai jalur berikutnya di
  rantai (mis. OpenRouter), lalu templat.
- Satu permintaan kalimat dibatasi 20 detik. Model besar yang lambat lebih sering jatuh ke jalur berikutnya atau ke
  templat.
- Tanpa token, link menjawab 401. Endpoint selain empat di atas (pull, delete, dan sebagainya) menjawab 404.
- Ini *quick tunnel* Cloudflare: gratis, tanpa akun, tanpa jaminan uptime. Untuk link tetap, perlu akun Cloudflare
  dan named tunnel.

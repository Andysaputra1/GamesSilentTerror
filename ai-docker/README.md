# ai-docker: LLM penulis kalimat bot untuk VM

Menjalankan **Qwen3** di Docker pada laptop, lalu membukanya ke internet lewat Cloudflare Tunnel. Backend game di VM
memakainya sebagai jalur **"LLM sendiri lewat link"** (`tautan`) di rantai penulis kalimat bot. Folder ini terpisah
dari `docker-compose.yml` utama.

```text
VM backend ──HTTPS + Bearer token──▶ Cloudflare tunnel ──▶ gerbang (nginx, cek token) ──▶ ollama
```

Dua model disiapkan. Model yang dipakai bot dipilih di panel → **Otak NPC** → **Model LLM link**:

| Model | Kapan dipakai |
| --- | --- |
| `qwen3:4b-instruct` | Disarankan. Diukur 1–2 detik per kalimat lewat tunnel (RTX 3060 6 GB), tanpa mode berpikir. |
| `qwen3:14b` | Diukur 6–9 detik per kalimat setelah termuat. Model 10 GB ini tidak muat di VRAM 6 GB (64% jalan di CPU). Memuat pertama kali sekitar 80 detik. Qwen3 tidak punya versi 12B; ini ukuran terdekat. |

| File | Isi |
| --- | --- |
| `jalankan.bat` | Nyalakan semuanya, tunggu model siap, uji link dari internet, tampilkan link + token |
| `lihat-link.bat` | Tampilkan link dan token yang sedang aktif (tanpa menyalakan ulang) |
| `hentikan.bat` | Matikan LLM dan tunnel (model tetap tersimpan) |
| `docker-compose.yml` | `ollama`, `model` (unduh sekali), `gerbang`, `tunnel` |
| `docker-compose.gpu.yml` | Tambahan GPU NVIDIA, dipakai otomatis bila `nvidia-smi` ada |
| `gerbang.conf.template` | Hanya `/api/tags`, `/api/show`, `/api/chat`, `/api/version` dengan token yang benar |
| `.env` | Dibuat otomatis: `LLM_TOKEN` acak dan `LLM_MODELS` (tidak masuk Git) |

## Pemakaian

1. Buka Docker Desktop, lalu klik dua kali `jalankan.bat`.
   - Model yang belum ada diunduh ke volume `silent_terror_ai_model`. Ukurannya sekitar 2,5 GB untuk 4B dan 9 GB untuk 14B.
   - Di akhir, skrip mencetak **Link** (juga disalin ke clipboard) dan **Token**.
2. Panel → **Konfigurasi AI**: pilih "LLM lokal · Ollama melalui tunnel", tempel link dan
   token, lalu Simpan. Token disimpan terenkripsi dan cukup diisi sekali; link perlu diisi
   ulang setiap kali tunnel berganti. Kolom token yang dikosongkan mempertahankan token lama.
3. (Opsional, cadangan) Token juga bisa ditaruh di VM sebagai `OLLAMA_TUNNEL_TOKEN=...` di
   `.env.azure`. Token dari panel selalu didahulukan.
4. Panel → **Otak NPC**:
   1. Aktifkan jalur "LLM sendiri lewat link".
   2. Klik **Tes koneksi semua prioritas**.
   3. Pilih model di **Model LLM link**, lalu Simpan.

   Pilihan "Bawaan" memakai model dari Konfigurasi AI (`qwen3:14b` di VM). Jalur Claude dan OpenRouter yang tidak punya key otomatis dilewati.
   Setelah pindah ke `qwen3:14b`, tunggu sekitar 1–2 menit sampai model termuat, lalu klik tes koneksi lagi. Tes pertama bisa gagal karena model masih dimuat.

## Perlu diingat

- **Link berganti** setiap tunnel dinyalakan ulang, misalnya setelah laptop restart atau `hentikan.bat`. Ulangi langkah 3–4. Token tetap sama selama `.env` tidak dihapus.
- Laptop harus tetap menyala dan Docker berjalan selama game dimainkan. Kalau mati, bot otomatis kembali ke templat.
- Setiap kalimat dibatasi 20 detik. Kalimat yang lebih lama jatuh ke templat, jadi model besar yang lambat bisa lebih sering memakai templat.
- Tanpa token, link menjawab 401. Endpoint selain empat di atas (pull, delete, dan sebagainya) menjawab 404.
- Ini *quick tunnel* Cloudflare: gratis, tanpa akun, tanpa jaminan uptime. Untuk link tetap, perlu akun Cloudflare dan named tunnel.

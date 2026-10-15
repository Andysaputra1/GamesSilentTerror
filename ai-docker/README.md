# ai-docker: LLM penulis kalimat bot untuk VM

Menjalankan **Qwen3 4B** (`qwen3:4b-instruct`) di Docker pada laptop, lalu membukanya ke internet lewat
Cloudflare Tunnel. Backend game di VM memakainya sebagai jalur **"LLM sendiri lewat link"** (`tautan`) di
rantai penulis kalimat bot. Folder ini terpisah dari `docker-compose.yml` utama.

```text
VM backend ──HTTPS + Bearer token──▶ Cloudflare tunnel ──▶ gerbang (nginx, cek token) ──▶ ollama (qwen3:4b-instruct)
```

| File | Isi |
| --- | --- |
| `jalankan.bat` | Nyalakan semuanya, tunggu model siap, uji link dari internet, tampilkan link + token |
| `lihat-link.bat` | Tampilkan link dan token yang sedang aktif (tanpa menyalakan ulang) |
| `hentikan.bat` | Matikan LLM dan tunnel (model tetap tersimpan) |
| `docker-compose.yml` | `ollama`, `model` (unduh sekali), `gerbang`, `tunnel` |
| `docker-compose.gpu.yml` | Tambahan GPU NVIDIA, dipakai otomatis bila `nvidia-smi` ada |
| `gerbang.conf.template` | Hanya `/api/tags`, `/api/show`, `/api/chat`, `/api/version` dengan token yang benar |
| `.env` | Dibuat otomatis: `LLM_TOKEN` acak dan `LLM_MODEL` (tidak masuk Git) |

## Pemakaian

1. Buka Docker Desktop, lalu klik dua kali `jalankan.bat`.
   - Pertama kali, model sekitar 2,5 GB diunduh ke volume `silent_terror_ai_model`.
   - Di akhir, skrip mencetak **Link** (juga disalin ke clipboard) dan **Token**.
2. Di VM, langkah ini cukup **sekali**. Tambahkan baris berikut ke `.env.azure`:

   ```dotenv
   OLLAMA_TUNNEL_TOKEN=<token dari jalankan.bat>
   ```

   Lalu buat ulang container backend:

   ```bash
   sudo docker compose --env-file .env.azure -f docker-compose.azure.yml up -d --force-recreate backend
   ```

3. Panel → **Konfigurasi AI**: pilih "LLM lokal · Ollama melalui tunnel", tempel link, lalu Simpan.
4. Panel → **Otak NPC**: pastikan jalur "LLM sendiri lewat link" aktif, lalu klik **Cek ulang penulis**.
   - Jalur Claude dan OpenRouter yang tidak punya key otomatis dilewati.
   - Untuk mengetes link, pakai tombol **Cek ulang penulis** ini, bukan "Cek AI" di Konfigurasi AI. Tombol itu tes chat lama dan selalu meminta `qwen3:14b`, padahal model itu sengaja tidak ada di sini.

## Perlu diingat

- **Link berganti** setiap tunnel dinyalakan ulang, misalnya setelah laptop restart atau `hentikan.bat`. Ulangi langkah 3–4. Token tetap sama selama `.env` tidak dihapus.
- Laptop harus tetap menyala dan Docker berjalan selama game dimainkan. Kalau mati, bot otomatis kembali ke templat.
- Backend VM meminta `qwen3:14b`. Karena link ini hanya punya model Qwen3 4B, backend otomatis memakai model sekeluarga itu.
- Pakai versi **instruct** (tanpa mode berpikir). `qwen3:4b` biasa berpikir dulu sebelum menjawab, sehingga bisa melewati batas 20 detik per kalimat.
- Ganti model lewat `LLM_MODEL` di `.env`. Jangan arahkan ke volume yang juga berisi `qwen3:14b`, karena backend akan memilih model 14B itu.
- Tanpa token, link menjawab 401. Endpoint selain empat di atas (pull, delete, dan sebagainya) menjawab 404.
- Ini *quick tunnel* Cloudflare: gratis, tanpa akun, tanpa jaminan uptime. Untuk link tetap, perlu akun Cloudflare dan named tunnel.

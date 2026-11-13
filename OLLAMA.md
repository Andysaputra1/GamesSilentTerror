# Ollama lokal

File ini menjelaskan cara menjalankan Ollama di Docker lokal dan memakainya sebagai penulis kalimat bot. Untuk membuka
LLM di laptop ke backend VM lewat tunnel, lihat [ai-docker/README.md](ai-docker/README.md). Langkah umum menjalankan
aplikasi ada di [README.md](README.md).

## Menjalankan

Ollama berjalan di container `shadow_ollama`. Pilih salah satu file Compose mandiri: `docker-compose.yml` untuk CPU
(termasuk Mac) atau `docker-compose.gpu.yml` untuk GPU NVIDIA. Jangan menjalankan keduanya bersamaan.

```sh
# CPU
docker compose up -d ollama ollama-models
docker compose logs -f ollama-models
docker compose exec ollama ollama list

# NVIDIA: pakai file GPU pada setiap perintah
docker compose -f docker-compose.gpu.yml up -d ollama ollama-models
docker compose -f docker-compose.gpu.yml logs -f ollama-models
docker compose -f docker-compose.gpu.yml exec ollama ollama list
```

| Alamat | Dari |
| --- | --- |
| `http://localhost:11435` | Host (hanya loopback 127.0.0.1, bukan jaringan publik) |
| `http://ollama:11434` | Container lain di jaringan Compose, termasuk backend |

- Kedua versi menjalankan Ollama di Docker, jadi Mac tidak perlu instalasi Ollama native. Versi CPU bisa jauh lebih
  lambat. Pastikan memori Docker cukup untuk model yang dipilih; model yang tidak muat bisa gagal, bukan hanya lambat.
- Service `ollama-models` menunggu server sehat, mengunduh model di `OLLAMA_MODELS_TO_PULL` yang belum ada, lalu keluar
  dengan kode 0. Model yang sudah ada dilewati. `.env.example` dan Compose mengunduh `qwen3:14b` saja.
- Model disimpan di volume `games_ollama_data` (`/root/.ollama`). `down`, `up`, restart, dan recreate mempertahankan
  model. **`docker compose down -v` menghapus volume ini beserta database.**
- Ollama hanya menyediakan inference, bukan training atau fine-tuning.

## Pengaturan

| Variabel | Dibaca | Arti |
| --- | --- | --- |
| `OLLAMA_MODELS_TO_PULL` | Container `ollama-models` | Daftar model yang diunduh, dipisah spasi (bawaan `qwen3:14b`) |
| `OLLAMA_CONTEXT_LENGTH` | Container `ollama` | Ukuran konteks (bawaan 2048) |
| `OLLAMA_KEEP_ALIVE` | Container `ollama` | Lama model tetap di memori sesudah request (bawaan `10m`) |
| `OLLAMA_MODEL` | Backend | Model jalur link: `4` = `qwen3:4b-instruct`, `8` = `qwen3:8b`, `14` = `qwen3:14b` (bawaan). Nilai lain ditolak. Model itu harus ada di `OLLAMA_MODELS_TO_PULL` |

Reservasi GPU NVIDIA hanya ada di `docker-compose.gpu.yml`. RTX 3060 Laptop pada mesin pengembang punya VRAM 6 GB,
jadi model 14B memakai sebagian RAM dan CPU; kecepatannya perlu diuji di mesin masing-masing. Bila 14B terlalu berat,
pakai 8B atau 4B, atau pakai OpenRouter.

## Penulis kalimat bot memakai Ollama

Penulis kalimat bot memakai **rantai prioritas** (panel menu **Otak NPC**): OpenRouter dan "LLM sendiri lewat link"
(`tautan`), lalu templat. Jalur link memakai URL dari panel **Konfigurasi AI**, atau `OLLAMA_BASE_URL` bila panel belum
menyimpan URL.

**Lokal.** Compose sudah mengisi `OLLAMA_BASE_URL=http://ollama:11434` untuk backend, jadi Ollama lokal langsung
menjadi jalur link. Buka panel **Otak NPC**, lalu klik **Tes koneksi semua prioritas**. Atur urutan jalur (▲▼) bila
jalur link ingin dipakai lebih dulu. Model jalur ini dipilih di **Model LLM link**; "Bawaan" memakai model dari
Konfigurasi AI atau `OLLAMA_MODEL`.

**Lewat tunnel** (mis. backend di VM). Cara tercepat `ai-docker/jalankan.bat` (Qwen3 + gerbang token + Cloudflare
tunnel). Cara manual dengan Ollama dari Compose utama:

1. Jalankan Ollama (lihat di atas) dan pastikan modelnya sudah diunduh.
2. Buka tunnel HTTPS ke port host, misalnya
   `cloudflared tunnel --url http://localhost:11435 --http-host-header localhost:11434`. Bila link menjawab 403,
   biasanya header host inilah yang kurang (Ollama menolak host asing).
3. Isi URL tunnel di panel **Konfigurasi AI** dan simpan. URL harus HTTPS dengan alamat publik. Bearer token tunnel
   diisi di kolom yang sama (tersimpan terenkripsi), atau lewat `OLLAMA_TUNNEL_TOKEN` sebagai cadangan.
4. Klik **Tes koneksi semua prioritas** di menu Otak NPC.

Backend mengenali Ollama (`/api/tags`, `/api/chat`) maupun server kompatibel OpenAI (`/v1/models`,
`/v1/chat/completions`). Bila model yang dipilih tidak ada di link, dipakai model sekeluarga (mis. `qwen3:8b` untuk
`qwen3:14b`) atau model pertama yang tersedia; panel menampilkan model yang benar-benar dipakai.

Satu permintaan kalimat dibatasi 20 detik. Model yang lambat di CPU lebih sering jatuh ke jalur berikutnya atau ke
templat. Bila jalur link gagal dan jalur OpenRouter aktif dengan key, kalimat ditulis lewat OpenRouter (berbayar);
nonaktifkan jalur itu di panel bila tidak diinginkan.

## `AI_PROVIDER` dan pemeriksaan status

`AI_PROVIDER` tidak memilih jalur penulis; rantai di panel Otak NPC yang menentukannya.

- `AI_PROVIDER=docker`: menu Konfigurasi AI terbuka di pilihan Ollama atau tunnel, dan `/app-status` memeriksa
  apakah model `OLLAMA_MODEL` tersedia (`ollama_ready`).
- `AI_PROVIDER=api`: menu Konfigurasi AI terbuka di pilihan OpenRouter, dan `/app-status` melaporkan model OpenRouter.

Sesudah mengubah environment, recreate backend (restart saja tidak memuat environment Compose baru):

```sh
docker compose up -d ollama ollama-models
docker compose up -d --force-recreate ai-engine
docker compose restart gateway
```

Untuk mesin NVIDIA, pakai awalan `docker compose -f docker-compose.gpu.yml` agar Ollama tetap mendapat GPU; jangan
memperbarui Ollama NVIDIA dengan file CPU secara tidak sengaja. Restart gateway memperbarui alamat container backend
bila alamatnya berubah. Periksa http://localhost:8000/app-status: `ai_provider`, `ai_model`, dan `ollama_ready`.

Referensi: [Ollama Docker](https://docs.ollama.com/docker).

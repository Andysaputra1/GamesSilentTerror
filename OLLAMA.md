# Ollama lokal

Server Ollama berjalan di container `shadow_ollama`.
Pilih salah satu file mandiri: `docker-compose.yml` untuk CPU (termasuk Mac),
atau `docker-compose.gpu.yml` untuk GPU NVIDIA. Jangan jalankan keduanya bersamaan.
API dari host: `http://localhost:11435`.
Alamat dari container dalam jaringan Compose: `http://ollama:11434`.

## Menjalankan

```sh
docker compose up -d ollama ollama-models
docker compose logs -f ollama-models
docker compose exec ollama ollama list
```

Untuk NVIDIA, gunakan file GPU pada setiap perintah:

```sh
docker compose -f docker-compose.gpu.yml up -d ollama ollama-models
docker compose -f docker-compose.gpu.yml logs -f ollama-models
docker compose -f docker-compose.gpu.yml exec ollama ollama list
```

Kedua versi menjalankan Ollama di Docker. Tidak perlu instalasi Ollama native
untuk Mac. Versi CPU tidak meminta perangkat NVIDIA dan dapat jauh lebih lambat.
Pastikan memori Docker cukup untuk model yang dipilih; mulai dari 8B atau gunakan API.

Service `ollama-models` menunggu server sehat, lalu mengunduh model yang belum
tersedia. `.env.example` mengunduh `qwen3:8b` saja; fallback Compose jika variabel
tidak diisi tetap `qwen3:8b qwen3:14b`. Setelah selesai, initializer keluar dengan
kode 0; server tetap berjalan. Ubah `OLLAMA_MODELS_TO_PULL` di .env untuk mengganti
daftar model. Model yang telah tersedia dilewati, bukan diunduh ulang.

Model disimpan di named volume `games_ollama_data`, dipasang ke `/root/.ollama`.
Volume proyek yang sudah ada dipakai ulang, termasuk model-model sebelumnya.
`docker compose down`, `up`, restart, dan recreate container mempertahankan model.
Jangan gunakan `docker compose down -v` atau menghapus volume jika model/data
database masih diperlukan: opsi `-v` ikut menghapus named volume proyek.

## Pengaturan

- `OLLAMA_CONTEXT_LENGTH=2048`: ukuran konteks default.
- `OLLAMA_KEEP_ALIVE=10m`: mempertahankan model di memori setelah request.
- Port host hanya di-bind ke loopback (127.0.0.1), bukan jaringan publik.
- Reservation GPU NVIDIA hanya ada di `docker-compose.gpu.yml`.
- RTX 3060 Laptop pada mesin ini memiliki VRAM 6 GB; model 14B dapat memakai
  sebagian RAM/CPU, sehingga kecepatan perlu diuji sesuai kapasitas mesin.

Ollama menyediakan inference, bukan pipeline training/fine-tuning.
## Memilih provider chat backend

Isi file .env di root:

```dotenv
AI_PROVIDER=docker
OLLAMA_MODEL=8
OLLAMA_TIMEOUT_SECONDS=180
OLLAMA_MAX_OUTPUT_TOKENS=160
```

- `AI_PROVIDER=docker`: backend mengirim chat ke Ollama di `http://ollama:11434`.
- `AI_PROVIDER=api`: backend memakai OpenAI dengan `OPENAI_API_KEY` dan `OPENAI_MODEL`.
- `OLLAMA_MODEL=8` memilih `qwen3:8b`; `OLLAMA_MODEL=14` memilih `qwen3:14b`.
- Nilai lama `qwen3:8b` dan `qwen3:14b` tetap diterima; pilihan lain ditolak.
- Tidak ada fallback otomatis dari Docker ke API berbayar.

Setelah mengubah environment, recreate backend (restart saja tidak memuat ulang
environment Docker Compose):

```sh
docker compose up -d ollama ollama-models
docker compose up -d --force-recreate ai-engine
docker compose restart gateway
```

Untuk mesin NVIDIA, ganti awalan perintah di atas menjadi
`docker compose -f docker-compose.gpu.yml` agar service Ollama tetap mendapat GPU.
Jangan memakai `up` versi CPU untuk memperbarui Ollama NVIDIA secara tidak sengaja.

CPU yang lambat dapat memerlukan `OLLAMA_TIMEOUT_SECONDS=600`; terapkan dengan
recreate backend. Timeout lebih panjang tidak menjamin model muat di RAM.

Recreate diperlukan untuk mengganti environment backend. Restart gateway
memperbarui resolusi alamat container backend jika alamatnya berubah.
Periksa `http://localhost:8000/app-status`: `ai_provider`, `ai_model`, dan
`ollama_ready` menunjukkan pilihan aktif dan ketersediaan model lokal.
Mode API tidak memerlukan server Ollama untuk menjawab.

Referensi: [Ollama Docker](https://docs.ollama.com/docker).

# Shadow Heist Python Backend

Struktur API menggunakan controller, service, dan model berisi SQL langsung.

```text
backend/
  app/
    __init__.py
    main.py                     # Entry point ASGI
    config/
      settings.py               # Pengaturan aplikasi/AI dan pembaca environment
      mysql.py                  # Host, port, database, kredensial, pool
      database.py               # Pool, sesi, jalankan_transaksi, PersistenceError, health probe
      skins.py                  # Daftar skin pemain dan bot
    controllers/                # API HTTP
      routes.py                 # Menggabungkan router HTTP
      auth.py
      health.py
      panel.py                  # Panel administrator (/panel)
      panel_npc.py              # Panel Otak NPC, simulasi, dan peta kode
      rooms.py                  # Lobby, start, snapshot privat, aksi/vote, checker
      survey.py
      users.py                  # Manajemen user di panel
    middleware/
      auth.py                   # Validasi bearer token sebelum controller
      auth_limits.py            # Batas percobaan login
      cors.py                   # Kebijakan cross-origin
      safe_validation.py        # Respons 422 tanpa isi input
    sockets/
      server.py                 # Membuat sio dan mengirim ke room (emit_room)
      chat.py                   # Event Socket.IO: connect, disconnect, send_chat (menerima dan mengirim system_alert)
    services/                   # Logika login, password, room, chat, survei, panel, dan konfigurasi AI
      auth_service.py           # Login, pendaftaran, login Google, dan sesi pemain
      chat_service.py           # Tahap chat manusia: cek, simpan, kirim ke room, baca IndoBERT
      panel_service.py          # Sesi admin, konfigurasi, arsip room, jejak, dan riwayat chat
      persistence_service.py    # Penyimpanan chat, jejak, dan arsip room per transaksi
      ollama_client.py          # Cek model di link Ollama
    models/
      auth_queries.py           # SELECT/INSERT/UPDATE/DELETE akun dan sesi
      game_queries.py           # SELECT/INSERT/UPDATE pemain, chat, dan jejak checker
      panel_queries.py          # Sesi panel, konfigurasi, arsip room, jejak, riwayat, kesiapan skema
      survey_queries.py         # Survei akhir pertandingan dan catatan metode bot
    game/
      match_engine.py           # Engine pertandingan: role, fase, skill, vote, kemenangan, snapshot privat
    bot/                        # Bot NPC; berpikir saja, tanpa SQL, bertindak lewat services/room_service.py
      bot_controller.py         # Urutan satu langkah bot (NPCService) dan otak bersama (BrainRuntime)
      nlu.py                    # IndoBERT membaca chat, aturan nama, memo bersama, pencatat NLU
      ingatan.py                # Bahan: Ingatan bot, chat/vote/fakta -> angka bukti per pemain (tanpa fuzzy)
      fuzzy_controller.py       # Main controller fuzzy: putuskan; [FUZZY 1] -> Tribunal -> Diskusi -> Malam -> bungkus
      fuzzy/                    # Hanya fungsi fuzzy (input 0-1 -> keluaran 0-100), satu sistem = satu fungsi
        mesin.py                # Kurva, bangun sistem Mamdani, centroid + cache, SEMUA_SISTEM, penjelasan
        kecurigaan.py           # [FUZZY 1] 7 sistem kecurigaan warga
        ancaman.py              # [FUZZY 1] 4 sistem ancaman dan kambing hitam Hitman
        diskusi.py              # [FUZZY 2] 6 sistem chat
        tribunal.py             # [FUZZY 2] 2 sistem vote warga
        malam.py                # [FUZZY 2] 2 sistem aksi malam (Gag, Peek)
      nlg.py                    # Kalimat: LLM atau templat, pemeriksa aturan, rantai penulis panel
      penjelasan.py             # Penjelasan keputusan bot untuk checker panel
      simulasi.py               # Simulasi panel dengan otak yang sama
    schemas/                    # Validasi request/response API
  artifacts/
    indobert/                   # Model NLU intent dan target
  deployment/                   # Dockerfile Azure dan proxy
  migrations/                   # SQL untuk membuat/mengubah struktur tabel
  public/                       # Panel administrator dan dokumen
  scripts/                      # CLI akun, penyiapan deployment, dan simulasi keseimbangan
  tests/
```

Alur manusia: HTTP -> controllers, atau Socket.IO -> sockets, lalu services -> game/ dan models (SQL) -> MySQL.
Alur bot: jam -> bot/bot_controller.py -> ingatan -> nlu -> fuzzy_controller (fuzzy/) -> services/ -> nlg -> services/
-> kirim ke room.
Koneksi dan pool MySQL disediakan oleh `app/config/database.py`.
Model tidak menyimpan aturan HTTP atau menulis respons API. Service mengatur
transaksi agar beberapa query bisa commit/rollback bersama.

Engine murni ada di `app/game/match_engine.py`: role, fase, skill, cooldown,
voting, kemenangan, serta snapshot privat. `app/services/room_service.py` membatasi
akses anggota/host dan memegang lock. `app/main.py` menjalankan clock pertandingan;
frontend hanya menampilkan keputusan server. Lihat [alur dan aturan game](../GAME_CONCEPT.md).

State pertandingan masih di memori satu proses, bukan snapshot MySQL. Reconnect
browser aman selama proses hidup, tetapi restart backend menghilangkan match.
Chat/analisis disimpan lewat model SQL yang sudah ada. Tes `tests/live_match_smoke.py`
menjalankan pertandingan nyata empat akun sementara sampai selesai, dengan cleanup
akun milik tes. Jangan menjalankannya pada deployment publik.

## SQL langsung di model

```python
# app/models/auth_queries.py
from sqlalchemy import text

def account_by_username(database, username):
    sql = text("""
        SELECT id, username, display_name, password_hash, is_active
        FROM user_accounts WHERE username = :username
    """)
    return database.execute(sql, {"username": username}).mappings().one_or_none()
```

Pemakaian dari service:

```python
from app.config.database import jalankan_transaksi
from app.models.auth_queries import account_by_username

account = jalankan_transaksi(lambda database: account_by_username(database, "user1"))
# account berupa mapping: account["username"], atau None jika tidak ditemukan.
# Error SQL di-rollback lalu menjadi PersistenceError.
```

SQLAlchemy digunakan sebagai konektor/pool dan pengikat parameter SQL; query
aplikasi ditulis sebagai SQL langsung, bukan query ORM. Jangan interpolasi input
pengguna ke SQL. Gunakan `:username` dan dictionary parameter, padanan placeholder
`?` di mysql2. Exception diteruskan ke service untuk rollback dan diterjemahkan
controller menjadi respons API. Pool ditutup hanya saat aplikasi berhenti,
bukan setiap query. Semua perubahan tabel tetap melalui migrations.

## Config

Environment Docker atau file `.env` di root dibaca oleh `app/config/settings.py`.
Pengaturan MySQL didefinisikan di `app/config/mysql.py`:
`MYSQL_HOST`, `MYSQL_PORT`, `MYSQL_DATABASE`, `MYSQL_USER`, `MYSQL_PASSWORD`.
`MYSQL_PASSWORD` wajib diisi: backend gagal jalan kalau kosong.
Alias `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD` juga diterima;
jika keduanya diberikan, nama MYSQL_* diprioritaskan. Nilai DB_* harus diteruskan
ke environment container jika menjalankan backend lewat Docker.

Secret tidak disimpan dalam mysql.json atau kode controller. Lihat `.env.example`.
`OPENROUTER_API_KEY` dan `OLLAMA_TUNNEL_TOKEN` hanya dibaca backend.
Default model dan batas respons tetap di settings.py.
Pilih `AI_PROVIDER=docker` untuk Ollama (lokal/tunnel) atau `AI_PROVIDER=api` untuk OpenRouter.
`OLLAMA_MODEL` memilih model lokal (default qwen3:14b). Recreate service ai-engine
setelah mengubah .env; lihat ../OLLAMA.md untuk perintah dan pemeriksaan status.

## Menjalankan dan menguji

Jalankan `uvicorn app.main:asgi_app --host 0.0.0.0 --port 8000` dari backend.
URL HTTP dan event Socket.IO tidak berubah karena refactor ini.
Setelah memperbarui kode, jalankan `docker compose up -d --build` dari root repo
agar image menggunakan entry point `app.main:asgi_app` yang baru.

```sh
python -m unittest discover -s tests -v
# Khusus database MySQL sementara yang telah diberi migration:
STRUCTURE_TEST_DB=1 python -m unittest discover -s tests -p mysql_smoke.py -v
```

Tes MySQL menulis data percobaan; jangan arahkan ke database pengguna. Tes
controller memakai respons AI mock untuk memeriksa jalur API dan penyimpanan
SQL, tanpa panggilan berbayar ke OpenAI.

Migration tidak membuat akun; buat akun lewat halaman daftar atau CLI `scripts/create_user.py`.

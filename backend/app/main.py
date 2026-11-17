"""
Membangun Server HTTP, Mengkoneksi dengan Socket.IO,Mengatur Jam Server dan mengatur bot NPC.

Alurnya 
1. Memasang Socket.IO (dibuat di sockets/server.py, event-nya di sockets/chat.py)
2. Membangun Server (Koneksi ke DB, Konfigurasi AI, Konfigurasi NPC, Memuat Otak AI, Menyalakan Jam (cek terus setiap 0.5 Detik))
3. Konfigurasi panel yang gagal dimuat karena MySQL belum siap dicoba ulang di latar; selama MySQL tidak menjawab, jam room dijeda

Jadinya AI Mulai Mikir dari Sini (isi pikirannya di bot/bot_controller.py)
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, suppress
import logging
import time

import socketio
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from app.config.settings import settings
from app.controllers.routes import api_router
from app.middleware.cors import configure_cors
from app.services.ai_config_service import muat_konfigurasi_ai
from app.config.database import database_gagal, database_is_ready, engine, error_koneksi
from app.bot.bot_controller import brain_runtime, npc_service
from app.services.npc_config_service import muat_konfigurasi_npc
from app.services.persistence_service import PersistenceError
from app.services.room_service import room_service
# Cukup diimpor: chat.py mendaftarkan event connect, disconnect, dan send_chat ke sio.
from app.sockets import chat  # noqa: F401
from app.sockets.server import sio

# Konfigurasi panel yang disimpan di MySQL dan dibaca ke memori saat server nyala, supaya tidak hilang saat restart:
# API key, token, dan link LLM (Konfigurasi AI), serta penulis kalimat dan model (Otak NPC).
PEMUAT_KONFIGURASI = {"Konfigurasi AI": muat_konfigurasi_ai, "Konfigurasi Otak NPC": muat_konfigurasi_npc}
# Jeda antarpercobaan memuat konfigurasi panel yang gagal saat server nyala (detik).
JEDA_COBA_KONFIGURASI_DETIK = 5


# Muat konfigurasi panel yang namanya diberikan; MySQL sudah dicek siap oleh pemanggil. Hasil: nama yang perlu dicoba
# lagi. Yang gagal memakai nilai .env. Hanya kegagalan karena MySQL tidak menjawab yang dicoba lagi; kegagalan lain
# (mis. API key tidak bisa dibuka dengan PANEL_ENCRYPTION_KEY) tidak berubah dengan mencoba ulang.
def muat_konfigurasi_panel(daftar_nama):
    gagal = []
    for nama in daftar_nama:
        try:
            PEMUAT_KONFIGURASI[nama]()
        except PersistenceError as error:
            logger.warning("%s panel gagal dimuat; memakai .env: %s", nama, error)
            if database_gagal():
                gagal.append(nama)
    return gagal


# Di latar: coba lagi tiap JEDA_COBA_KONFIGURASI_DETIK sampai semua konfigurasi panel termuat, tanpa menahan startup.
# Alur: 1 tunggu jeda -> 2 MySQL belum siap: ulangi -> 3 muat yang belum termuat -> 4 semua termuat: catat di log
async def coba_ulang_konfigurasi_panel(belum):
    percobaan = 1
    while belum:
        await asyncio.sleep(JEDA_COBA_KONFIGURASI_DETIK)
        percobaan += 1
        if await asyncio.to_thread(database_is_ready):
            belum = await asyncio.to_thread(muat_konfigurasi_panel, belum)
    logger.info("Konfigurasi panel dimuat dari MySQL pada percobaan ke-%s.", percobaan)


@asynccontextmanager
async def lifespan(_: FastAPI):
    # setiap 0.5 detik jalankan pengcekan fase dan bot. Selama MySQL tidak menjawab (pemain hanya mendapat 503),
    # jam room dijeda: fase tidak berganti, bot tidak melangkah, dan sisa waktu fase tetap.
    # Alur: 1 putaran sebelumnya dijeda: geser batas waktu room sejauh selangnya -> 2.1 MySQL menjawab: ganti fase
    #       dan jalankan bot -> 2.2 MySQL gagal: periksa ulang dengan SELECT 1 di thread
    async def game_clock():
        dijeda, waktu_sebelum = False, time.monotonic()
        while True:
            try:
                waktu_sekarang = time.monotonic()
                if dijeda:
                    room_service.jeda_jam_semua_room(waktu_sekarang - waktu_sebelum)
                waktu_sebelum = waktu_sekarang
                dijeda = database_gagal()
                if dijeda:
                    await asyncio.to_thread(database_is_ready)
                else:
                    # ganti fase yang waktunya habis
                    room_service.perbarui_fase_semua_room()
                    # jalankan bot yang sudah waktunya
                    npc_service.jalankan_bot_yang_sudah_waktunya()
            except Exception:
                logger.exception("Satu putaran jam permainan gagal.")
            # tunggu 0,5 detik
            await asyncio.sleep(0.5)
    
    
    # API key, token, dan link LLM yang disimpan lewat panel dibaca dari DB ke memori, begitu juga pengaturan
    # Otak NPC (penulis kalimat dan model). MySQL belum siap: dicoba ulang di latar.
    belum = list(PEMUAT_KONFIGURASI)
    if database_is_ready():
        logger.info("Koneksi MySQL siap.")
        belum = muat_konfigurasi_panel(belum)
    else:
        logger.error("Koneksi awal MySQL gagal.")
    coba_ulang = None
    if belum:
        logger.error(
            "%s belum dimuat dari MySQL; dicoba ulang tiap %s detik di latar.",
            ", ".join(belum),
            JEDA_COBA_KONFIGURASI_DETIK,
        )
        coba_ulang = asyncio.create_task(coba_ulang_konfigurasi_panel(belum))

    # memasukan Indobert, Fuzzy , NLG 
    brain_runtime.mulai_memuat()

    # Jam jalan sebagai tugas latar, supaya tetap berdetak sambil server melayani pemain.
    clock = asyncio.create_task(game_clock())
    try:
        yield
    finally:
        # Server mati: hentikan jam dan percobaan konfigurasi, batalkan giliran bot yang masih jalan, tutup thread
        # otak, tutup koneksi MySQL.
        for tugas in (clock, coba_ulang):
            if tugas is not None:
                tugas.cancel()
                with suppress(asyncio.CancelledError):
                    await tugas
        await npc_service.close()
        brain_runtime.tutup()
        engine.dispose()


# Menyiapkan pencatat log. File lain memakai anak dari nama ini (mis. shadow_heist.database), jadi pesannya ikut aturan yang sama.
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("shadow_heist")

# Bangun FastAPI dan daftarkan lifespan(Koneksi ke DB, Konfigurasi AI, Konfigurasi NPC, Memuat Otak AI, Menyalakan Jam (cek terus setiap 0.5 Detik)).
# Lifespan baru jalan saat Uvicorn menyalakan server. /docs, /redoc, dan /openapi.json mati bila API_DOCS=false (produksi).
app = FastAPI(
    title=settings.app_name,
    lifespan=lifespan,
    docs_url="/docs" if settings.api_docs else None,
    redoc_url="/redoc" if settings.api_docs else None,
    openapi_url="/openapi.json" if settings.api_docs else None,
)


# Error database yang tidak ditangani controller (mis. profil akun saat membuat, masuk, atau memulai room) menjadi
# JSON: 503 bila MySQL tidak menjawab, 500 untuk error SQL lain. Handler ini berjalan di dalam middleware CORS, jadi
# browser tetap menerima header CORS dan menampilkan pesannya, bukan "CORS error".
async def error_database(_request, error):
    if isinstance(error, PersistenceError):
        return JSONResponse({"detail": str(error)}, status_code=503)
    # Parameter SQL tidak dicatat karena bisa memuat isi chat privat.
    logger.error("Query database gagal di luar transaksi (%s).", type(error).__name__)
    if error_koneksi(error):
        return JSONResponse({"detail": "Database sedang tidak tersedia."}, status_code=503)
    return JSONResponse({"detail": "Terjadi kesalahan database di server."}, status_code=500)


app.add_exception_handler(SQLAlchemyError, error_database)
app.add_exception_handler(PersistenceError, error_database)
configure_cors(app)
app.include_router(api_router)

# Socket.IO: jalur yang tetap terbuka antara server dan browser, jadi server bisa mengirim chat kapan saja.
# Di sini hanya persiapan: connect, disconnect, dan send_chat baru jalan saat ada pemain.
asgi_app = socketio.ASGIApp(sio, other_asgi_app=app)

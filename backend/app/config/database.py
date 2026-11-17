"""Pool MySQL bersama dan sesi transaksi untuk SQL mentah berparameter.

Alurnya
1. Saat berkas ini diimpor, pool dibuat dengan batas waktu koneksi, baca, dan tulis. Koneksinya baru dibuka saat pertama kali dipakai
2. Setiap koneksi MySQL baru diatur ke zona waktu UTC
3. Modul lain menjalankan transaksi lewat jalankan_transaksi: commit bila sukses; error SQL di-rollback lalu menjadi PersistenceError
4. Setiap transaksi dan SELECT 1 mencatat apakah MySQL menjawab; jam permainan (main.py) membaca database_gagal
5. main.py dan controller health memeriksa kesiapan lewat database_is_ready
6. main.py menutup pool saat server mati (engine.dispose)
"""

import logging

from sqlalchemy import create_engine, text, event
from sqlalchemy.engine import make_url
from sqlalchemy.exc import InterfaceError, OperationalError, SQLAlchemyError
from sqlalchemy.exc import TimeoutError as PoolTimeoutError
from sqlalchemy.orm import sessionmaker

from app.config.settings import settings

logger = logging.getLogger("shadow_heist.database")

alamat_database = make_url(settings.sqlalchemy_database_url)
# Batas waktu PyMySQL (detik). Tanpa ini query yang menunggu MySQL hang atau jaringan putus tanpa RST tidak pernah
# kembali, padahal sebagian query berjalan di event loop atau sambil memegang lock room (jam dan bot ikut berhenti).
# connect 5: MySQL di jaringan Docker yang sama biasanya menjawab dalam milidetik. read/write 15: query terberat
# (halaman riwayat chat, ekspor CSV per 1000 baris) selesai jauh di bawah satu detik, jadi 15 detik hanya terlampaui
# bila MySQL memang macet. DATABASE_URL boleh menunjuk database lain yang tidak mengenal opsi ini.
BATAS_WAKTU_MYSQL = {"connect_timeout": 5, "read_timeout": 15, "write_timeout": 15}

# Kumpulan koneksi (pool) yang dipakai bersama. Koneksi yang diputus MySQL atau berumur lebih dari 1 jam diganti otomatis.
# Menunggu koneksi kosong paling lama 10 detik (bawaan 30), dengan alasan yang sama.
engine = create_engine(
    alamat_database,
    echo=settings.sql_echo,
    pool_pre_ping=True,
    pool_recycle=3_600,
    pool_size=settings.database_pool_size,
    max_overflow=settings.database_max_overflow,
    pool_timeout=10,
    connect_args=BATAS_WAKTU_MYSQL if alamat_database.get_backend_name() == "mysql" else {},
)
# DATABASE_URL boleh menunjuk database lain, sedangkan SET time_zone hanya ada di MySQL.
if engine.dialect.name == "mysql":
    # Set zona waktu setiap koneksi MySQL baru ke UTC agar timestamp konsisten.
    @event.listens_for(engine, "connect")
    def use_utc(dbapi_connection, _):
        with dbapi_connection.cursor() as cursor:
            cursor.execute("SET time_zone = '+00:00'")


# Pembuat sesi DB. Sesi wajib ditutup: close() mengembalikan koneksi ke pool, dan tanpa itu koneksi lama-lama habis.
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


class PersistenceError(RuntimeError):
    """Transaksi database gagal."""


# True sejak query terakhir gagal karena MySQL tidak menjawab; False lagi begitu ada query yang berhasil.
_database_gagal = False
# Kode error MySQL/PyMySQL yang berarti server tidak bisa dihubungi atau tidak menjawab: 2002/2003 gagal tersambung
# (termasuk connect_timeout), 2006/2013/2055 koneksi putus (termasuk read/write_timeout), 1040 koneksi penuh, 1053
# server sedang mati, 4031 diputus server. Kode lain (kolom belum ada, deadlock, data bentrok) berarti MySQL menjawab.
KODE_KONEKSI_GAGAL = {1040, 1053, 2002, 2003, 2006, 2013, 2055, 4031}


# True bila error berarti MySQL tidak bisa dihubungi atau tidak menjawab: koneksi ditolak atau putus, batas waktu
# terlampaui, atau pool kehabisan koneksi.
def error_koneksi(error) -> bool:
    if isinstance(error, (InterfaceError, PoolTimeoutError)):
        return True
    kode = (getattr(getattr(error, "orig", None), "args", None) or (None,))[0]
    return isinstance(error, OperationalError) and kode in KODE_KONEKSI_GAGAL


# Catat hasil satu query (error=None berarti berhasil): MySQL menjawab atau tidak. Perubahan keadaan dicatat sekali
# di log.
def _catat_kesehatan(error=None):
    global _database_gagal
    gagal = error_koneksi(error)
    if gagal == _database_gagal:
        return
    _database_gagal = gagal
    if gagal:
        logger.warning(
            "MySQL tidak menjawab (%s); jam room dijeda sampai pulih.", type(error).__name__
        )
    else:
        logger.info("MySQL menjawab lagi; jam room berjalan kembali.")


# Dibaca game_clock tiap putaran: True selama MySQL terakhir kali tidak menjawab.
def database_gagal() -> bool:
    return _database_gagal


# Jalankan operasi(database) dalam satu transaksi; hanya error SQL menjadi PersistenceError(pesan).
# Sesi dibuka manual, bukan lewat SessionLocal.begin(): operasi di service auth memanggil
# database.rollback() sendiri, dan di dalam blok begin() itu bisa memicu InvalidRequestError.
def jalankan_transaksi(operasi, pesan="Database sedang tidak tersedia."):
    database = SessionLocal()
    try:
        hasil = operasi(database)
        database.commit()
        _catat_kesehatan()
        return hasil
    except SQLAlchemyError as error:
        database.rollback()
        _catat_kesehatan(error)
        # Parameter SQL tidak dicatat karena bisa memuat isi chat privat.
        logger.error("Transaksi database gagal (%s).", type(error).__name__)
        raise PersistenceError(pesan) from error
    finally:
        database.close()


# HEALTH CHECK: jalankan SELECT 1 tanpa mengubah data; dipakai startup, controller health, dan jam permainan
# (memeriksa apakah MySQL sudah pulih).
def database_is_ready() -> bool:
    try:
        with engine.connect() as koneksi:
            koneksi.execute(text("SELECT 1"))
    except SQLAlchemyError as error:
        _catat_kesehatan(error)
        return False
    _catat_kesehatan()
    return True

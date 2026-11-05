"""Pool MySQL bersama dan sesi transaksi untuk SQL mentah berparameter.

Alurnya
1. Saat berkas ini diimpor, pool dibuat. Koneksinya baru dibuka saat pertama kali dipakai
2. Setiap koneksi MySQL baru diatur ke zona waktu UTC
3. Modul lain menjalankan transaksi lewat jalankan_transaksi: commit bila sukses; error SQL di-rollback lalu menjadi PersistenceError
4. main.py dan controller health memeriksa kesiapan lewat database_is_ready
5. main.py menutup pool saat server mati (engine.dispose)
"""

import logging

from sqlalchemy import create_engine, text, event
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker

from app.config.settings import settings

logger = logging.getLogger("shadow_heist.database")

# Kumpulan koneksi (pool) yang dipakai bersama. Koneksi yang diputus MySQL atau berumur lebih dari 1 jam diganti otomatis.
engine = create_engine(
    settings.sqlalchemy_database_url,
    echo=settings.sql_echo,
    pool_pre_ping=True,
    pool_recycle=3_600,
    pool_size=settings.database_pool_size,
    max_overflow=settings.database_max_overflow,
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


# Jalankan operasi(database) dalam satu transaksi; hanya error SQL menjadi PersistenceError(pesan).
# Sesi dibuka manual, bukan lewat SessionLocal.begin(): operasi di service auth memanggil
# database.rollback() sendiri, dan di dalam blok begin() itu bisa memicu InvalidRequestError.
def jalankan_transaksi(operasi, pesan="Database sedang tidak tersedia."):
    database = SessionLocal()
    try:
        hasil = operasi(database)
        database.commit()
        return hasil
    except SQLAlchemyError as error:
        database.rollback()
        # Parameter SQL tidak dicatat karena bisa memuat isi chat privat.
        logger.error("Transaksi database gagal (%s).", type(error).__name__)
        raise PersistenceError(pesan) from error
    finally:
        database.close()


# HEALTH CHECK: jalankan SELECT 1 tanpa mengubah data; dipakai startup dan controller health.
def database_is_ready() -> bool:
    try:
        with engine.connect() as koneksi:
            koneksi.execute(text("SELECT 1"))
        return True
    except SQLAlchemyError:
        return False

"""Pool MySQL bersama dan sesi transaksi untuk SQL mentah berparameter.

Alurnya
1. Saat berkas ini diimpor, pool dibuat. Koneksinya baru dibuka saat pertama kali dipakai
2. Setiap koneksi MySQL baru diatur ke zona waktu UTC
3. Modul lain membuka transaksi lewat SessionLocal, sedangkan main.py dan controller health memeriksa kesiapan lewat database_is_ready
4. main.py menutup pool saat server mati (engine.dispose)
"""

from sqlalchemy import create_engine, text, event
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker

from app.config.settings import settings

# pool_pre_ping dan pool_recycle: koneksi yang sudah diputus MySQL diganti, tidak menggagalkan request.
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


SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


# HEALTH CHECK: jalankan SELECT 1 tanpa mengubah data; dipakai startup dan controller health.
def database_is_ready() -> bool:
    try:
        with engine.connect() as koneksi:
            koneksi.execute(text("SELECT 1"))
        return True
    except SQLAlchemyError:
        return False

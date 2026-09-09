"""Shared MySQL pool and transaction sessions for parameterized raw SQL."""

from collections.abc import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from config.settings import settings


engine = create_engine(
    settings.sqlalchemy_database_url,
    echo=settings.sql_echo,
    pool_pre_ping=True,
    pool_recycle=3_600,
    pool_size=settings.database_pool_size,
    max_overflow=settings.database_max_overflow,
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


# GENERATOR DEPENDENCY: sediakan sesi database untuk pemanggil dan selalu tutup sesi setelah selesai.
def get_db() -> Generator[Session, None, None]:
    """Yield one transaction session per HTTP request."""
    database = SessionLocal()
    try:
        yield database
    finally:
        database.close()

# HEALTH CHECK: jalankan SELECT 1 untuk mengecek koneksi tanpa mengubah data.
def database_is_ready() -> bool:
    """Read-only connectivity probe shared by startup and health controller."""
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return True
    except SQLAlchemyError:
        return False

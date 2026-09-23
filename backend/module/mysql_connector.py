"""Shared MySQL pool and transaction sessions for parameterized raw SQL."""

from sqlalchemy import create_engine, text, event
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker

from config.settings import settings

engine = create_engine(
    settings.sqlalchemy_database_url,
    echo=settings.sql_echo,
    pool_pre_ping=True,
    pool_recycle=3_600,
    pool_size=settings.database_pool_size,
    max_overflow=settings.database_max_overflow,
)
if engine.dialect.name == "mysql":
    # Set zona waktu setiap koneksi MySQL baru ke UTC agar timestamp konsisten.
    @event.listens_for(engine, "connect")
    def use_utc(dbapi_connection, _):
        with dbapi_connection.cursor() as cursor:
            cursor.execute("SET time_zone = '+00:00'")


SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


# HEALTH CHECK: jalankan SELECT 1 untuk mengecek koneksi tanpa mengubah data.
def database_is_ready() -> bool:
    """Read-only connectivity probe shared by startup and health controller."""
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return True
    except SQLAlchemyError:
        return False

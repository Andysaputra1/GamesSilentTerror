"""SQLAlchemy engine and request-scoped database session dependency."""

from collections.abc import Generator

from sqlalchemy import create_engine
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


def get_db() -> Generator[Session, None, None]:
    """Yield one transaction session per HTTP request."""
    database = SessionLocal()
    try:
        yield database
    finally:
        database.close()

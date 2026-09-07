"""Base declaration shared by every SQLAlchemy model."""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass

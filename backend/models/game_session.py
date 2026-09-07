from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, String, text
from sqlalchemy.dialects.mysql import BIGINT
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.base import Base

if TYPE_CHECKING:
    from models.chat_message import ChatMessage
    from models.player import Player


class GameSession(Base):
    """One playable Shadow Heist room/session."""

    __tablename__ = "game_sessions"

    id: Mapped[int] = mapped_column(BIGINT(unsigned=True), primary_key=True, autoincrement=True)
    room_code: Mapped[str] = mapped_column(String(36), nullable=False, unique=True, index=True)
    phase: Mapped[str] = mapped_column(String(20), nullable=False, server_default=text("'lobby'"))
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
        server_onupdate=text("CURRENT_TIMESTAMP"),
    )

    players: Mapped[list["Player"]] = relationship(back_populates="game_session")
    chat_messages: Mapped[list["ChatMessage"]] = relationship(back_populates="game_session")

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, text
from sqlalchemy.dialects.mysql import BIGINT, DECIMAL, TINYINT
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.base import Base

if TYPE_CHECKING:
    from models.chat_message import ChatMessage
    from models.game_session import GameSession


class Player(Base):
    """A player's persistent state inside a game session."""

    __tablename__ = "players"
    __table_args__ = (UniqueConstraint("game_session_id", "username", name="uq_players_session_username"),)

    id: Mapped[int] = mapped_column(BIGINT(unsigned=True), primary_key=True, autoincrement=True)
    game_session_id: Mapped[int | None] = mapped_column(
        BIGINT(unsigned=True),
        ForeignKey("game_sessions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    username: Mapped[str] = mapped_column(String(100), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    role: Mapped[str | None] = mapped_column(String(20), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default=text("'active'"))
    aggressiveness: Mapped[int] = mapped_column(TINYINT(unsigned=True), nullable=False, server_default=text("0"))
    suspicion_score: Mapped[float] = mapped_column(
        DECIMAL(5, 2), nullable=False, server_default=text("0.00")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
        server_onupdate=text("CURRENT_TIMESTAMP"),
    )

    game_session: Mapped["GameSession | None"] = relationship(back_populates="players")
    chat_messages: Mapped[list["ChatMessage"]] = relationship(back_populates="player")

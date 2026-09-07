from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String, Text, text
from sqlalchemy.dialects.mysql import BIGINT, DECIMAL
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.base import Base

if TYPE_CHECKING:
    from models.ai_analysis import AIAnalysis
    from models.game_session import GameSession
    from models.player import Player


class ChatMessage(Base):
    """A message sent by a player or the AI host."""

    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(BIGINT(unsigned=True), primary_key=True, autoincrement=True)
    game_session_id: Mapped[int | None] = mapped_column(
        BIGINT(unsigned=True),
        ForeignKey("game_sessions.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    player_id: Mapped[int | None] = mapped_column(
        BIGINT(unsigned=True),
        ForeignKey("players.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    sender_name: Mapped[str] = mapped_column(String(100), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    intent: Mapped[str | None] = mapped_column(String(50), nullable=True)
    suspicion_score: Mapped[float | None] = mapped_column(DECIMAL(5, 2), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )

    game_session: Mapped["GameSession | None"] = relationship(back_populates="chat_messages")
    player: Mapped["Player | None"] = relationship(back_populates="chat_messages")
    analyses: Mapped[list["AIAnalysis"]] = relationship(back_populates="chat_message")

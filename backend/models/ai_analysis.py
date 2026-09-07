from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String, Text, text
from sqlalchemy.dialects.mysql import BIGINT, DECIMAL, TINYINT
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.base import Base

if TYPE_CHECKING:
    from models.chat_message import ChatMessage


class AIAnalysis(Base):
    """SVM, fuzzy, and LLM output associated with one chat message."""

    __tablename__ = "ai_analyses"

    id: Mapped[int] = mapped_column(BIGINT(unsigned=True), primary_key=True, autoincrement=True)
    chat_message_id: Mapped[int | None] = mapped_column(
        BIGINT(unsigned=True),
        ForeignKey("chat_messages.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    intent: Mapped[str] = mapped_column(String(50), nullable=False)
    aggressiveness: Mapped[int] = mapped_column(TINYINT(unsigned=True), nullable=False)
    suspicion_score: Mapped[float] = mapped_column(DECIMAL(5, 2), nullable=False)
    suspicion_status: Mapped[str] = mapped_column(String(10), nullable=False)
    llm_response: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )

    chat_message: Mapped["ChatMessage | None"] = relationship(back_populates="analyses")

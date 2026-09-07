"""Validation contracts for chat and AI-analysis endpoints."""

from pydantic import BaseModel, Field


class AnalyzeChatRequest(BaseModel):
    player_name: str = Field(min_length=1, max_length=100)
    message: str = Field(min_length=1, max_length=2_000)
    silence_percentage: int = Field(ge=0, le=100)


class LegacyGameChatRequest(BaseModel):
    """Payload retained for the old Express ``/api/game/chat`` caller."""

    message: str = Field(min_length=1, max_length=2_000)
    player_id: str | None = Field(default=None, max_length=100)


class LegacyAIChatRequest(BaseModel):
    """Payload retained for the old Node-to-Python ``/api/ai-chat`` caller."""

    player_message: str = Field(min_length=1, max_length=2_000)


class FuzzyResult(BaseModel):
    aggressiveness: int
    suspicion_score: float
    status: str


class AnalysisResponse(BaseModel):
    intent: str
    fuzzy: FuzzyResult
    llm_response: str

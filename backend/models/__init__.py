"""Import SQLAlchemy mappings before using model metadata or relationships."""

from models.ai_analysis import AIAnalysis
from models.auth_session import AuthSession
from models.chat_message import ChatMessage
from models.game_session import GameSession
from models.player import Player
from models.schema_migration import SchemaMigration
from models.user_account import UserAccount

__all__ = [
    "AIAnalysis",
    "AuthSession",
    "ChatMessage",
    "GameSession",
    "Player",
    "SchemaMigration",
    "UserAccount",
]

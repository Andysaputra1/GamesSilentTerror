"""Database use cases backed by the SQLAlchemy models.

The migration files own schema changes. This service only reads and writes rows
from that versioned schema.
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from config.database import SessionLocal
from config.settings import settings
from models import AIAnalysis, ChatMessage, GameSession, Player
from services.analysis_service import AnalysisResult
from services.fuzzy_service import status_for_score


logger = logging.getLogger("shadow_heist.persistence")


class PersistenceError(RuntimeError):
    """Raised when a game action cannot be committed to MySQL."""


def _session_for_room(database: Session) -> GameSession:
    game_session = database.scalar(
        select(GameSession).where(GameSession.room_code == settings.default_room_code)
    )
    if game_session is None:
        game_session = GameSession(room_code=settings.default_room_code, phase="day")
        database.add(game_session)
        database.flush()
    return game_session


def _player_for_username(
    database: Session, game_session: GameSession, username: str
) -> Player:
    player = database.scalar(
        select(Player).where(
            Player.game_session_id == game_session.id,
            Player.username == username,
        )
    )
    if player is None:
        player = Player(
            game_session_id=game_session.id,
            username=username,
            display_name=username,
            role="civilian",
            status="active",
            aggressiveness=0,
            suspicion_score=0,
        )
        database.add(player)
        database.flush()
    return player


class PersistenceService:
    """Persists application state in the configured default game room."""

    @staticmethod
    def _run(operation):
        database = SessionLocal()
        try:
            result = operation(database)
            database.commit()
            return result
        except SQLAlchemyError as error:
            database.rollback()
            logger.exception("Transaksi MySQL gagal: %s", error)
            raise PersistenceError("Data game gagal disimpan ke database.") from error
        finally:
            database.close()

    def ensure_player(self, username: str) -> None:
        def operation(database: Session) -> None:
            _player_for_username(database, _session_for_room(database), username)

        self._run(operation)

    def record_analysis(
        self, *, player_name: str, message: str, result: AnalysisResult
    ) -> None:
        def operation(database: Session) -> None:
            player = _player_for_username(database, _session_for_room(database), player_name)
            player.aggressiveness = result.aggressiveness
            player.suspicion_score = round(result.suspicion_score, 2)
            chat_message = ChatMessage(
                game_session_id=player.game_session_id,
                player_id=player.id,
                sender_name=player_name,
                message=message,
                intent=result.intent,
                suspicion_score=round(result.suspicion_score, 2),
            )
            database.add(chat_message)
            database.flush()
            database.add(
                AIAnalysis(
                    chat_message_id=chat_message.id,
                    intent=result.intent,
                    aggressiveness=result.aggressiveness,
                    suspicion_score=round(result.suspicion_score, 2),
                    suspicion_status=result.suspicion_status,
                    llm_response=result.llm_response,
                )
            )

        self._run(operation)

    def record_player_message(
        self,
        *,
        username: str,
        message: str,
        intent: str | None,
        aggressiveness: int,
        suspicion_score: float,
        status: str,
        llm_response: str | None = None,
    ) -> int:
        def operation(database: Session) -> int:
            player = _player_for_username(database, _session_for_room(database), username)
            player.aggressiveness = aggressiveness
            player.suspicion_score = round(suspicion_score, 2)
            player.status = status
            chat_message = ChatMessage(
                game_session_id=player.game_session_id,
                player_id=player.id,
                sender_name=username,
                message=message,
                intent=intent,
                suspicion_score=round(suspicion_score, 2),
            )
            database.add(chat_message)
            database.flush()
            if intent is not None and llm_response is not None:
                database.add(
                    AIAnalysis(
                        chat_message_id=chat_message.id,
                        intent=intent,
                        aggressiveness=aggressiveness,
                        suspicion_score=round(suspicion_score, 2),
                        suspicion_status=status_for_score(suspicion_score),
                        llm_response=llm_response,
                    )
                )
            return int(chat_message.id)

        return self._run(operation)

    def update_player_status(self, *, username: str, status: str) -> None:
        def operation(database: Session) -> None:
            player = _player_for_username(database, _session_for_room(database), username)
            player.status = status

        self._run(operation)

    def update_player_scores(
        self, *, username: str, aggressiveness: int, suspicion_score: float
    ) -> None:
        def operation(database: Session) -> None:
            player = _player_for_username(database, _session_for_room(database), username)
            player.aggressiveness = aggressiveness
            player.suspicion_score = round(suspicion_score, 2)

        self._run(operation)

    def set_phase(self, phase: str) -> None:
        def operation(database: Session) -> None:
            _session_for_room(database).phase = phase

        self._run(operation)


persistence_service = PersistenceService()

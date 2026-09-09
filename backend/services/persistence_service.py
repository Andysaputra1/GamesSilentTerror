"""Game persistence use cases. SQL stays in models; each action is atomic."""

from __future__ import annotations
import logging
from typing import TYPE_CHECKING
from sqlalchemy.exc import SQLAlchemyError

from config.settings import settings
from module.mysql_connector import SessionLocal
from models import game_queries as queries
from services.fuzzy_service import status_for_score

if TYPE_CHECKING:
    from services.analysis_service import AnalysisResult

logger = logging.getLogger("shadow_heist.persistence")


class PersistenceError(RuntimeError):
    """A game transaction could not be committed."""


class PersistenceService:
    # CONSTRUCTOR: pilih kode ruangan penyimpanan; gunakan ruangan default untuk pemanggil tanpa kode.
    def __init__(self, room_code: str | None = None):
        self.room_code = room_code or settings.default_room_code

    @staticmethod
    # STATIC METHOD TRANSAKSI: jalankan callback dengan commit/rollback otomatis dan terjemahkan error SQL.
    def _run(operation):
        try:
            with SessionLocal.begin() as database:
                return operation(database)
        except SQLAlchemyError as error:
            # Do not log SQL parameters: they may contain private chat content.
            logger.error("Game database transaction failed (%s).", type(error).__name__)
            raise PersistenceError("Data game gagal disimpan ke database.") from error

    # HELPER TRANSAKSI: pastikan ruangan dan pemain tersedia, lalu kembalikan kedua ID-nya.
    def _player(self, database, username):
        room_id = queries.ensure_room(database, self.room_code)
        return room_id, queries.ensure_player(database, room_id, username)

    # SERVICE PENYIMPANAN: pastikan pemain terdaftar dalam ruangan melalui satu transaksi.
    def ensure_player(self, username: str) -> None:
        self._run(lambda db: self._player(db, username))

    # SERVICE REST: petakan hasil analisis ke proses penyimpanan pesan dan respons AI.
    def record_analysis(self, *, player_name: str, message: str, result: AnalysisResult) -> None:
        self._record(
            username=player_name, message=message, intent=result.intent,
            aggressiveness=result.aggressiveness, suspicion_score=result.suspicion_score,
            status=None, llm_response=result.llm_response, suspicion_status=result.suspicion_status,
        )

    # SERVICE CHAT SOCKET: simpan pesan, skor, status pemain, dan respons LLM jika tersedia.
    def record_player_message(self, *, username: str, message: str, intent: str | None,
                              aggressiveness: int, suspicion_score: float, status: str,
                              llm_response: str | None = None) -> int:
        return self._record(
            username=username, message=message, intent=intent, aggressiveness=aggressiveness,
            suspicion_score=suspicion_score, status=status, llm_response=llm_response,
            suspicion_status=status_for_score(suspicion_score),
        )

    # HELPER PENYIMPANAN: gabungkan pembaruan pemain, pesan, dan analisis dalam satu transaksi atomik.
    def _record(self, *, username, message, intent, aggressiveness, suspicion_score,
                status, llm_response, suspicion_status):
        # CALLBACK TRANSAKSI: perbarui pemain, buat pesan, simpan analisis jika ada intent serta respons, lalu kembalikan ID pesan.
        def operation(database):
            room_id, player_id = self._player(database, username)
            queries.update_player_scores(database, player_id, aggressiveness, suspicion_score)
            if status is not None:
                queries.update_player_status(database, player_id, status)
            message_id = queries.insert_message(
                database, room_id=room_id, player_id=player_id, username=username,
                message=message, intent=intent, suspicion_score=suspicion_score,
            )
            if intent is not None and llm_response is not None:
                queries.insert_analysis(
                    database, message_id=message_id, intent=intent, aggressiveness=aggressiveness,
                    suspicion_score=suspicion_score, suspicion_status=suspicion_status,
                    llm_response=llm_response,
                )
            return message_id
        return self._run(operation)

    # SERVICE PENYIMPANAN: ubah status pemain secara transaksional, bukan keputusan aturan permainan.
    def update_player_status(self, *, username: str, status: str) -> None:
        # CALLBACK TRANSAKSI: pastikan pemain ada lalu perbarui statusnya.
        def operation(database):
            _, player_id = self._player(database, username)
            queries.update_player_status(database, player_id, status)
        self._run(operation)

    # SERVICE PENYIMPANAN: perbarui skor pemain melalui transaksi database.
    def update_player_scores(self, *, username: str, aggressiveness: int, suspicion_score: float) -> None:
        # CALLBACK TRANSAKSI: pastikan pemain ada lalu perbarui agresivitas dan kecurigaannya.
        def operation(database):
            _, player_id = self._player(database, username)
            queries.update_player_scores(database, player_id, aggressiveness, suspicion_score)
        self._run(operation)

    # SERVICE PENYIMPANAN: simpan nama fase ruangan; fungsi ini tidak menjalankan timer/voting.
    def set_phase(self, phase: str) -> None:
        # CALLBACK TRANSAKSI: pastikan ruangan ada lalu simpan fase yang diminta.
        def operation(database):
            queries.set_phase(database, queries.ensure_room(database, self.room_code), phase)
        self._run(operation)


persistence_service = PersistenceService()

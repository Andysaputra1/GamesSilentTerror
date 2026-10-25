"""Game persistence use cases. SQL stays in models; each action is atomic."""

from __future__ import annotations
import logging
from sqlalchemy.exc import SQLAlchemyError

from app.config.settings import settings
from app.services.mysql_connector import SessionLocal
from app.models import game_queries as queries

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

    # SERVICE CHAT SOCKET: simpan pesan pemain, status pemain, dan konteks fase dalam satu transaksi.
    def record_player_message(
        self,
        *,
        username: str,
        message: str,
        status: str | None = None,
        context: dict | None = None,
    ) -> int:
        # CALLBACK TRANSAKSI: pastikan pemain ada, perbarui status, simpan pesan, lalu kembalikan ID pesan.
        def operation(database):
            room_id, player_id = self._player(database, username)
            if status is not None:
                queries.update_player_status(database, player_id, status)
            message_id = queries.insert_message(
                database,
                room_id=room_id,
                player_id=player_id,
                username=username,
                message=message,
            )
            if context is not None:
                queries.set_message_context(
                    database, message_id, sender_kind="human", context=context
                )
            return message_id

        return self._run(operation)

    # Arsipkan ruangan baru beserta pemiliknya sebelum dipakai bermain.
    def archive_new_room(self, username):
        from sqlalchemy import text

        # Simpan ruangan dan pemiliknya dalam satu transaksi agar arsip tidak setengah jadi.
        def operation(db):
            inserted = db.execute(
                text("INSERT IGNORE INTO game_sessions(room_code,phase) VALUES(:code,'lobby')"),
                {"code": self.room_code},
            ).rowcount
            if not inserted:
                return False
            self._player(db, username)
            return True

        return self._run(operation)

    # Simpan jejak checker sebagai arsip analisis ruangan.
    def record_trace(self, trace):
        import json
        from sqlalchemy import text

        self._run(
            lambda db: db.execute(
                text("""
            INSERT INTO checker_traces(id,room_code,trace) VALUES(:id,:room,:trace)
            ON DUPLICATE KEY UPDATE trace=:trace
        """),
                {"id": trace["id"], "room": self.room_code, "trace": json.dumps(trace)},
            )
        )

    # Bacaan NLU (intent, target) satu pesan untuk riwayat chat panel (kolom migrasi V9).
    def record_nlu(self, message_id, nlu):
        import json
        from sqlalchemy import text

        self._run(
            lambda db: db.execute(
                text("UPDATE chat_messages SET nlu=:nlu WHERE id=:id"),
                {"id": message_id, "nlu": json.dumps(nlu, ensure_ascii=False)},
            )
        )

    # Simpan pesan bot beserta konteks fase (dan ID pesan yang dijawab, bila ada).
    def record_bot_message(self, *, username, message, context, reply_to_id=None):
        # Simpan pesan bot lalu tautkan konteks fase dan pesan manusia yang dibalas.
        def operation(db):
            room_id = queries.ensure_room(db, self.room_code)
            message_id = queries.insert_message(
                db,
                room_id=room_id,
                player_id=None,
                username=username,
                message=message,
            )
            queries.set_message_context(
                db, message_id, sender_kind="bot", context=context, reply_to_id=reply_to_id
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

    # SERVICE PENYIMPANAN: simpan nama fase ruangan; fungsi ini tidak menjalankan timer/voting.
    def set_phase(self, phase: str) -> None:
        # CALLBACK TRANSAKSI: pastikan ruangan ada lalu simpan fase yang diminta.
        def operation(database):
            queries.set_phase(database, queries.ensure_room(database, self.room_code), phase)

        self._run(operation)


persistence_service = PersistenceService()

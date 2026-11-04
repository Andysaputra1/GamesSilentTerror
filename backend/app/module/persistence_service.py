"""Penyimpanan data game. Sebagian besar SQL ada di models; setiap aksi satu transaksi."""

from __future__ import annotations
import json
import logging
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.module.mysql_connector import SessionLocal
from app.models import game_queries as queries

logger = logging.getLogger("shadow_heist.persistence")


class PersistenceError(RuntimeError):
    """Transaksi game gagal disimpan."""


class PersistenceService:
    # CONSTRUCTOR: pilih kode ruangan penyimpanan.
    def __init__(self, room_code: str):
        self.room_code = room_code

    @staticmethod
    # STATIC METHOD TRANSAKSI: jalankan callback dengan commit/rollback otomatis dan terjemahkan error SQL.
    def _run(operasi):
        try:
            with SessionLocal.begin() as database:
                return operasi(database)
        except SQLAlchemyError as error:
            # Parameter SQL tidak dicatat karena bisa memuat isi chat privat.
            logger.error("Game database transaction failed (%s).", type(error).__name__)
            raise PersistenceError("Data game gagal disimpan ke database.") from error

    # HELPER TRANSAKSI: pastikan ruangan dan pemain tersedia, lalu kembalikan kedua ID-nya.
    def _pastikan_room_dan_pemain(self, database, username):
        id_room = queries.ensure_room(database, self.room_code)
        return id_room, queries.ensure_player(database, id_room, username)

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
        def simpan_pesan_pemain(database):
            id_room, id_pemain = self._pastikan_room_dan_pemain(database, username)
            if status is not None:
                queries.update_player_status(database, id_pemain, status)
            id_pesan = queries.insert_message(
                database,
                room_id=id_room,
                player_id=id_pemain,
                username=username,
                message=message,
            )
            if context is not None:
                queries.set_message_context(
                    database, id_pesan, sender_kind="human", context=context
                )
            return id_pesan

        return self._run(simpan_pesan_pemain)

    # Arsipkan ruangan baru beserta pemiliknya sebelum dipakai bermain.
    def archive_new_room(self, username):
        # Simpan ruangan dan pemiliknya dalam satu transaksi agar arsip tidak setengah jadi.
        def simpan_room_baru(database):
            jumlah_baris_baru = database.execute(
                text("INSERT IGNORE INTO game_sessions(room_code,phase) VALUES(:code,'lobby')"),
                {"code": self.room_code},
            ).rowcount
            if not jumlah_baris_baru:
                return False
            self._pastikan_room_dan_pemain(database, username)
            return True

        return self._run(simpan_room_baru)

    # Simpan jejak checker sebagai arsip analisis ruangan.
    def record_trace(self, trace):
        self._run(
            lambda database: database.execute(
                text("""
            INSERT INTO checker_traces(id,room_code,trace) VALUES(:id,:room,:trace)
            ON DUPLICATE KEY UPDATE trace=:trace
        """),
                {"id": trace["id"], "room": self.room_code, "trace": json.dumps(trace)},
            )
        )

    # Bacaan NLU (intent, target) satu pesan untuk riwayat chat panel (kolom migrasi V9).
    def record_nlu(self, message_id, nlu):
        self._run(
            lambda database: database.execute(
                text("UPDATE chat_messages SET nlu=:nlu WHERE id=:id"),
                {"id": message_id, "nlu": json.dumps(nlu, ensure_ascii=False)},
            )
        )

    # Simpan pesan bot beserta konteks fase.
    def record_bot_message(self, *, username, message, context):
        # Simpan pesan bot lalu tautkan konteks fase.
        def simpan_pesan_bot(database):
            id_room = queries.ensure_room(database, self.room_code)
            id_pesan = queries.insert_message(
                database,
                room_id=id_room,
                player_id=None,
                username=username,
                message=message,
            )
            queries.set_message_context(database, id_pesan, sender_kind="bot", context=context)
            return id_pesan

        return self._run(simpan_pesan_bot)


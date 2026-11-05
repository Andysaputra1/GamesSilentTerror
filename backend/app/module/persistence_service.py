"""Penyimpanan data game. Sebagian besar SQL ada di models; setiap aksi satu transaksi."""

from __future__ import annotations
import json

# PersistenceError ikut diimpor agar file lain tetap bisa mengimpornya dari modul ini.
from app.config.database import PersistenceError, jalankan_transaksi  # noqa: F401
from app.models import game_queries as queries

# sockets/chat.py mengirim teks ini ke pemain saat pesan chat gagal disimpan.
PESAN_GAME = "Data game gagal disimpan ke database."


class PersistenceService:
    # CONSTRUCTOR: pilih kode ruangan penyimpanan.
    def __init__(self, room_code: str):
        self.room_code = room_code

    # HELPER TRANSAKSI: pastikan ruangan dan pemain tersedia, lalu kembalikan kedua ID-nya.
    def _pastikan_room_dan_pemain(self, database, username):
        id_room = queries.ensure_room(database, self.room_code)
        return id_room, queries.ensure_player(database, id_room, username)

    # Simpan pesan pemain dan konteks fase dalam satu transaksi.
    def record_player_message(
        self,
        *,
        username: str,
        message: str,
        context: dict | None = None,
    ) -> int:
        # Pastikan pemain ada, simpan pesan, lalu kembalikan ID pesan.
        def simpan_pesan_pemain(database):
            id_room, id_pemain = self._pastikan_room_dan_pemain(database, username)
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

        return jalankan_transaksi(simpan_pesan_pemain, PESAN_GAME)

    # Arsipkan ruangan baru beserta pemiliknya sebelum dipakai bermain.
    def archive_new_room(self, username):
        # Simpan ruangan dan pemiliknya dalam satu transaksi agar arsip tidak setengah jadi.
        def simpan_room_baru(database):
            jumlah_baris_baru = queries.insert_lobby_room(database, self.room_code)
            if not jumlah_baris_baru:
                return False
            self._pastikan_room_dan_pemain(database, username)
            return True

        return jalankan_transaksi(simpan_room_baru, PESAN_GAME)

    # Simpan jejak checker sebagai arsip analisis ruangan.
    def record_trace(self, trace):
        jalankan_transaksi(
            lambda database: queries.save_checker_trace(
                database, trace["id"], self.room_code, json.dumps(trace)
            ),
            PESAN_GAME,
        )

    # Bacaan NLU (intent, target) satu pesan untuk riwayat chat panel (kolom migrasi V9).
    def record_nlu(self, message_id, nlu):
        jalankan_transaksi(
            lambda database: queries.set_message_nlu(
                database, message_id, json.dumps(nlu, ensure_ascii=False)
            ),
            PESAN_GAME,
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

        return jalankan_transaksi(simpan_pesan_bot, PESAN_GAME)

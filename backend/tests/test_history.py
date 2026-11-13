import unittest
from unittest.mock import Mock, patch
from app.services.room_service import RoomService
from tests.palsu.bot_lobby import isi_kursi_bot
from app.services.persistence_service import PersistenceError
from app.sockets import chat
from tests.palsu.socket_palsu import socket_palsu


class ChatDurabilityTests(unittest.IsolatedAsyncioTestCase):
    async def run_chat(self, *, db_fails=False):
        rooms = RoomService()
        room = rooms.create("alice")
        isi_kursi_bot(rooms, room.code, "alice")
        persistence = Mock()
        persistence.record_player_message.return_value = 42
        if db_fails:
            persistence.record_player_message.side_effect = PersistenceError("DB unavailable")
        sambungan = {"sid": {"username": "alice", "token": "alice", "room": room.code}}
        with (
            socket_palsu(rooms, sambungan) as sio,
            patch("app.services.chat_service.PersistenceService", return_value=persistence),
        ):
            await chat.send_chat("sid", {"username": "alice", "message": "Halo bot"})
        chats = [c.args[1] for c in sio.emit.call_args_list if c.args[0] == "receive_chat"]
        return persistence, chats

    # Chat manusia disimpan lalu disiarkan; tidak ada balasan bot langsung (bot membaca lewat NPCService).
    async def test_human_saved_then_echoed_without_direct_bot_reply(self):
        persistence, chats = await self.run_chat()
        self.assertEqual(persistence.record_player_message.call_args.kwargs["message"], "Halo bot")
        persistence.record_bot_message.assert_not_called()
        self.assertEqual([c["sender"] for c in chats], ["alice"])

    # players.status tidak pernah berubah di jalur chat, jadi chat tidak perlu menulisnya.
    async def test_chat_does_not_write_player_status(self):
        persistence, _ = await self.run_chat()
        self.assertNotIn("status", persistence.record_player_message.call_args.kwargs)

    async def test_database_failure_prevents_echo(self):
        _, chats = await self.run_chat(db_fails=True)
        self.assertEqual(chats, [])

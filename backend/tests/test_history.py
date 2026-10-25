import unittest
from unittest.mock import Mock, AsyncMock, patch
from app.services.room_service import RoomService
from app.services.persistence_service import PersistenceError
from app.realtime.socket_handlers import SocketGameController


class ChatDurabilityTests(unittest.IsolatedAsyncioTestCase):
    async def run_chat(self, *, db_fails=False):
        rooms = RoomService()
        room = rooms.create("alice")
        rooms.set_bot(room.code, "alice", True)
        sio = Mock(emit=AsyncMock(), enter_room=AsyncMock())
        persistence = Mock()
        persistence.record_player_message.return_value = 42
        if db_fails:
            persistence.record_player_message.side_effect = PersistenceError("DB unavailable")
        controller = SocketGameController(sio, Mock())
        controller.socket_players["sid"] = "alice"
        controller.socket_rooms["sid"] = room.code
        with (
            patch("app.realtime.socket_handlers.room_service", rooms),
            patch("app.realtime.socket_handlers.PersistenceService", return_value=persistence),
        ):
            await controller.send_chat("sid", {"username": "alice", "message": "Halo bot"})
        chats = [c.args[1] for c in sio.emit.call_args_list if c.args[0] == "receive_chat"]
        return persistence, chats

    # Chat manusia disimpan lalu disiarkan; tidak ada balasan bot langsung (bot membaca lewat NPCService).
    async def test_human_saved_then_echoed_without_direct_bot_reply(self):
        persistence, chats = await self.run_chat()
        self.assertEqual(persistence.record_player_message.call_args.kwargs["message"], "Halo bot")
        persistence.record_bot_message.assert_not_called()
        self.assertEqual([c["sender"] for c in chats], ["alice"])

    async def test_database_failure_prevents_echo(self):
        _, chats = await self.run_chat(db_fails=True)
        self.assertEqual(chats, [])

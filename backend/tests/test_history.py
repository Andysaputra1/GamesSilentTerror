import unittest
from types import SimpleNamespace
from unittest.mock import Mock, AsyncMock, patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from controller.api.history import router
from controller.middleware.auth import require_authenticated_user
from config.settings import settings
from services.room_service import RoomService
from services.persistence_service import PersistenceError
from realtime.socket_handlers import SocketGameController


class HistoryAccessTests(unittest.TestCase):
    def setUp(self):
        app = FastAPI()
        app.include_router(router)
        self.app = app
        self.client = TestClient(app)

    def test_anonymous_and_non_admin_cannot_read(self):
        self.assertEqual(self.client.get("/api/history/messages").status_code, 401)
        self.app.dependency_overrides[require_authenticated_user] = lambda: SimpleNamespace(
            username="alice"
        )
        with patch.object(settings, "history_admin_usernames", ""):
            self.assertEqual(self.client.get("/api/history/messages").status_code, 403)

    def test_admin_pagination_and_no_store(self):
        self.app.dependency_overrides[require_authenticated_user] = lambda: SimpleNamespace(
            username="alice"
        )
        with (
            patch.object(settings, "history_admin_usernames", "alice"),
            patch(
                "controller.api.history.PersistenceService._run",
                return_value=[{"id": 10}, {"id": 11}],
            ),
        ):
            response = self.client.get("/api/history/messages?limit=1")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers["cache-control"], "no-store")
            self.assertEqual(
                response.json(), {"messages": [{"id": 10}], "has_more": True, "next_after_id": 10}
            )
            self.assertEqual(self.client.get("/api/history/messages?limit=501").status_code, 422)


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
            patch("realtime.socket_handlers.room_service", rooms),
            patch("realtime.socket_handlers.PersistenceService", return_value=persistence),
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

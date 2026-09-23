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
    async def run_chat(self, *, ai_fails=False, db_fails=False, bot_db_fails=False):
        rooms = RoomService()
        room = rooms.create("alice")
        rooms.set_bot(room.code, "alice", True)
        sio = Mock(emit=AsyncMock(), enter_room=AsyncMock())
        analysis = Mock()
        analysis.predict_intent.return_value = "neutral"
        analysis.aggressiveness_for_intent.return_value = 0
        persistence = Mock()
        persistence.record_player_message.return_value = 42
        if db_fails:
            persistence.record_player_message.side_effect = PersistenceError("DB unavailable")
        if bot_db_fails:
            persistence.record_bot_message.side_effect = PersistenceError("DB unavailable")

        async def respond(**kwargs):
            persistence.record_player_message.assert_called_once()
            self.assertTrue(any(call.args[0] == "receive_chat" for call in sio.emit.call_args_list))
            if ai_fails:
                raise RuntimeError("simulated provider failure")
            return "Halo pemain"

        analysis.create_host_response = AsyncMock(side_effect=respond)
        controller = SocketGameController(sio, analysis, Mock())
        controller.socket_players["sid"] = "alice"
        controller.socket_rooms["sid"] = room.code
        controller.room_analysis[room.code] = analysis
        with (
            patch("realtime.socket_handlers.room_service", rooms),
            patch("realtime.socket_handlers.PersistenceService", return_value=persistence),
        ):
            await controller.send_chat("sid", {"username": "alice", "message": "Halo bot"})
        chats = [c.args[1] for c in sio.emit.call_args_list if c.args[0] == "receive_chat"]
        return persistence, analysis, chats

    async def test_human_saved_before_ai_even_when_provider_fails(self):
        persistence, _, chats = await self.run_chat(ai_fails=True)
        self.assertEqual(persistence.record_player_message.call_args.kwargs["message"], "Halo bot")
        persistence.record_bot_message.assert_not_called()
        self.assertEqual([c["sender"] for c in chats], ["alice"])

    async def test_database_failure_prevents_echo_and_ai(self):
        _, analysis, chats = await self.run_chat(db_fails=True)
        self.assertEqual(chats, [])
        analysis.create_host_response.assert_not_awaited()

    async def test_bot_saved_with_sender_and_parent(self):
        persistence, _, chats = await self.run_chat()
        kwargs = persistence.record_bot_message.call_args.kwargs
        self.assertEqual((kwargs["username"], kwargs["reply_to_id"]), ("NOX", 42))
        self.assertEqual([c["sender"] for c in chats], ["alice", "NOX"])

    async def test_bot_database_failure_preserves_human_only(self):
        _, _, chats = await self.run_chat(bot_db_fails=True)
        self.assertEqual([c["sender"] for c in chats], ["alice"])

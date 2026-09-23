import unittest
from unittest.mock import AsyncMock, Mock, patch

from services.room_service import RoomService
from realtime.socket_handlers import SocketGameController
from services.analysis_service import IntentModelNotReadyError


class RoomTests(unittest.TestCase):
    # SETUP TES: buat registry lobby baru sebelum setiap skenario agar state tes terpisah.
    def setUp(self):
        self.rooms = RoomService()

    # TES LOBBY: periksa kode ruangan, join tanpa duplikasi, dan hak pemilik untuk mengatur bot.
    def test_create_join_and_bot_permissions(self):
        room = self.rooms.create("alice")
        self.assertRegex(room.code, r"^[A-F0-9]{6}$")
        self.assertFalse(room.bot_enabled)
        self.rooms.join(room.code.lower(), "bob")
        self.rooms.join(room.code, "bob")
        self.assertEqual(room.members, ["alice", "bob"])
        with self.assertRaises(ValueError):
            self.rooms.set_bot(room.code, "bob", True)
        self.assertTrue(self.rooms.set_bot(room.code, "alice", True).bot_enabled)

    # TES LOBBY: tolak akses nonanggota, kode hilang, dan join melebihi kapasitas.
    def test_missing_nonmember_and_full_room(self):
        room = self.rooms.create("alice")
        with self.assertRaises(ValueError):
            self.rooms.get(room.code, "outsider")
        with self.assertRaises(ValueError):
            self.rooms.join("missing", "bob")
        for index in range(5):
            self.rooms.join(room.code, str(index))
        with self.assertRaises(ValueError):
            self.rooms.join(room.code, "overflow")


class SocketRoomTests(unittest.IsolatedAsyncioTestCase):
    # TES ASYNC SOCKET: simulasikan SVM tidak siap/AI gagal; pastikan error terlihat dan status menunggu dibersihkan.
    async def test_missing_model_and_ai_failure_are_visible(self):
        rooms = RoomService()
        room = rooms.create("alice")
        rooms.set_bot(room.code, "alice", True)
        sio = Mock(emit=AsyncMock(), enter_room=AsyncMock())
        analysis = Mock()
        analysis.predict_intent.side_effect = IntentModelNotReadyError()
        analysis.create_host_response = AsyncMock(side_effect=RuntimeError("test failure"))
        controller = SocketGameController(sio, analysis, Mock())
        controller.socket_players["sid"] = "alice"
        controller.socket_rooms["sid"] = room.code
        controller.room_analysis[room.code] = analysis
        with (
            patch("realtime.socket_handlers.room_service", rooms),
            patch("realtime.socket_handlers.PersistenceService"),
        ):
            await controller.send_chat("sid", {"username": "alice", "message": "Halo"})
            analysis.create_host_response.assert_not_awaited()
            self.assertTrue(
                any(
                    c.args[0] == "system_alert" and "SVM" in c.args[1]["msg"]
                    for c in sio.emit.call_args_list
                )
            )
            analysis.predict_intent.side_effect = None
            analysis.predict_intent.return_value = "neutral"
            analysis.aggressiveness_for_intent.return_value = 0
            sio.emit.reset_mock()
            await controller.send_chat("sid", {"username": "alice", "message": "Coba lagi"})
            self.assertNotIn("sid", controller.ai_pending)
            states = [
                c.args[1]["pending"] for c in sio.emit.call_args_list if c.args[0] == "ai_status"
            ]
            self.assertEqual(states, [True, False])
            self.assertTrue(
                any(
                    c.args[0] == "system_alert" and "gagal" in c.args[1]["msg"]
                    for c in sio.emit.call_args_list
                )
            )

    # TES ASYNC SOCKET: pastikan pesan terisolasi per ruangan dan AI hanya dipanggil ketika bot aktif.
    async def test_chat_scoped_and_no_bot_when_disabled(self):
        rooms = RoomService()
        room = rooms.create("alice")
        other = rooms.create("bob")
        sio = Mock(emit=AsyncMock(), enter_room=AsyncMock())
        analysis = Mock()
        analysis.predict_intent.return_value = "neutral"
        analysis.aggressiveness_for_intent.return_value = 0
        analysis.create_host_response = AsyncMock(return_value="Halo")
        controller = SocketGameController(sio, analysis, Mock())
        controller.socket_players["sid"] = "alice"
        controller.socket_rooms["sid"] = room.code
        controller.room_analysis[room.code] = analysis
        with (
            patch("realtime.socket_handlers.room_service", rooms),
            patch("realtime.socket_handlers.PersistenceService"),
        ):
            await controller.send_chat("sid", {"username": "alice", "message": "Halo"})
            analysis.create_host_response.assert_not_awaited()
            self.assertTrue(
                any(
                    c.args[0] == "system_alert" and "belum ditambahkan" in c.args[1]["msg"]
                    for c in sio.emit.call_args_list
                )
            )
            chats = [c for c in sio.emit.call_args_list if c.args[0] == "receive_chat"]
            self.assertEqual(len(chats), 1)
            self.assertEqual(chats[0].kwargs["to"], room.code)
            self.assertNotEqual(chats[0].kwargs["to"], other.code)
            rooms.set_bot(room.code, "alice", True)
            await controller.send_chat("sid", {"username": "alice", "message": "NOX?"})
            analysis.create_host_response.assert_awaited_once()
            self.assertEqual(sio.emit.call_args.args[1]["sender"], "NOX")
            self.assertEqual(sio.emit.call_args.kwargs["to"], room.code)

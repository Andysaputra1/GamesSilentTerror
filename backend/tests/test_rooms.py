import unittest
from unittest.mock import AsyncMock, Mock, patch

from app.module.room_service import RoomService
from app.realtime.socket_handlers import SocketGameController
from app.module.checker_service import checker_service
from app.module.auth_service import SessionValidationError


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

    # Setelah pertandingan selesai, pemain langsung boleh membuat atau bergabung ke room baru;
    # lobby yang belum mulai tetap menahan pemain di satu room.
    def test_finished_match_releases_members_for_a_new_room(self):
        lama = self.rooms.create("alice", capacity=4)
        self.rooms.join(lama.code, "bob")
        self.rooms.set_bot(lama.code, "alice", True)
        self.rooms.start(lama.code, "alice")
        lama.match.finish("civilians", "hitman_executed", "Hitman dieksekusi.")
        baru = self.rooms.create("alice")
        self.assertIs(self.rooms.current("alice"), baru)
        self.rooms.join(baru.code, "bob")
        self.assertEqual(baru.members, ["alice", "bob"])
        self.assertNotIn(lama.code, self.rooms.rooms)  # room lama yang kosong dibersihkan
        with self.assertRaises(ValueError):
            self.rooms.create("bob")  # masih anggota lobby baru yang belum mulai


class SocketRoomTests(unittest.IsolatedAsyncioTestCase):
    async def test_passive_socket_loses_broadcast_access_after_leave_or_logout(self):
        rooms = RoomService()
        room = rooms.create("alice")
        rooms.join(room.code, "bob")
        sio = Mock(emit=AsyncMock(), leave_room=AsyncMock())
        controller = SocketGameController(sio, Mock())
        controller.socket_players.update({"alice-sid": "alice", "bob-sid": "bob"})
        controller.socket_rooms.update({"alice-sid": room.code, "bob-sid": room.code})
        rooms.leave(room.code, "bob")
        with patch("app.realtime.socket_handlers.room_service", rooms):
            await controller.emit_room("receive_chat", {"message": "private room"}, to=room.code)
            sio.leave_room.assert_awaited_once_with("bob-sid", room.code)
            sio.leave_room.reset_mock()
            rooms.join(room.code, "bob")
            controller.socket_tokens["bob-sid"] = "revoked-session"
            with patch(
                "app.realtime.socket_handlers.auth_service.user_for_token",
                side_effect=SessionValidationError("revoked"),
            ):
                await controller.emit_room("receive_chat", {"message": "next"}, to=room.code)
            sio.leave_room.assert_awaited_once_with("bob-sid", room.code)

    async def test_human_chat_rechecks_phase_and_gag_before_saving(self):
        for change in ["night", "gag"]:
            with self.subTest(change=change):
                rooms = RoomService()
                room = rooms.create("alice")
                rooms.set_bot(room.code, "alice", True)
                rooms.start(room.code, "alice")
                sio = Mock(emit=AsyncMock(), enter_room=AsyncMock())
                real_begin = checker_service.begin

                # Fase/Gag berubah di antara otorisasi pertama dan penyimpanan (mis. aksi HTTP bersamaan).
                def begin(*args):
                    if change == "night":
                        room.match.phase = "night"
                    else:
                        room.match.players["alice"].gagged = True
                    return real_begin(*args)

                controller = SocketGameController(sio, Mock())
                controller.socket_players["sid"] = "alice"
                controller.socket_rooms["sid"] = room.code
                with (
                    patch("app.realtime.socket_handlers.room_service", rooms),
                    patch("app.realtime.socket_handlers.PersistenceService") as persistence,
                    patch("app.realtime.socket_handlers.checker_service.begin", side_effect=begin),
                ):
                    await controller.send_chat("sid", {"username": "alice", "message": "Halo"})
                persistence.return_value.record_player_message.assert_not_called()
                self.assertEqual(room.match.messages, [])
                self.assertFalse(any(c.args[0] == "receive_chat" for c in sio.emit.call_args_list))

    # TES ASYNC SOCKET: pesan hanya disiarkan ke ruangan pengirim dan tidak dibalas bot secara langsung.
    async def test_chat_scoped_to_room_without_direct_bot_reply(self):
        rooms = RoomService()
        room = rooms.create("alice")
        other = rooms.create("bob")
        rooms.set_bot(room.code, "alice", True)
        sio = Mock(emit=AsyncMock(), enter_room=AsyncMock())
        controller = SocketGameController(sio, Mock())
        controller.socket_players["sid"] = "alice"
        controller.socket_rooms["sid"] = room.code
        with (
            patch("app.realtime.socket_handlers.room_service", rooms),
            patch("app.realtime.socket_handlers.PersistenceService") as persistence,
        ):
            await controller.send_chat("sid", {"username": "alice", "message": "Halo"})
        chats = [c for c in sio.emit.call_args_list if c.args[0] == "receive_chat"]
        self.assertEqual(len(chats), 1)
        self.assertEqual(chats[0].args[1]["sender"], "alice")
        self.assertEqual(chats[0].kwargs["to"], room.code)
        self.assertNotEqual(chats[0].kwargs["to"], other.code)
        persistence.return_value.record_bot_message.assert_not_called()


class TickAllTests(unittest.TestCase):
    # Satu pertandingan yang error tidak boleh menghentikan timer room lain.
    def test_broken_match_does_not_stop_other_rooms(self):
        rooms = RoomService()
        rusak, sehat = rooms.create("alice"), rooms.create("bob")
        rusak.match = Mock(tick=Mock(side_effect=RuntimeError("rusak")), phase="day", round=1)
        sehat.match = Mock(phase="day", round=1)
        with self.assertLogs("shadow_heist.rooms", "ERROR"):
            rooms.tick_all()
        sehat.match.tick.assert_called_once()


class DisplayNameRoomTests(unittest.TestCase):
    # Lobby dan pertandingan memakai nama tampilan akun; username tetap kunci anggota.
    def test_lobby_and_match_use_display_names(self):
        rooms = RoomService()
        profil = {"alice": ("dexter", "Alice Wonder"), "bob": ("jenny", "Alice Wonder")}
        with patch.object(
            RoomService, "_fetch_profiles", lambda self, names: {n: profil[n] for n in names}
        ):
            room = rooms.create("alice")
            rooms.join(room.code, "bob")
            rooms.set_bot(room.code, "alice", True)
            lobby = rooms.snapshot(room)
            self.assertEqual(
                [m["label"] for m in lobby["members"]], ["Alice Wonder", "Alice Wonder"]
            )
            rooms.start(room.code, "alice")
        labels = room.match.labels
        self.assertEqual(labels["alice"], "Alice Wonder (alice)")  # nama sama → diberi penanda
        self.assertEqual(labels["bob"], "Alice Wonder (bob)")
        self.assertEqual(labels["NOX"], "NOX")

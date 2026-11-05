import unittest
from unittest.mock import Mock, patch

from sqlalchemy.exc import OperationalError

from app.services.room_service import RoomService
from app.services.checker_service import checker_service
from app.services.auth_service import SessionValidationError
from app.sockets import chat, server
from socket_palsu import socket_palsu

DATABASE_GAGAL = OperationalError("SELECT", {}, Exception("server hilang"))


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
        sambungan = {
            "alice-sid": {"username": "alice", "token": "alice", "room": room.code},
            "bob-sid": {"username": "bob", "token": "bob", "room": room.code},
        }
        rooms.leave(room.code, "bob")

        # Token palsu berisi username; hanya sesi yang dicabut yang ditolak.
        def cek_token(token):
            if token == "revoked-session":
                raise SessionValidationError("revoked")
            return Mock(username=token)

        with socket_palsu(rooms, sambungan, cek_token) as sio:
            await server.emit_room("receive_chat", {"message": "private room"}, to=room.code)
            sio.leave_room.assert_awaited_once_with("bob-sid", room.code)
            sio.leave_room.reset_mock()
            rooms.join(room.code, "bob")
            server.sockets["bob-sid"]["token"] = "revoked-session"
            await server.emit_room("receive_chat", {"message": "next"}, to=room.code)
            sio.leave_room.assert_awaited_once_with("bob-sid", room.code)

    # connect selalu mengisi token, jadi catatan tanpa token tidak boleh lolos tanpa dicek.
    async def test_socket_record_without_token_is_not_trusted(self):
        rooms = RoomService()
        room = rooms.create("alice")
        sambungan = {"sid": {"username": "alice", "room": room.code}}
        with socket_palsu(rooms, sambungan), self.assertRaises(KeyError):
            server.verifikasi_socket("sid", "alice")

    # Database sempat gagal bukan berarti sesinya berakhir: pemain tetap di kanal dan tetap menerima chat.
    async def test_database_failure_keeps_socket_in_room_channel(self):
        rooms = RoomService()
        room = rooms.create("alice")
        sambungan = {"sid": {"username": "alice", "token": "token-uji", "room": room.code}}
        with (
            socket_palsu(rooms, sambungan, cek_token=None) as sio,
            patch("app.models.auth_queries.account_by_token", side_effect=DATABASE_GAGAL),
            self.assertLogs("shadow_heist.socket", "WARNING"),
        ):
            await server.emit_room("receive_chat", {"message": "halo"}, to=room.code)
        sio.leave_room.assert_not_awaited()
        sio.emit.assert_awaited_once_with("receive_chat", {"message": "halo"}, to=room.code)

    # Pengirim harus tahu layanannya yang bermasalah, bukan disuruh login ulang.
    async def test_database_failure_tells_sender_login_service_unavailable(self):
        rooms = RoomService()
        room = rooms.create("alice")
        sambungan = {"sid": {"username": "alice", "token": "token-uji", "room": room.code}}
        with (
            socket_palsu(rooms, sambungan, cek_token=None) as sio,
            patch("app.models.auth_queries.account_by_token", side_effect=DATABASE_GAGAL),
        ):
            await chat.send_chat("sid", {"username": "alice", "message": "halo"})
        sio.emit.assert_awaited_once_with(
            "system_alert", {"msg": "Layanan login sedang tidak tersedia."}, to="sid"
        )

    async def test_human_chat_rechecks_phase_and_gag_before_saving(self):
        for change in ["night", "gag"]:
            with self.subTest(change=change):
                rooms = RoomService()
                room = rooms.create("alice")
                rooms.set_bot(room.code, "alice", True)
                rooms.start(room.code, "alice")
                real_begin = checker_service.begin

                # Fase/Gag berubah di antara otorisasi pertama dan penyimpanan (mis. aksi HTTP bersamaan).
                def begin(*args):
                    if change == "night":
                        room.match.phase = "night"
                    else:
                        room.match.players["alice"].gagged = True
                    return real_begin(*args)

                sambungan = {"sid": {"username": "alice", "token": "alice", "room": room.code}}
                with (
                    socket_palsu(rooms, sambungan) as sio,
                    patch("app.services.chat_service.PersistenceService") as persistence,
                    patch("app.services.chat_service.checker_service.begin", side_effect=begin),
                ):
                    await chat.send_chat("sid", {"username": "alice", "message": "Halo"})
                persistence.return_value.record_player_message.assert_not_called()
                self.assertEqual(room.match.messages, [])
                self.assertFalse(any(c.args[0] == "receive_chat" for c in sio.emit.call_args_list))

    # Hanya penolakan yang menjadi system_alert; error sesudah pesan terkirim tidak boleh tampil sebagai penolakan.
    async def test_error_after_delivery_is_not_sent_as_rejection(self):
        rooms = RoomService()
        room = rooms.create("alice")
        rooms.set_bot(room.code, "alice", True)
        rooms.start(room.code, "alice")
        room.match.phase = "day"
        sambungan = {"sid": {"username": "alice", "token": "alice", "room": room.code}}
        with (
            socket_palsu(rooms, sambungan) as sio,
            patch("app.services.chat_service.PersistenceService"),
            patch("app.services.chat_service.catat_nlu", side_effect=ValueError("rusak")),
            self.assertRaises(ValueError),
        ):
            await chat.send_chat("sid", {"username": "alice", "message": "Halo"})
        self.assertEqual([c.args[0] for c in sio.emit.call_args_list], ["receive_chat"])

    # TES ASYNC SOCKET: pesan hanya disiarkan ke ruangan pengirim dan tidak dibalas bot secara langsung.
    async def test_chat_scoped_to_room_without_direct_bot_reply(self):
        rooms = RoomService()
        room = rooms.create("alice")
        other = rooms.create("bob")
        rooms.set_bot(room.code, "alice", True)
        sambungan = {"sid": {"username": "alice", "token": "alice", "room": room.code}}
        with (
            socket_palsu(rooms, sambungan) as sio,
            patch("app.services.chat_service.PersistenceService") as persistence,
        ):
            await chat.send_chat("sid", {"username": "alice", "message": "Halo"})
        chats = [c for c in sio.emit.call_args_list if c.args[0] == "receive_chat"]
        self.assertEqual(len(chats), 1)
        self.assertEqual(chats[0].args[1]["sender"], "alice")
        self.assertEqual(chats[0].kwargs["to"], room.code)
        self.assertNotEqual(chats[0].kwargs["to"], other.code)
        persistence.return_value.record_bot_message.assert_not_called()

    # Tes lain memanggil fungsinya langsung, jadi tes ini yang menjaga event benar-benar terpasang saat server nyala.
    def test_main_uses_one_sio_for_browser_events_and_bot_chat(self):
        from app import main

        self.assertIs(main.sio, server.sio)
        self.assertEqual(
            {nama: server.sio.handlers["/"][nama] for nama in ("connect", "disconnect", "send_chat")},
            {"connect": chat.connect, "disconnect": chat.disconnect, "send_chat": chat.send_chat},
        )
        self.assertIs(main.npc_service.broadcast, server.emit_room)


class TickAllTests(unittest.TestCase):
    # Satu pertandingan yang error tidak boleh menghentikan timer room lain.
    def test_broken_match_does_not_stop_other_rooms(self):
        rooms = RoomService()
        rusak, sehat = rooms.create("alice"), rooms.create("bob")
        rusak.match = Mock(tick=Mock(side_effect=RuntimeError("rusak")), phase="day", round=1)
        sehat.match = Mock(phase="day", round=1)
        with self.assertLogs("shadow_heist.rooms", "ERROR"):
            rooms.perbarui_fase_semua_room()
        sehat.match.tick.assert_called_once()


class DisplayNameRoomTests(unittest.TestCase):
    # Lobby dan pertandingan memakai nama tampilan akun; username tetap kunci anggota.
    def test_lobby_and_match_use_display_names(self):
        rooms = RoomService()
        profil = {"alice": ("dexter", "Alice Wonder"), "bob": ("jenny", "Alice Wonder")}
        with patch.object(
            RoomService, "_ambil_profil_akun", lambda self, names: {n: profil[n] for n in names}
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

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from app.controllers import rooms as rooms_controller
from app.controllers.rooms import router
from app.middleware.auth import require_authenticated_user
from app.services import room_service as modul_room
from app.services.room_service import BOT_MAKS, PESAN_ROOM_TERTUTUP, RoomService
from tests.palsu.bot_lobby import isi_kursi_bot
from app.services.checker_service import checker_service
from app.services.auth_service import SessionValidationError
from app.sockets import chat, server
from tests.palsu.socket_palsu import socket_palsu

DATABASE_GAGAL = OperationalError("SELECT", {}, Exception("server hilang"))


class RoomTests(unittest.TestCase):
    # SETUP TES: buat registry lobby baru sebelum setiap skenario agar state tes terpisah.
    def setUp(self):
        self.rooms = RoomService()

    # TES LOBBY: periksa kode ruangan, join tanpa duplikasi, dan hak pemilik untuk mengatur bot.
    def test_create_join_and_bot_permissions(self):
        room = self.rooms.create("alice")
        self.assertRegex(room.code, r"^[A-F0-9]{6}$")
        self.assertEqual(room.jumlah_bot, 0)
        self.rooms.join(room.code.lower(), "bob")
        self.rooms.join(room.code, "bob")
        self.assertEqual(room.members, ["alice", "bob"])
        with self.assertRaises(ValueError):
            self.rooms.ubah_bot(room.code, "bob", "tambah")
        self.assertEqual(self.rooms.ubah_bot(room.code, "alice", "tambah").jumlah_bot, 1)

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

    # L10: kode yang tidak ada dan room yang bukan milik kita memberi pesan yang sama, jadi kode tidak bisa ditebak
    # dengan membedakan pesan error.
    def test_missing_and_foreign_room_give_the_same_message(self):
        lobby = self.rooms.create("alice")
        bertanding = self.rooms.create("bob", capacity=4)
        isi_kursi_bot(self.rooms, bertanding.code, "bob")
        self.rooms.start(bertanding.code, "bob")
        for kode in ("ZZZZZZ", lobby.code, bertanding.code):
            with self.subTest(kode=kode), self.assertRaisesRegex(ValueError, PESAN_ROOM_TERTUTUP):
                self.rooms.get(kode, "outsider")

    # Setelah pertandingan selesai, pemain langsung boleh membuat atau bergabung ke room baru;
    # lobby yang belum mulai tetap menahan pemain di satu room.
    def test_finished_match_releases_members_for_a_new_room(self):
        lama = self.rooms.create("alice", capacity=4)
        self.rooms.join(lama.code, "bob")
        isi_kursi_bot(self.rooms, lama.code, "alice")
        self.rooms.start(lama.code, "alice")
        lama.match.finish("civilians", "hitman_executed", "Hitman dieksekusi.")
        baru = self.rooms.create("alice")
        self.assertIs(self.rooms.current("alice"), baru)
        self.rooms.join(baru.code, "bob")
        self.assertEqual(baru.members, ["alice", "bob"])
        self.assertNotIn(lama.code, self.rooms.rooms)  # room lama yang kosong dibersihkan
        with self.assertRaises(ValueError):
            self.rooms.create("bob")  # masih anggota lobby baru yang belum mulai


class BotLobbyTests(unittest.TestCase):
    """Host menambah atau mengurangi bot satu per satu, paling banyak BOT_MAKS, dan hanya selama masih di lobby."""

    def setUp(self):
        self.rooms = RoomService()

    # Room milik alice, lalu alice menekan tombol bot sebanyak `tekan` kali.
    # Alur: 1 buat room -> 2 tekan Tambah bot -> 3 kembalikan room
    def room_dengan_bot(self, tekan=0, capacity=6):
        room = self.rooms.create("alice", capacity=capacity)
        for _ in range(tekan):
            self.rooms.ubah_bot(room.code, "alice", "tambah")
        return room

    def test_tambah_satu_per_satu_sesuai_urutan_nama(self):
        room = self.room_dengan_bot()
        self.assertEqual(self.rooms.snapshot(room)["bots"], [])
        for jumlah in range(1, 4):
            self.rooms.ubah_bot(room.code, "alice", "tambah")
            lobby = self.rooms.snapshot(room)
            self.assertEqual(lobby["bots"], ["NOX", "ECHO", "VEIL"][:jumlah])
            self.assertEqual((lobby["bot_count"], lobby["bot_max"]), (jumlah, BOT_MAKS))
        self.assertNotIn("bot_enabled", lobby)

    def test_paling_banyak_lima_bot_walau_kursi_masih_kosong(self):
        room = self.room_dengan_bot(tekan=BOT_MAKS, capacity=10)
        self.assertEqual(BOT_MAKS, 5)
        with self.assertRaisesRegex(ValueError, "Bot paling banyak 5."):
            self.rooms.ubah_bot(room.code, "alice", "tambah")
        self.assertEqual(self.rooms.bot_names(room), ["NOX", "ECHO", "VEIL", "RAVEN", "ASH"])

    def test_kursi_penuh_menolak_bot_baru(self):
        room = self.room_dengan_bot(tekan=3, capacity=4)
        with self.assertRaisesRegex(ValueError, "Kursi penuh"):
            self.rooms.ubah_bot(room.code, "alice", "tambah")
        self.assertEqual(len(self.rooms.bot_names(room)), 3)

    def test_kurangi_sampai_nol_lalu_ditolak(self):
        room = self.room_dengan_bot(tekan=3)
        for sisa in (2, 1, 0):
            self.rooms.ubah_bot(room.code, "alice", "kurangi")
            self.assertEqual(len(self.rooms.bot_names(room)), sisa)
        with self.assertRaisesRegex(ValueError, "Belum ada bot"):
            self.rooms.ubah_bot(room.code, "alice", "kurangi")
        with self.assertRaises(ValueError):
            self.rooms.ubah_bot(room.code, "alice", "hapus")

    # Kursi penuh: manusia baru menggantikan bot terakhir; bila ia keluar sebelum mulai, bot itu kembali.
    # Tombol berikutnya dihitung dari bot yang ikut, jadi Kurangi tetap mengurangi tepat satu.
    def test_manusia_masuk_menggantikan_bot_terakhir(self):
        room = self.room_dengan_bot(tekan=5)
        self.rooms.join(room.code, "bob")
        self.assertEqual(self.rooms.bot_names(room), ["NOX", "ECHO", "VEIL", "RAVEN"])
        with self.assertRaisesRegex(ValueError, "Kursi penuh"):
            self.rooms.ubah_bot(room.code, "alice", "tambah")
        self.rooms.leave(room.code, "bob")
        self.assertEqual(len(self.rooms.bot_names(room)), 5)
        self.rooms.join(room.code, "bob")
        self.rooms.ubah_bot(room.code, "alice", "kurangi")
        self.assertEqual(self.rooms.bot_names(room), ["NOX", "ECHO", "VEIL"])

    def test_hanya_host_di_lobby_yang_boleh_mengatur_bot(self):
        room = self.room_dengan_bot(tekan=1)
        self.rooms.join(room.code, "bob")
        for orang in ("bob", "outsider"):
            with self.subTest(orang=orang), self.assertRaises(ValueError):
                self.rooms.ubah_bot(room.code, orang, "tambah")
        with self.assertRaisesRegex(ValueError, "Hanya pembuat ruangan"):
            self.rooms.ubah_bot(room.code, "bob", "kurangi")
        self.assertEqual(len(self.rooms.bot_names(room)), 1)

    def test_bot_terkunci_sesudah_pertandingan_mulai(self):
        room = self.room_dengan_bot(tekan=3)
        self.rooms.start(room.code, "alice")
        for aksi in ("tambah", "kurangi"):
            with (
                self.subTest(aksi=aksi),
                self.assertRaisesRegex(ValueError, "setelah pertandingan"),
            ):
                self.rooms.ubah_bot(room.code, "alice", aksi)
        lobby = self.rooms.snapshot(room)
        self.assertEqual((sorted(lobby["bots"]), lobby["bot_count"]), (["ECHO", "NOX", "VEIL"], 3))

    def test_mulai_dengan_kurang_dari_empat_peserta_memberi_pesan_jelas(self):
        room = self.room_dengan_bot(tekan=2)
        with self.assertRaisesRegex(ValueError, "minimal 4 peserta"):
            self.rooms.start(room.code, "alice")
        self.assertIsNone(room.match)
        self.rooms.ubah_bot(room.code, "alice", "tambah")
        self.rooms.start(room.code, "alice")
        self.assertEqual(len(room.match.players), 4)

    def test_api_bot_menerima_satu_aksi_dan_mengembalikan_snapshot(self):
        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[require_authenticated_user] = lambda: SimpleNamespace(
            username="alice"
        )
        room = self.room_dengan_bot(tekan=4)
        jalur = f"/api/rooms/{room.code}/bot"
        with patch("app.controllers.rooms.room_service", self.rooms), TestClient(app) as client:
            lobby = client.post(jalur, json={"aksi": "tambah"})
            self.assertEqual(lobby.status_code, 200)
            self.assertEqual((lobby.json()["bot_count"], lobby.json()["bot_max"]), (5, 5))
            self.assertEqual(len(lobby.json()["bots"]), 5)
            ditolak = client.post(jalur, json={"aksi": "tambah"})
            self.assertEqual(
                (ditolak.status_code, ditolak.json()["detail"]), (400, "Bot paling banyak 5.")
            )
            for body in ({"enabled": True}, {"aksi": "hapus"}, {}):
                self.assertEqual(client.post(jalur, json=body).status_code, 422)
            self.assertEqual(client.post(jalur, json={"aksi": "kurangi"}).json()["bot_count"], 4)


# M1: lobby dan room selesai yang ditinggal (tanpa /leave) dihapus jam permainan; pertandingan berjalan tidak disentuh.
class RoomDiamTests(unittest.TestCase):
    def setUp(self):
        self.rooms = RoomService()

    def test_lobby_diam_satu_jam_dihapus_yang_masih_dipakai_tetap(self):
        diam, dipakai = self.rooms.create("alice"), self.rooms.create("bob")
        diam.disentuh -= modul_room.LOBBY_DIAM_DETIK + 1
        dipakai.disentuh -= modul_room.LOBBY_DIAM_DETIK + 1
        self.rooms.get(dipakai.code, "bob")  # lobby yang tabnya terbuka bertanya tiap 3 detik
        self.assertEqual(self.rooms.bersihkan_room_diam(), [diam.code])
        self.assertEqual(list(self.rooms.rooms), [dipakai.code])
        self.assertIsNone(self.rooms.current("alice"))
        self.rooms.create("alice")  # pemilik lobby yang dihapus bisa membuat room lagi

    def test_pertandingan_berjalan_tidak_dihapus_yang_selesai_tetap_bisa_disurvei(self):
        from app.services.survey_service import survey_service

        berjalan, selesai = self.rooms.create("alice", capacity=4), self.rooms.create("bob", capacity=4)
        for room, host in ((berjalan, "alice"), (selesai, "bob")):
            isi_kursi_bot(self.rooms, room.code, host)
            self.rooms.start(room.code, host)
            room.disentuh -= modul_room.SELESAI_DIAM_DETIK + 1
        selesai.match.finish("civilians", "hitman_executed", "Hitman dieksekusi.")
        with patch.object(survey_service, "catat_peserta") as catat:
            self.assertEqual(self.rooms.bersihkan_room_diam(), [selesai.code])
        self.assertIn(berjalan.code, self.rooms.rooms)
        # Peserta masuk arsip survei (MySQL) dan registri memori, jadi survei tetap bisa dikirim sesudah room hilang.
        self.assertTrue(selesai.peserta_tercatat)
        self.assertIn(selesai.match.id, survey_service._selesai)
        catat.assert_called_once()
        konteks = survey_service._context(selesai.code, "bob", selesai.match.id)
        self.assertEqual(konteks["match_id"], selesai.match.id)

    def test_batas_room_penuh_pulih_sesudah_pembersihan(self):
        with patch.object(modul_room, "ROOM_MAKS", 3):
            tertinggal = [self.rooms.create(f"pemain{nomor}") for nomor in range(3)]
            with self.assertRaisesRegex(ValueError, "Batas ruangan aktif"):
                self.rooms.create("baru")
            for room in tertinggal:
                room.disentuh -= modul_room.LOBBY_DIAM_DETIK
            self.assertEqual(len(self.rooms.bersihkan_room_diam()), 3)
            self.assertEqual(self.rooms.create("baru").owner, "baru")


# L10: /join yang gagal paling banyak 10 per akun per menit; sesudahnya kode yang benar pun ditolak 429, akun lain tidak.
class JoinLimitTests(unittest.TestCase):
    def setUp(self):
        rooms_controller._batas_join_akun.riwayat.clear()
        rooms_controller._batas_join_ip.riwayat.clear()

    tearDown = setUp

    def test_join_dibatasi_per_akun(self):
        rooms = RoomService()
        app = FastAPI()
        app.include_router(router)
        akun = {"nama": "penebak"}
        app.dependency_overrides[require_authenticated_user] = lambda: SimpleNamespace(
            username=akun["nama"]
        )
        room = rooms.create("alice")
        with patch("app.controllers.rooms.room_service", rooms), TestClient(app) as client:
            for _ in range(10):
                tebakan = client.post("/api/rooms/join", json={"code": "000000"})
                self.assertEqual(tebakan.status_code, 400)
            ditahan = client.post("/api/rooms/join", json={"code": room.code})
            self.assertEqual(ditahan.status_code, 429)
            self.assertIn("Retry-After", ditahan.headers)
            self.assertNotIn("penebak", room.members)
            akun["nama"] = "teman"
            self.assertEqual(client.post("/api/rooms/join", json={"code": room.code}).status_code, 200)


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
            # Catatan socket basi ikut dibuang, jadi tidak dicek ulang di setiap siaran.
            self.assertNotIn("bob-sid", server.sockets)
            sio.leave_room.reset_mock()
            rooms.join(room.code, "bob")
            server.sockets["bob-sid"] = {"username": "bob", "token": "revoked-session", "room": room.code}
            await server.emit_room("receive_chat", {"message": "next"}, to=room.code)
            sio.leave_room.assert_awaited_once_with("bob-sid", room.code)

    # connect selalu mengisi token, jadi catatan tanpa token tidak boleh lolos tanpa dicek.
    async def test_socket_record_without_token_is_not_trusted(self):
        rooms = RoomService()
        room = rooms.create("alice")
        sambungan = {"sid": {"username": "alice", "room": room.code}}
        with socket_palsu(rooms, sambungan), self.assertRaises(KeyError):
            await server.verifikasi_socket("sid", "alice")

    # Database sempat gagal bukan berarti sesinya berakhir: pemain tetap di kanal, tetapi siaran yang tokennya belum
    # bisa dicek tidak dikirim kepadanya (gagal tertutup).
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
            self.assertIn("sid", server.sockets)
        sio.leave_room.assert_not_awaited()
        sio.emit.assert_awaited_once_with(
            "receive_chat", {"message": "halo"}, to=room.code, skip_sid=["sid"]
        )

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
                isi_kursi_bot(rooms, room.code, "alice")
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
        isi_kursi_bot(rooms, room.code, "alice")
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
        isi_kursi_bot(rooms, room.code, "alice")
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

    # H4: chat dibatasi per pemain per room, jeda 2 detik dan 5 pesan per 20 detik. Pesan yang terlalu cepat tidak
    # disimpan atau disiarkan, dan pengirim menerima system_alert berisi lama tunggu.
    async def test_chat_terlalu_cepat_ditolak_dengan_pesan_jelas(self):
        from app.middleware import auth_limits
        from app.services import chat_service

        rooms = RoomService()
        room = rooms.create("alice")
        sambungan = {"sid": {"username": "alice", "token": "alice", "room": room.code}}
        jam = {"t": 1000.0}
        hasil = []
        with (
            socket_palsu(rooms, sambungan) as sio,
            patch("app.services.chat_service.PersistenceService") as persistence,
            patch.object(auth_limits, "monotonic", lambda: jam["t"]),
        ):
            for detik in (1000, 1000.5, 1003, 1006, 1009, 1012, 1015, 1020.5):
                jam["t"] = detik
                sio.emit.reset_mock()
                await chat.send_chat("sid", {"username": "alice", "message": f"pesan {detik}"})
                peristiwa = sio.emit.call_args.args
                hasil.append(peristiwa[1]["msg"] if peristiwa[0] == "system_alert" else "terkirim")
        self.assertEqual(hasil[0], "terkirim")
        self.assertEqual(hasil[1], "Chat terlalu cepat. Tunggu 2 detik lalu kirim lagi.")
        self.assertEqual(hasil[2:6], ["terkirim"] * 4)
        self.assertEqual(hasil[6], "Chat terlalu cepat. Tunggu 5 detik lalu kirim lagi.")
        self.assertEqual(hasil[7], "terkirim")
        self.assertEqual(persistence.return_value.record_player_message.call_count, 6)
        chat_service._jeda_chat.riwayat.clear()
        chat_service._jendela_chat.riwayat.clear()

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
            isi_kursi_bot(rooms, room.code, "alice")
            lobby = rooms.snapshot(room)
            self.assertEqual(
                [m["label"] for m in lobby["members"]], ["Alice Wonder", "Alice Wonder"]
            )
            rooms.start(room.code, "alice")
        labels = room.match.labels
        self.assertEqual(labels["alice"], "Alice Wonder (alice)")  # nama sama → diberi penanda
        self.assertEqual(labels["bob"], "Alice Wonder (bob)")
        self.assertEqual(labels["NOX"], "NOX")

"""Tahap 3A: ketahanan saat MySQL lambat atau mati, cek token socket, /ready, error database, dan sesi panel."""

import asyncio
import base64
import re
import threading
import time
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.exc import TimeoutError as PoolTimeoutError
from sqlalchemy.orm import Session

from app import main
from app.config import database
from app.config.settings import settings
from app.controllers.health import router as health_router
from app.middleware.auth import require_authenticated_user
from app.models import panel_queries
from app.services import panel_service
from app.services.password_service import hash_password
from app.services.room_service import RoomService
from app.sockets import chat, server
from tests.palsu.bot_lobby import isi_kursi_bot
from tests.palsu.socket_palsu import socket_palsu

MIGRASI = Path(__file__).resolve().parents[1] / "migrations"


# Error SQLAlchemy tiruan dengan kode PyMySQL di args[0], seperti yang dibungkus SQLAlchemy dari PyMySQL.
def error_mysql(kode):
    return OperationalError("SELECT", {}, Exception(kode, "uji"))


class KesehatanDatabaseTests(unittest.TestCase):
    def setUp(self):
        # Keadaan "MySQL gagal" berlaku untuk seluruh proses; kembalikan ke "menjawab" sesudah tiap tes.
        self.addCleanup(database._catat_kesehatan)

    def test_only_connection_errors_count_as_database_down(self):
        kasus = [
            (error_mysql(2003), True),  # gagal tersambung / connect_timeout
            (error_mysql(2013), True),  # koneksi putus / read_timeout
            (PoolTimeoutError("pool habis"), True),
            (error_mysql(1054), False),  # kolom belum ada: MySQL menjawab
            (error_mysql(1213), False),  # deadlock: MySQL menjawab
            (IntegrityError("INSERT", {}, Exception(1062, "uji")), False),
        ]
        for error, gagal in kasus:
            with self.subTest(error=repr(error)[:60]):
                self.assertEqual(database.error_koneksi(error), gagal)

    def test_failed_and_successful_transactions_update_health(self):
        with (
            patch("sqlalchemy.orm.Session.execute", side_effect=error_mysql(2013)),
            self.assertLogs("shadow_heist.database", "WARNING"),
            self.assertRaises(database.PersistenceError),
        ):
            database.jalankan_transaksi(lambda db: db.execute(text("SELECT 1")))
        self.assertTrue(database.database_gagal())
        with (
            patch("sqlalchemy.orm.Session.execute"),
            self.assertLogs("shadow_heist.database", "INFO"),
        ):
            database.jalankan_transaksi(lambda db: db.execute(text("SELECT 1")))
        self.assertFalse(database.database_gagal())

    @unittest.skipUnless(database.engine.dialect.name == "mysql", "butuh MySQL")
    def test_mysql_connections_have_timeouts(self):
        self.assertEqual(database.engine.pool.timeout(), 10)
        if not database.database_is_ready():
            self.skipTest("MySQL uji tidak tersedia")
        with database.engine.connect() as koneksi:
            mentah = koneksi.connection.dbapi_connection
            self.assertEqual(
                (mentah.connect_timeout, mentah._read_timeout, mentah._write_timeout), (5, 15, 15)
            )


class JedaJamTests(unittest.TestCase):
    # Selama jeda, sisa waktu fase dan jadwal persiapan tetap; pertandingan selesai tidak disentuh.
    def test_pause_shifts_running_matches_but_not_finished_ones(self):
        rooms = RoomService()
        room = rooms.create("alice")
        isi_kursi_bot(rooms, room.code, "alice")
        rooms.start(room.code, "alice")
        match = room.match
        match.preparation["ready_at"] = 100.0
        batas, persiapan = match.deadline, dict(match.preparation)
        rooms.jeda_jam_semua_room(30)
        self.assertEqual(match.deadline, batas + 30)
        self.assertEqual(match.preparation["min_until"], persiapan["min_until"] + 30)
        self.assertEqual(match.preparation["ready_at"], 130.0)
        match.begin()
        batas = match.deadline
        rooms.jeda_jam_semua_room(5)
        self.assertEqual(match.deadline, batas + 5)
        match.winner = "civilians"
        rooms.jeda_jam_semua_room(5)
        self.assertEqual(match.deadline, batas + 5)


class LifespanTests(unittest.IsolatedAsyncioTestCase):
    # Ganti semua yang disentuh lifespan: tanpa MySQL, otak, atau room sungguhan.
    def pasang(self, *, mysql_siap, mysql_gagal):
        rooms, npc, pemuat = Mock(), Mock(close=AsyncMock()), Mock()
        for tambalan in (
            patch.object(main, "database_is_ready", Mock(side_effect=mysql_siap)),
            patch.object(main, "database_gagal", Mock(return_value=mysql_gagal)),
            patch.object(main, "room_service", rooms),
            patch.object(main, "npc_service", npc),
            patch.object(main, "brain_runtime", Mock()),
            patch.object(main, "engine", Mock()),
            patch.dict(main.PEMUAT_KONFIGURASI, {"Konfigurasi AI": pemuat}, clear=True),
            patch.object(main, "JEDA_COBA_KONFIGURASI_DETIK", 0.05),
        ):
            tambalan.start()
            self.addCleanup(tambalan.stop)
        return rooms, npc, pemuat

    # MySQL mati: fase tidak berganti, bot tidak melangkah, dan batas waktu room digeser sejauh lama jeda.
    async def test_clock_pauses_rooms_while_database_is_down(self):
        rooms, npc, pemuat = self.pasang(mysql_siap=lambda: False, mysql_gagal=True)
        with self.assertLogs("shadow_heist", "ERROR"):
            async with main.lifespan(main.app):
                await asyncio.sleep(1.2)
        rooms.perbarui_fase_semua_room.assert_not_called()
        npc.jalankan_bot_yang_sudah_waktunya.assert_not_called()
        jeda = sum(panggilan.args[0] for panggilan in rooms.jeda_jam_semua_room.call_args_list)
        self.assertGreater(jeda, 0.4)
        pemuat.assert_not_called()

    # MySQL belum siap saat server nyala: startup tidak ditahan, konfigurasi panel dicoba ulang sampai termuat.
    async def test_panel_config_is_retried_in_background(self):
        jawaban = iter([False, False])
        rooms, npc, pemuat = self.pasang(mysql_siap=lambda: next(jawaban, True), mysql_gagal=False)
        mysql = {"gagal": False}
        main.database_gagal.side_effect = lambda: mysql["gagal"]

        # Percobaan pertama sesudah MySQL siap masih putus koneksi; yang kedua berhasil.
        def muat():
            mysql["gagal"] = pemuat.call_count == 1
            if mysql["gagal"]:
                raise database.PersistenceError("belum")

        pemuat.side_effect = muat
        with self.assertLogs("shadow_heist", "INFO") as log:
            async with main.lifespan(main.app):
                self.assertEqual(pemuat.call_count, 0)
                await asyncio.sleep(0.6)
        self.assertEqual(pemuat.call_count, 2)
        self.assertTrue(any("percobaan ke-4" in baris for baris in log.output))
        rooms.perbarui_fase_semua_room.assert_called()

    # Gagal yang bukan karena MySQL (mis. kunci enkripsi panel salah) tidak dicoba ulang terus: cukup memakai .env.
    async def test_panel_config_failure_with_database_up_is_not_retried(self):
        rooms, npc, pemuat = self.pasang(mysql_siap=lambda: True, mysql_gagal=False)
        pemuat.side_effect = database.PersistenceError("API key panel tidak dapat dibuka.")
        with self.assertLogs("shadow_heist", "WARNING"):
            async with main.lifespan(main.app):
                await asyncio.sleep(0.3)
        self.assertEqual(pemuat.call_count, 1)


class TokenSocketTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.rooms = RoomService()
        self.room = self.rooms.create("alice")

    # Token yang baru dicek tidak ditanyakan lagi; sesudah TOKEN_BERLAKU_DETIK dicek di thread, bukan di event loop.
    async def test_recent_check_is_reused_and_old_check_runs_in_thread(self):
        thread_cek = []

        def cek(token):
            thread_cek.append(threading.current_thread())
            return Mock(username=token)

        sambungan = {
            "sid": {
                "username": "alice",
                "token": "alice",
                "room": self.room.code,
                "dicek": time.monotonic(),
            }
        }
        with socket_palsu(self.rooms, sambungan, cek):
            await server.emit_room("receive_chat", {"n": 1}, to=self.room.code)
            self.assertEqual(thread_cek, [])
            server.sockets["sid"]["dicek"] -= server.TOKEN_BERLAKU_DETIK
            await server.emit_room("receive_chat", {"n": 2}, to=self.room.code)
            await server.emit_room("receive_chat", {"n": 3}, to=self.room.code)
        self.assertEqual(len(thread_cek), 1)
        self.assertIsNot(thread_cek[0], threading.current_thread())

    # Siaran kedua menunggu siaran pertama yang masih mengecek token, jadi urutan pesan di room tetap.
    async def test_broadcasts_in_one_room_keep_their_order(self):
        jumlah_cek = []

        def cek(token):
            jumlah_cek.append(token)
            if len(jumlah_cek) == 1:
                time.sleep(0.3)
            return Mock(username=token)

        sambungan = {"sid": {"username": "alice", "token": "alice", "room": self.room.code}}
        with socket_palsu(self.rooms, sambungan, cek) as sio:
            await asyncio.gather(
                server.emit_room("receive_chat", "A", to=self.room.code),
                server.emit_room("receive_chat", "B", to=self.room.code),
            )
        self.assertEqual([panggilan.args[1] for panggilan in sio.emit.call_args_list], ["A", "B"])
        self.assertEqual(len(jumlah_cek), 1)

    async def test_connect_checks_token_in_thread_and_records_check_time(self):
        thread_cek = []

        def cek(token):
            thread_cek.append(threading.current_thread())
            return Mock(username="alice")

        with socket_palsu(self.rooms, {}, cek):
            await chat.connect("sid", {}, {"token": "tok", "room_code": self.room.code})
            self.assertIn("dicek", server.sockets["sid"])
        self.assertIsNot(thread_cek[0], threading.current_thread())

    # Simpan pesan (dengan lock room) dan arsip jejak berjalan di thread; pesan tetap masuk pertandingan.
    async def test_chat_saves_message_and_trace_outside_event_loop(self):
        isi_kursi_bot(self.rooms, self.room.code, "alice")
        self.rooms.start(self.room.code, "alice")
        self.room.match.begin()
        thread = {}

        def catat(nama, hasil=None):
            def tercatat(*_args, **_kwargs):
                thread[nama] = threading.current_thread()
                return hasil

            return tercatat

        sambungan = {"sid": {"username": "alice", "token": "alice", "room": self.room.code}}
        with (
            socket_palsu(self.rooms, sambungan),
            patch("app.services.chat_service.PersistenceService") as persistence,
            patch("app.services.chat_service.catat_nlu", AsyncMock(return_value=None)),
        ):
            persistence.return_value.record_player_message.side_effect = catat("simpan", 7)
            persistence.return_value.record_trace.side_effect = catat("jejak")
            await chat.send_chat("sid", {"username": "alice", "message": "Halo"})
        self.assertEqual(self.room.match.messages[-1]["message"], "Halo")
        self.assertEqual(set(thread), {"simpan", "jejak"})
        self.assertTrue(all(t is not threading.current_thread() for t in thread.values()))


class ReadyTests(unittest.TestCase):
    def setUp(self):
        app = FastAPI()
        app.include_router(health_router)
        self.client = TestClient(app)

    # /ready gagal hanya karena database atau migrasi; model IndoBERT yang masih dimuat cukup dilaporkan.
    def test_ready_needs_required_migrations_but_not_the_model(self):
        kasus = [
            ([], "memuat", 200),
            (["V12__survey_formal"], "siap", 503),
            (None, "gagal", 503),
        ]
        for kurang, model, kode in kasus:
            status = {"siap": model == "siap", "gagal": model == "gagal"}
            with (
                self.subTest(kurang=kurang),
                patch.object(panel_service, "migrasi_kurang", return_value=kurang),
                patch("app.controllers.health.brain_runtime.ringkasan", return_value=status),
            ):
                hasil = self.client.get("/ready")
                self.assertEqual(hasil.status_code, kode)
                self.assertEqual(
                    hasil.json(),
                    {
                        "ready": kode == 200,
                        "database": kurang is not None,
                        "migrasi_kurang": kurang or [],
                        "indobert": model,
                    },
                )

    # Penjaga: migrasi terbaru di folder migrations harus ikut dicek /ready.
    def test_required_migrations_include_latest_file(self):
        versi = []
        for berkas in MIGRASI.glob("V*.sql"):
            versi += re.findall(
                r"schema_migrations\s*\(version\)\s*VALUES\s*\('(V(\d+)__\w+)'\)",
                berkas.read_text(encoding="utf-8"),
            )
        terbaru = max(versi, key=lambda item: int(item[1]))[0]
        self.assertIn(terbaru, panel_service.MIGRASI_WAJIB)

    def test_recorded_migrations_reads_only_given_versions(self):
        with Session(create_engine("sqlite://")) as db:
            db.execute(text("CREATE TABLE schema_migrations (version TEXT)"))
            db.execute(text("INSERT INTO schema_migrations VALUES ('V5__chat_history'), ('V9__x')"))
            self.assertEqual(
                panel_queries.recorded_migrations(db, panel_service.MIGRASI_WAJIB),
                {"V5__chat_history"},
            )


class ErrorDatabaseTests(unittest.TestCase):
    # Error database di create room (mis. profil akun) menjadi JSON dengan header CORS, bukan 500 tanpa CORS.
    def test_database_errors_from_room_endpoints_keep_cors_headers(self):
        asal = settings.allowed_origins[0]
        main.app.dependency_overrides[require_authenticated_user] = lambda: SimpleNamespace(
            username="alice"
        )
        self.addCleanup(main.app.dependency_overrides.pop, require_authenticated_user, None)
        client = TestClient(main.app)  # tanpa `with`: lifespan (MySQL, otak, jam) tidak dijalankan
        kasus = [
            (error_mysql(2003), 503, "Database sedang tidak tersedia."),
            (
                database.PersistenceError("Data game gagal disimpan."),
                503,
                "Data game gagal disimpan.",
            ),
            (IntegrityError("INSERT", {}, Exception(1062, "uji")), 500, "kesalahan database"),
        ]
        for error, kode, pesan in kasus:
            with (
                self.subTest(error=type(error).__name__),
                patch("app.controllers.rooms.room_service.buat_room_terarsip", side_effect=error),
                patch.object(main, "logger") as log,
            ):
                hasil = client.post("/api/rooms", json={}, headers={"Origin": asal})
                self.assertEqual(hasil.status_code, kode)
                self.assertEqual(hasil.headers.get("access-control-allow-origin"), asal)
                self.assertIn(pesan, hasil.json()["detail"])
                # Error SQL mentah dicatat di log; PersistenceError sudah dicatat jalankan_transaksi.
                self.assertEqual(log.error.called, not isinstance(error, database.PersistenceError))


class SesiPanelTests(unittest.TestCase):
    # Sesi kedaluwarsa dihapus di transaksi kedua; gagal membersihkan tidak menggagalkan login.
    def test_login_cleans_expired_sessions_in_own_transaction(self):
        operasi_dijalankan = []

        def transaksi(operasi):
            operasi_dijalankan.append(operasi)
            if operasi is panel_queries.delete_expired_panel_sessions:
                raise database.PersistenceError("deadlock")
            return operasi(Mock())

        hash_uji = base64.b64encode(hash_password("rahasia-uji").encode()).decode()
        with (
            patch.object(settings, "panel_password_hash", SecretStr(hash_uji)),
            patch.object(panel_service, "transaction", side_effect=transaksi),
            self.assertLogs("shadow_heist.panel", "WARNING"),
        ):
            token = panel_service.login(settings.panel_username, "rahasia-uji")
        self.assertTrue(token)
        self.assertEqual(len(operasi_dijalankan), 2)
        self.assertIs(operasi_dijalankan[1], panel_queries.delete_expired_panel_sessions)

    def test_create_session_only_inserts(self):
        db = Mock()
        panel_queries.create_panel_session(db, "a" * 64, datetime(2026, 11, 13), "b" * 64)
        self.assertEqual(db.execute.call_count, 1)
        self.assertTrue(str(db.execute.call_args.args[0]).lstrip().startswith("INSERT"))


class CheckerSalinanTests(unittest.TestCase):
    # Jejak live disalin di event loop (tempat penulisnya), bukan di thread endpoint.
    def test_live_traces_are_copied_on_event_loop(self):
        from app.controllers.panel import require_panel, router

        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[require_panel] = lambda: "token-uji"
        di_event_loop = []

        def salin(*_args, **_kwargs):
            try:
                asyncio.get_running_loop()
                di_event_loop.append(True)
            except RuntimeError:
                di_event_loop.append(False)
            return None

        checker = panel_service.checker_service
        client = TestClient(app)
        with (
            patch.object(checker, "list", side_effect=lambda *a, **k: salin() or []),
            patch.object(checker, "cari", side_effect=salin),
            patch.object(checker, "ringkasan_room", return_value={}),
        ):
            with patch.object(panel_service, "transaction", return_value=[]):
                self.assertEqual(client.get("/api/panel/checker/ABC123").status_code, 200)
            with patch.object(panel_service, "transaction", return_value=None):
                jalur = f"/api/panel/checker/ABC123/jejak/{'a' * 32}"
                self.assertEqual(client.get(jalur).status_code, 404)
        self.assertEqual(di_event_loop, [True, True])

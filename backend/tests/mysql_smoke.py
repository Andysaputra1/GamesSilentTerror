"""Integration test for a disposable database initialized from migrations.

Never point this test at a user's database: it writes test rows.
Set STRUCTURE_TEST_DB=1 explicitly to run.
"""

from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
import unittest
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import text

from app.main import app
from app.config.database import SessionLocal, jalankan_transaksi
from app.models import auth_queries, game_queries, panel_queries, survey_queries
from app.services.persistence_service import PersistenceError, PersistenceService
from app.services.survey_service import validate_question


# Hash acak berbentuk SHA-256, sesuai kolom token CHAR(64).
def _hash_acak():
    return hashlib.sha256(uuid4().bytes).hexdigest()


# Kode room unik per jalan tes, jadi hasil query tidak bercampur dengan data lama.
def _kode_room():
    return "S" + uuid4().hex[:11].upper()


# Waktu UTC tanpa zona, sesuai kolom DATETIME.
def _utc(**selisih):
    return datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(**selisih)


# Kolom JSON dibaca lewat SQL mentah bisa berupa teks atau sudah menjadi objek.
def _json(nilai):
    return json.loads(nilai) if isinstance(nilai, str) else nilai


@unittest.skipUnless(os.getenv("STRUCTURE_TEST_DB") == "1", "requires disposable MySQL")
class MySQLIntegration(unittest.TestCase):
    # TES INTEGRASI KHUSUS DB SEMENTARA: uji login, endpoint chat, query dan rollback pada MySQL; jangan jalankan pada data pengguna.
    def test_http_auth_and_game_queries(self):
        client = TestClient(app)
        self.assertEqual(client.get("/api/auth/me").status_code, 401)
        # Database migrasi tidak berisi akun: tes mendaftarkan akunnya sendiri.
        akun = "smoke_" + uuid4().hex[:8]
        sandi = "smoke-" + uuid4().hex[:10]
        daftar = {"username": akun, "password": sandi, "password_confirmation": sandi}
        self.assertEqual(client.post("/api/auth/register", json=daftar).status_code, 201)
        salah = {"username": akun, "password": "wrong"}
        self.assertEqual(client.post("/api/auth/login", json=salah).status_code, 401)
        login = client.post("/api/auth/login", json={"username": akun, "password": sandi})
        self.assertEqual(login.status_code, 200)
        headers = {"Authorization": "Bearer " + login.json()["access_token"]}
        self.assertEqual(client.get("/api/auth/me", headers=headers).json()["username"], akun)
        # Endpoint analisis lama (/api/analyze) sudah dihapus.
        self.assertEqual(client.post("/api/analyze", headers=headers, json={}).status_code, 404)
        username = "sql-test-" + uuid4().hex[:10]
        # Dua pesan dari pemain yang sama tidak boleh membuat baris pemain ganda.
        PersistenceService("local-lobby").record_player_message(
            username=username, message="pertama"
        )
        message_id = PersistenceService("local-lobby").record_player_message(
            username=username,
            message="'quoted'; --",
        )
        with SessionLocal() as db:
            self.assertEqual(
                db.execute(
                    text("SELECT COUNT(*) FROM players WHERE username=:name"), {"name": username}
                ).scalar_one(),
                1,
            )
            self.assertEqual(
                db.execute(
                    text("SELECT message FROM chat_messages WHERE id=:id"), {"id": message_id}
                ).scalar_one(),
                "'quoted'; --",
            )
        # An invalid write must also roll back the player inserted earlier in the same transaction.
        bad_name = "rollback-" + uuid4().hex[:10]
        with self.assertRaises(PersistenceError):
            PersistenceService("local-lobby").record_player_message(
                username=bad_name,
                message=None,  # kolom NOT NULL: gagal sesudah baris pemain ditulis
            )
        with SessionLocal() as db:
            self.assertEqual(
                db.execute(
                    text("SELECT COUNT(*) FROM players WHERE username=:name"), {"name": bad_name}
                ).scalar_one(),
                0,
            )
        self.assertEqual(client.post("/api/auth/logout", headers=headers).status_code, 204)
        self.assertEqual(client.get("/api/auth/me", headers=headers).status_code, 401)
        self.assertTrue(client.get("/app-status").json()["database_ready"])


# SQL yang pindah ke models lewat plan06 langkah 2: dijalankan di MySQL asli dengan data buatan tiap tes.
@unittest.skipUnless(os.getenv("STRUCTURE_TEST_DB") == "1", "requires disposable MySQL")
class MovedSqlIntegration(unittest.TestCase):
    def test_panel_sessions(self):
        token, versi = _hash_acak(), _hash_acak()

        def sesi(token_dicari, versi_dicari=versi):
            return jalankan_transaksi(
                lambda db: panel_queries.valid_panel_session(db, token_dicari, versi_dicari)
            )

        def buat_sesi(token_baru, **selisih):
            jalankan_transaksi(
                lambda db: panel_queries.create_panel_session(
                    db, token_baru, _utc(**selisih), versi
                )
            )

        buat_sesi(token, hours=1)
        self.assertEqual(sesi(token), token)
        self.assertIsNone(sesi(token, _hash_acak()))
        # Sesi kedaluwarsa tidak berlaku, lalu ikut dibersihkan saat sesi baru dibuat.
        kedaluwarsa = _hash_acak()
        buat_sesi(kedaluwarsa, hours=-1)
        self.assertIsNone(sesi(kedaluwarsa))
        buat_sesi(_hash_acak(), hours=1)
        with SessionLocal() as db:
            self.assertEqual(
                db.execute(
                    text("SELECT COUNT(*) FROM panel_sessions WHERE token_hash=:token"),
                    {"token": kedaluwarsa},
                ).scalar_one(),
                0,
            )
        jalankan_transaksi(lambda db: panel_queries.delete_panel_session(db, token))
        self.assertIsNone(sesi(token))

    def test_panel_configuration_with_for_update(self):
        # Baris 1 dan 2 milik aplikasi; id bertipe TINYINT.
        baris_uji = 99

        def baca(baris=baris_uji):
            return jalankan_transaksi(lambda db: panel_queries.panel_configuration(db, baris))

        awal, baru = {"penanda": uuid4().hex}, {"penanda": uuid4().hex}
        jalankan_transaksi(
            lambda db: panel_queries.write_panel_configuration(db, baris_uji, json.dumps(awal))
        )
        self.assertEqual(_json(baca()), awal)
        self.assertIsNone(baca(98))

        def baca_terkunci_lalu_tulis(db):
            terkunci = panel_queries.panel_configuration(db, baris_uji, for_update=True)
            panel_queries.write_panel_configuration(db, baris_uji, json.dumps(baru))
            return terkunci

        self.assertEqual(_json(jalankan_transaksi(baca_terkunci_lalu_tulis)), awal)
        self.assertEqual(_json(baca()), baru)

    def test_required_migrations(self):
        self.assertEqual(jalankan_transaksi(panel_queries.count_required_migrations), 2)

    # Satu room arsip berisi dua pesan: pemain dengan bacaan NLU, lalu bot.
    def _room_dua_pesan(self):
        kode, id_match = _kode_room(), uuid4().hex
        layanan = PersistenceService(kode)
        konteks = {"match_id": id_match, "round_number": 1, "phase": "day"}
        id_pemain = layanan.record_player_message(
            username="pemain_" + uuid4().hex[:8], message="pesan pemain", context=konteks
        )
        id_bot = layanan.record_bot_message(username="NOX", message="pesan bot", context=konteks)
        jalankan_transaksi(
            lambda db: game_queries.set_message_nlu(
                db, id_pemain, json.dumps({"intent": "offend", "target": []}, ensure_ascii=False)
            )
        )
        return kode, id_match, id_pemain, id_bot

    def test_lobby_room_and_archived_rooms(self):
        kode = _kode_room()

        def tambah(db):
            return game_queries.insert_lobby_room(db, kode)

        self.assertEqual(jalankan_transaksi(tambah), 1)
        # INSERT IGNORE: kode yang sudah ada tidak ditimpa dan hasilnya 0.
        self.assertEqual(jalankan_transaksi(tambah), 0)
        with SessionLocal() as db:
            id_room, fase = db.execute(
                text("SELECT id, phase FROM game_sessions WHERE room_code=:code"), {"code": kode}
            ).one()
        self.assertEqual(fase, "lobby")
        lainnya = _kode_room()
        self.assertTrue(PersistenceService(lainnya).archive_new_room("pemilik"))
        self.assertFalse(PersistenceService(lainnya).archive_new_room("pemilik"))

        kode_pesan, _, _, _ = self._room_dua_pesan()
        daftar = jalankan_transaksi(lambda db: panel_queries.archived_rooms(db, id_room - 1))
        per_kode = {baris["room_code"]: baris for baris in daftar}
        self.assertEqual(per_kode[kode]["id"], id_room)
        self.assertEqual(per_kode[kode]["message_count"], 0)
        self.assertEqual(per_kode[kode_pesan]["message_count"], 2)
        sesudah = jalankan_transaksi(lambda db: panel_queries.archived_rooms(db, id_room))
        self.assertNotIn(kode, {baris["room_code"] for baris in sesudah})

    def test_history_page_conditions_and_nlu(self):
        kode, id_match, id_pemain, id_bot = self._room_dua_pesan()

        def halaman(sender_kind="all", awal=None, akhir=None, **arah):
            syarat = panel_queries.history_conditions(kode, awal, akhir, sender_kind)
            return jalankan_transaksi(lambda db: panel_queries.history_page(db, *syarat, **arah))

        def id_dari(baris_baris):
            return [baris["id"] for baris in baris_baris]

        lama = {"terbaru_dulu": False, "after_id": 0, "before_id": None}
        baru = {"terbaru_dulu": True, "after_id": 0, "before_id": None}
        pertama = halaman(**lama)
        self.assertEqual(id_dari(pertama), [id_pemain, id_bot])
        self.assertEqual(id_dari(halaman(**{**lama, "after_id": id_pemain})), [id_bot])
        self.assertEqual(id_dari(halaman(**baru)), [id_bot, id_pemain])
        self.assertEqual(id_dari(halaman(**{**baru, "before_id": id_bot})), [id_pemain])
        self.assertEqual(id_dari(halaman("bot", **lama)), [id_bot])
        self.assertEqual(id_dari(halaman("human", **lama)), [id_pemain])
        self.assertEqual(
            id_dari(halaman(awal=_utc(hours=-1), akhir=_utc(hours=1), **lama)), [id_pemain, id_bot]
        )
        self.assertEqual(halaman(akhir=_utc(hours=-1), **lama), [])
        self.assertEqual(halaman(awal=_utc(hours=1), **lama), [])
        baris = pertama[0]
        self.assertEqual(
            (baris["sender_kind"], baris["message"], baris["room_code"]),
            ("human", "pesan pemain", kode),
        )
        self.assertEqual((baris["round_number"], baris["phase"]), (1, "day"))
        self.assertEqual(_json(baris["nlu"])["intent"], "offend")
        self.assertIsNone(pertama[1]["nlu"])

    def test_history_export_pages(self):
        kode, id_match, id_pemain, id_bot = self._room_dua_pesan()
        maksimum = jalankan_transaksi(panel_queries.max_message_id)
        self.assertGreaterEqual(maksimum, id_bot)
        syarat = panel_queries.history_conditions(kode, None, None)

        def halaman(**arah):
            return jalankan_transaksi(
                lambda db: panel_queries.history_export_page(db, *syarat, **arah)
            )

        naik = halaman(terbaru_dulu=False, batas=0, maximum=maksimum)
        self.assertEqual([baris[0] for baris in naik], [id_pemain, id_bot])
        # Urutan kolom dibaca panel_service saat menulis CSV.
        self.assertTrue(naik[0][1].startswith("pemain_"))
        self.assertEqual((naik[0][2], naik[0][3]), ("human", "pesan pemain"))
        self.assertEqual(_json(naik[0][4])["intent"], "offend")
        self.assertEqual((naik[0][5], naik[0][6]), (id_match, kode))
        self.assertIsNotNone(naik[0][7])
        turun = halaman(terbaru_dulu=True, batas=maksimum + 1, maximum=maksimum)
        self.assertEqual([baris[0] for baris in turun], [id_bot, id_pemain])
        lanjut = halaman(terbaru_dulu=False, batas=id_pemain, maximum=maksimum)
        self.assertEqual([baris[0] for baris in lanjut], [id_bot])
        # Pesan sesudah id maksimum saat ekspor dimulai tidak ikut.
        terbatas = halaman(terbaru_dulu=False, batas=0, maximum=id_pemain)
        self.assertEqual([baris[0] for baris in terbatas], [id_pemain])

    def test_checker_traces(self):
        kode = _kode_room()
        id_a, id_b = uuid4().hex, uuid4().hex

        def simpan(id_jejak, penanda):
            isi = {"id": id_jejak, "penanda": penanda, "penjelasan": {"bot": "NOX"}}
            jalankan_transaksi(
                lambda db: game_queries.save_checker_trace(db, id_jejak, kode, json.dumps(isi))
            )

        def jejak(id_jejak, room=kode):
            return jalankan_transaksi(lambda db: panel_queries.checker_trace(db, id_jejak, room))

        def halaman(sebelum):
            return jalankan_transaksi(
                lambda db: panel_queries.checker_trace_page(db, kode, sebelum)
            )

        simpan(id_a, "lama")
        simpan(id_b, "lain")
        # ON DUPLICATE KEY: id yang sama ditimpa, bukan menambah baris.
        simpan(id_a, "baru")
        lengkap = _json(jejak(id_a))
        self.assertEqual((lengkap["penanda"], lengkap["penjelasan"]), ("baru", {"bot": "NOX"}))
        self.assertIsNone(jejak(id_a, _kode_room()))
        self.assertIsNone(jejak(uuid4().hex))

        pertama = halaman(None)
        isi = [_json(baris["trace"]) for baris in pertama]
        self.assertEqual({jejak_isi["id"] for jejak_isi in isi}, {id_a, id_b})
        self.assertFalse(any("penjelasan" in jejak_isi for jejak_isi in isi))
        for baris, jejak_isi in zip(pertama, isi):
            self.assertTrue(baris["trace_cursor"].endswith("|" + jejak_isi["id"]))
        # Halaman lanjutan hanya berisi jejak sesudah cursor baris pertama.
        lanjut = halaman(pertama[0]["trace_cursor"])
        self.assertEqual([_json(baris["trace"])["id"] for baris in lanjut], [isi[1]["id"]])
        self.assertEqual(halaman(pertama[1]["trace_cursor"]), [])

    def test_latest_match_bots(self):
        kode, id_match = _kode_room(), uuid4().hex

        def catat(db):
            for nama in ("VEIL", "ECHO"):
                survey_queries.record_match_bot(
                    db,
                    {"match_id": id_match, "room_code": kode, "bot_name": nama,
                     "method": "fuzzy", "persona": "kalem", "role": "spy"},
                )  # fmt: skip

        jalankan_transaksi(catat)
        daftar = jalankan_transaksi(lambda db: survey_queries.latest_match_bots(db, kode))
        self.assertEqual({baris["bot_name"] for baris in daftar}, {"VEIL", "ECHO"})
        self.assertEqual(
            {
                (baris["match_id"], baris["method"], baris["persona"], baris["role"])
                for baris in daftar
            },
            {(id_match, "fuzzy", "kalem", "spy")},
        )
        self.assertEqual(
            list(jalankan_transaksi(lambda db: survey_queries.latest_match_bots(db, _kode_room()))),
            [],
        )

    def test_accounts_for_panel_and_removal(self):
        nama_lokal = "smoke_" + uuid4().hex[:10]
        nama_google = "smoke_" + uuid4().hex[:10]
        subjek = "subjek-" + uuid4().hex

        def buat_akun(db):
            id_lokal = auth_queries.create_account(
                db, username=nama_lokal, display_name="Akun Lokal", password_hash="hash-lama"
            )
            id_google = auth_queries.create_account(
                db, username=nama_google, display_name="Akun Google", password_hash="hash-google"
            )
            auth_queries.create_identity(db, id_google, nama_google + "@contoh.test", subjek)
            return id_lokal, id_google

        id_lokal, id_google = jalankan_transaksi(buat_akun)

        def akun_panel(id_akun):
            return jalankan_transaksi(lambda db: auth_queries.account_for_management(db, id_akun))

        def akun_login(nama):
            return jalankan_transaksi(lambda db: auth_queries.account_by_username(db, nama))

        # Profil beberapa akun sekaligus; nama yang tidak ada tidak ikut terbaca.
        profil = jalankan_transaksi(
            lambda db: {
                baris.username: (baris.skin_id, baris.display_name)
                for baris in auth_queries.account_profiles(
                    db, [nama_lokal, nama_google, "tidak_ada_" + uuid4().hex[:8]]
                )
            }
        )
        self.assertEqual(set(profil), {nama_lokal, nama_google})
        self.assertEqual(profil[nama_lokal][1], "Akun Lokal")
        self.assertTrue(profil[nama_lokal][0])

        self.assertEqual(akun_panel(id_lokal)["username"], nama_lokal)
        self.assertEqual(akun_panel(id_lokal)["login_method"], "password")
        self.assertEqual(akun_panel(id_google)["login_method"], "google")
        self.assertNotIn("password_hash", akun_panel(id_lokal))
        self.assertIsNone(akun_panel(0))

        halaman = jalankan_transaksi(
            lambda db: auth_queries.accounts_for_management(db, id_lokal - 1, nama_lokal)
        )
        self.assertEqual([baris["id"] for baris in halaman], [id_lokal])
        self.assertEqual(halaman[0]["login_method"], "password")
        self.assertEqual(
            list(
                jalankan_transaksi(
                    lambda db: auth_queries.accounts_for_management(db, id_lokal, nama_lokal)
                )
            ),
            [],
        )

        jalankan_transaksi(lambda db: auth_queries.update_password_hash(db, id_lokal, "hash-baru"))
        self.assertEqual(akun_login(nama_lokal)["password_hash"], "hash-baru")

        # Mencabut semua sesi satu akun tidak boleh menyentuh sesi akun lain.
        token_lokal, token_lain, token_google = _hash_acak(), _hash_acak(), _hash_acak()

        def buat_sesi(db):
            for id_akun, token in (
                (id_lokal, token_lokal), (id_lokal, token_lain), (id_google, token_google),
            ):  # fmt: skip
                auth_queries.create_session(
                    db, user_id=id_akun, token_hash=token, expires_at=_utc(hours=1)
                )

        def pemilik_token(token):
            return jalankan_transaksi(lambda db: auth_queries.account_by_token(db, token, _utc()))

        jalankan_transaksi(buat_sesi)
        self.assertEqual(pemilik_token(token_lokal)["id"], id_lokal)
        jalankan_transaksi(lambda db: auth_queries.delete_user_sessions(db, id_lokal))
        self.assertIsNone(pemilik_token(token_lokal))
        self.assertIsNone(pemilik_token(token_lain))
        self.assertEqual(pemilik_token(token_google)["id"], id_google)

        jalankan_transaksi(lambda db: auth_queries.delete_identity(db, id_google))
        self.assertIsNone(
            jalankan_transaksi(lambda db: auth_queries.account_by_google_subject(db, subjek))
        )
        self.assertEqual(akun_panel(id_google)["login_method"], "password")

        for id_akun, nama in ((id_lokal, nama_lokal), (id_google, nama_google)):
            jalankan_transaksi(lambda db: auth_queries.delete_user_sessions(db, id_akun))
            jalankan_transaksi(lambda db: auth_queries.delete_account(db, id_akun))
            self.assertIsNone(akun_panel(id_akun))
            self.assertIsNone(akun_login(nama))


# Survei di MySQL asli: pertanyaan hasil migrasi (termasuk V11) lolos validasi panel, susunan ulang
# ditulis lewat executemany, dan ekspor CSV mengikuti urutan pertanyaan. Data uji di-rollback.
@unittest.skipUnless(os.getenv("STRUCTURE_TEST_DB") == "1", "requires disposable MySQL")
class SurveySqlIntegration(unittest.TestCase):
    V11 = [
        "pengalaman_bermain",
        "saran_kesan_pesan",
        "kesenangan_bersama_bot",
        "harapan_bot_npc",
        "kesenangan_individu",
    ]

    def test_migrated_questions_pass_panel_validation_and_v11_is_last(self):
        semua = jalankan_transaksi(lambda db: survey_queries.list_questions(db, active_only=False))
        for pertanyaan in semua:
            hasil = validate_question(pertanyaan)
            for kolom in hasil:
                self.assertEqual(hasil[kolom], pertanyaan[kolom], (pertanyaan["code"], kolom))
        posisi = {pertanyaan["code"]: pertanyaan["position"] for pertanyaan in semua}
        self.assertEqual(sorted(self.V11, key=posisi.get), self.V11)
        lama = [nilai for kode, nilai in posisi.items() if kode not in self.V11]
        self.assertLess(max(lama), min(posisi[kode] for kode in self.V11))
        harapan = next(item for item in semua if item["code"] == "harapan_bot_npc")
        self.assertEqual(
            (harapan["kind"], harapan["required"], harapan["options"]),
            ("choice", False, ["Lebih cepat", "Lebih berempati", "Lainnya"]),
        )

    def test_reorder_and_export_follow_question_positions(self):
        with SessionLocal() as db:
            try:
                semua = survey_queries.list_questions(db, active_only=False)
                dibalik = [pertanyaan["id"] for pertanyaan in reversed(semua)]
                survey_queries.update_positions(
                    db,
                    [{"id": id_, "position": (i + 1) * 10} for i, id_ in enumerate(dibalik)],
                )
                urut = survey_queries.list_questions(db, active_only=False)
                self.assertEqual([pertanyaan["id"] for pertanyaan in urut], dibalik)
                # Satu kiriman, jawabannya disisipkan berlawanan dengan urutan pertanyaan.
                id_match, kode_room = uuid4().hex, _kode_room()
                for id_pertanyaan in (dibalik[1], dibalik[0]):
                    survey_queries.insert_answer(
                        db,
                        {"match_id": id_match, "room_code": kode_room, "username": "smoke_survei",
                         "question_id": id_pertanyaan, "question_snapshot": {"prompt": "uji"},
                         "value_number": None, "value_text": "Lainnya: uji urutan",
                         "role": "spy", "team": "civilians", "outcome": "won"},
                    )  # fmt: skip
                ekspor = [b for b in survey_queries.export_rows(db) if b["match_id"] == id_match]
                self.assertEqual([b["code"] for b in ekspor], [urut[0]["code"], urut[1]["code"]])
                self.assertEqual(ekspor[0]["value_text"], "Lainnya: uji urutan")
            finally:
                db.rollback()


if __name__ == "__main__":
    unittest.main()

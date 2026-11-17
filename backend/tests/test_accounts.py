"""Regresi register/Google: SQLite menguji SQL, transaksi, dan sesi tanpa akun nyata."""

import unittest
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from google.auth.exceptions import TransportError
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.controllers.auth import router
from app.middleware.auth_limits import batas_gagal_login, limit_auth_pemain
from app.config.settings import settings
from app.services.auth_service import hash_tiruan, nonces
from app.services.password_service import verify_password

# Diimpor sebelum setUp mem-patch SessionLocal: room_service menyalin nama itu saat pertama diimpor,
# jadi impor pertama di tengah patch mengikatnya selamanya ke engine tes yang sudah ditutup.
from app.services.room_service import room_service


# Batas percobaan disimpan di memori proses; tiap tes mulai dari kosong.
def kosongkan_batas():
    limit_auth_pemain.riwayat.clear()
    batas_gagal_login.riwayat.clear()


class AccountTests(unittest.TestCase):
    def setUp(self):
        kosongkan_batas()
        self.engine = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
        with self.engine.begin() as db:
            db.execute(
                text(
                    "CREATE TABLE user_accounts (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE, display_name TEXT, skin_id TEXT DEFAULT 'dexter', password_hash TEXT, is_active BOOLEAN DEFAULT 1)"
                )
            )
            db.execute(
                text(
                    "CREATE TABLE account_identities (user_id INTEGER PRIMARY KEY, email TEXT UNIQUE, google_subject TEXT UNIQUE, email_verified BOOLEAN)"
                )
            )
            db.execute(
                text(
                    "CREATE TABLE auth_sessions (user_id INTEGER, token_hash TEXT, expires_at DATETIME)"
                )
            )
            db.execute(text("CREATE TABLE match_participants (match_id TEXT, username TEXT)"))
            db.execute(text("CREATE TABLE survey_responses (match_id TEXT, username TEXT)"))
        self.session_patch = patch(
            "app.config.database.SessionLocal", sessionmaker(bind=self.engine)
        )
        self.session_patch.start()
        app = FastAPI()
        app.include_router(router)
        self.client = TestClient(app)
        self.origin = {"Origin": "http://localhost:4200"}
        self.body = {
            "username": "detective_test",
            "email": "test@example.com",
            "email_confirmation": "test@example.com",
            "password": "strong-test-password",
            "password_confirmation": "strong-test-password",
        }

    def tearDown(self):
        self.client.close()
        self.session_patch.stop()
        self.engine.dispose()
        kosongkan_batas()

    def register(self, **changes):
        return self.client.post("/api/auth/register", json={**self.body, **changes})

    # Nama baru bertahan melalui sesi baru; ID login dan profil akun lain tidak berubah.
    def test_profile_name_persists_without_changing_login_or_other_accounts(self):
        registered = self.register().json()
        headers = {"Authorization": "Bearer " + registered["access_token"]}
        other = self.register(
            username="other_player",
            email="other@example.com",
            email_confirmation="other@example.com",
        ).json()
        response = self.client.post(
            "/api/auth/me", headers=headers, json={"display_name": "  Andy Saputra  "}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertEqual(
            response.json(),
            {
                "username": self.body["username"],
                "display_name": "Andy Saputra",
                "skin_id": "dexter",
            },
        )
        self.assertEqual(
            self.client.get("/api/auth/me", headers=headers).json()["display_name"], "Andy Saputra"
        )
        self.assertEqual(
            self.client.get(
                "/api/auth/me", headers={"Authorization": "Bearer " + other["access_token"]}
            ).json()["display_name"],
            "other_player",
        )
        login = self.client.post(
            "/api/auth/login",
            json={"username": self.body["username"], "password": self.body["password"]},
        )
        self.assertEqual(login.status_code, 200)
        self.assertEqual(login.json()["user"]["display_name"], "Andy Saputra")

    # Endpoint harus menolak pengguna anonim, nama tidak valid, dan upaya mengganti identitas akun.
    def test_profile_update_requires_auth_and_valid_name(self):
        self.assertEqual(
            self.client.post("/api/auth/me", json={"display_name": "Name"}).status_code, 401
        )
        token = self.register().json()["access_token"]
        headers = {"Authorization": "Bearer " + token}
        # Nama yang dibaca keliru oleh NLU bot juga ditolak (M10): tanpa huruf/angka, atau diawali kata ganti/istilah.
        for name in ["", "   ", "x" * 101, "Bad\nName", "Bad\u202eName", 123, None,
                     "Aku", "gw", "Vote", "Hitman keren", "\U0001f525\U0001f525", "!!!"]:  # fmt: skip
            response = self.client.post(
                "/api/auth/me", headers=headers, json={"display_name": name}
            )
            self.assertEqual(response.status_code, 422)
        response = self.client.post(
            "/api/auth/me",
            headers=headers,
            json={"display_name": "Name", "user_id": 999},
        )
        self.assertEqual(response.status_code, 422)
        self.assertEqual(
            self.client.get("/api/auth/me", headers=headers).json()["display_name"],
            self.body["username"],
        )

    # Kegagalan penyimpanan tidak boleh mengklaim sukses atau mengubah profil lama.
    def test_profile_database_failure_preserves_old_name(self):
        from sqlalchemy.exc import SQLAlchemyError

        token = self.register().json()["access_token"]
        headers = {"Authorization": "Bearer " + token}
        with patch(
            "app.models.auth_queries.update_display_name", side_effect=SQLAlchemyError("test failure")
        ):
            response = self.client.post(
                "/api/auth/me", headers=headers, json={"display_name": "New Name"}
            )
        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            self.client.get("/api/auth/me", headers=headers).json()["display_name"],
            self.body["username"],
        )

    # H1: email dari form daftar tidak disimpan, jadi tidak bisa dipakai login dan tidak menghalangi pendaftar lain.
    def test_register_password_hash_ignores_unverified_email_and_duplicates(self):
        response = self.register()
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertTrue(response.json()["access_token"])
        with self.engine.connect() as db:
            row = db.execute(text("SELECT password_hash FROM user_accounts")).scalar()
            self.assertNotEqual(row, self.body["password"])
            self.assertTrue(row.startswith("pbkdf2_sha256"))
            self.assertEqual(db.execute(text("SELECT COUNT(*) FROM account_identities")).scalar(), 0)
        with self.engine.begin() as db:
            db.execute(text("UPDATE user_accounts SET skin_id = 'jenny'"))
        login = self.client.post(
            "/api/auth/login",
            json={"username": self.body["username"], "password": self.body["password"]},
        )
        self.assertEqual(login.status_code, 200)
        self.assertEqual(login.json()["user"]["skin_id"], "jenny")  # skin tersimpan, bukan bawaan
        lewat_email = self.client.post(
            "/api/auth/login",
            json={"username": "test@example.com", "password": self.body["password"]},
        )
        self.assertEqual(lewat_email.status_code, 401)
        self.assertEqual(self.register().status_code, 409)
        self.assertEqual(self.register(username="another").status_code, 201)
        with self.engine.connect() as db:
            self.assertEqual(db.execute(text("SELECT count(*) FROM user_accounts")).scalar(), 2)

    # H1: identitas lama dari form daftar (email belum terverifikasi) tidak bisa dipakai login lewat email, dan login
    # Google dengan email itu membuat akun Google baru sambil melepas email dari akun lama, tanpa 409.
    def test_legacy_unverified_email_neither_logs_in_nor_blocks_google(self):
        self.assertEqual(self.register().status_code, 201)
        with self.engine.begin() as db:
            db.execute(
                text("INSERT INTO account_identities VALUES (1, 'korban@example.com', NULL, 0)")
            )
        login = self.client.post(
            "/api/auth/login",
            json={"username": "korban@example.com", "password": self.body["password"]},
        )
        self.assertEqual(login.status_code, 401)
        google, _ = self.google(email="Korban@Example.com", subject="korban-sub")
        self.assertEqual(google.status_code, 200)
        self.assertTrue(google.json()["user"]["username"].startswith("google_"))
        with self.engine.connect() as db:
            identitas = db.execute(
                text("SELECT user_id, google_subject, email_verified FROM account_identities")
            ).all()
            self.assertEqual(len(identitas), 1)
            self.assertEqual(tuple(identitas[0])[1:], ("korban-sub", 1))
            self.assertEqual(db.execute(text("SELECT count(*) FROM user_accounts")).scalar(), 2)
        akun_lama = self.client.post(
            "/api/auth/login",
            json={"username": self.body["username"], "password": self.body["password"]},
        )
        self.assertEqual(akun_lama.status_code, 200)
        lagi, _ = self.google(email="korban@example.com", subject="korban-sub")
        self.assertEqual(lagi.json()["user"], google.json()["user"])

    # L1: akun yang tidak ada tetap menghitung hash (hash tiruan), jadi lama respons sama dengan akun yang ada.
    def test_login_unknown_account_still_hashes(self):
        with patch(
            "app.services.auth_service.verify_password", wraps=verify_password
        ) as verifikasi:
            for isian in ["tidak_ada_sama_sekali", "siapa@example.com"]:
                response = self.client.post(
                    "/api/auth/login", json={"username": isian, "password": "password-apa-saja"}
                )
                self.assertEqual(response.status_code, 401)
        self.assertEqual(verifikasi.call_count, 2)
        self.assertTrue(all(c.args[1] == hash_tiruan() for c in verifikasi.call_args_list))

    # M5: 10 password salah untuk satu akun menahan akun itu 15 menit (juga dengan password benar), tanpa
    # menahan akun lain.
    def test_wrong_password_limit_is_per_account(self):
        self.assertEqual(self.register().status_code, 201)
        self.assertEqual(self.register(username="teman_lab").status_code, 201)
        salah = {"username": self.body["username"], "password": "password-salah-123"}
        with patch(
            "app.services.auth_service.verify_password", side_effect=lambda p, h: p == "benar"
        ):
            for _ in range(10):
                self.assertEqual(self.client.post("/api/auth/login", json=salah).status_code, 401)
            ditahan = self.client.post(
                "/api/auth/login",
                json={"username": " " + self.body["username"].upper(), "password": "benar"},
            )
            self.assertEqual(ditahan.status_code, 429)
            self.assertIn("akun ini", ditahan.json()["detail"])
            self.assertLessEqual(int(ditahan.headers["retry-after"]), 15 * 60)
            teman = self.client.post(
                "/api/auth/login", json={"username": "teman_lab", "password": "benar"}
            )
            self.assertEqual(teman.status_code, 200)

    def test_validation_reserved_and_rate_limit(self):
        self.assertEqual(self.register(password_confirmation="different-password").status_code, 422)
        self.assertEqual(self.register(email_confirmation="other@example.com").status_code, 422)
        self.assertEqual(self.register(username="NOX").status_code, 409)
        self.assertEqual(self.register(username="sage").status_code, 409)  # nama NPC lain juga
        self.assertEqual(self.register(username="user1").status_code, 409)
        self.assertEqual(self.register(username="x<script>").status_code, 422)
        # Batas per IP untuk pemain 60 per menit: orang ke-16 di satu lab tidak lagi kena 429.
        kosongkan_batas()
        for _ in range(60):
            self.assertEqual(self.register(username="NOX").status_code, 409)
        self.assertEqual(self.register(username="NOX").status_code, 429)

    def test_google_disabled_and_wrong_origin(self):
        with patch.object(settings, "google_client_id", ""):
            self.assertEqual(
                self.client.post("/api/auth/google/challenge", headers=self.origin).status_code, 503
            )
        self.assertEqual(
            self.client.post(
                "/api/auth/google/challenge", headers={"Origin": "http://evil.invalid"}
            ).status_code,
            403,
        )

    def google(self, email="google@example.com", subject="google-subject", **changes):
        nonce = nonces.issue()
        claims = {
            "sub": subject,
            "email": email,
            "email_verified": True,
            "nonce": nonce,
            "name": "Google Detective",
            **changes,
        }
        with (
            patch.object(settings, "google_client_id", "test-client"),
            patch(
                "app.services.auth_service.id_token.verify_oauth2_token", return_value=claims
            ) as verify,
        ):
            response = self.client.post(
                "/api/auth/google",
                headers=self.origin,
                json={"credential": "test-token", "nonce": nonce},
            )
            self.assertEqual(verify.call_args.args[2], "test-client")
        return response, nonce

    def test_google_account_reuse_and_nonce_replay(self):
        first, nonce = self.google()
        self.assertEqual(first.status_code, 200)
        second, _ = self.google()
        self.assertEqual(first.json()["user"], second.json()["user"])
        with patch.object(settings, "google_client_id", "test-client"):
            replay = self.client.post(
                "/api/auth/google",
                headers=self.origin,
                json={"credential": "test-token", "nonce": nonce},
            )
        self.assertEqual(replay.status_code, 401)

    # Nama Google menjadi default; penyuntingan profil tidak ditimpa saat login Google ulang.
    def test_google_name_initializes_profile_and_preserves_user_edits(self):
        first, _ = self.google(name="Andy Saputra")
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json()["user"]["display_name"], "Andy Saputra")
        headers = {"Authorization": "Bearer " + first.json()["access_token"]}
        changed = self.client.post(
            "/api/auth/me", headers=headers, json={"display_name": "Andy Detective"}
        )
        self.assertEqual(changed.status_code, 200)
        second, _ = self.google(name="Andy Saputra")
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.json()["user"]["display_name"], "Andy Detective")
        self.assertEqual(second.json()["user"]["username"], first.json()["user"]["username"])

    def test_registration_with_name_and_no_email(self):
        body = {
            "username": "new_detective",
            "display_name": "Nama Pemain",
            "password": "test-password-123",
            "password_confirmation": "test-password-123",
        }
        response = self.client.post("/api/auth/register", json=body)
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["user"]["display_name"], "Nama Pemain")
        with self.engine.connect() as db:
            self.assertEqual(
                db.execute(text("SELECT COUNT(*) FROM account_identities")).scalar(), 0
            )
        self.assertEqual(
            self.client.post(
                "/api/auth/login", json={"username": body["username"], "password": body["password"]}
            ).status_code,
            200,
        )

    def test_username_change_conflicts_rooms_and_google_identity(self):
        first, _ = self.google(name="Google Name")
        original = first.json()["user"]["username"]
        headers = {"Authorization": "Bearer " + first.json()["access_token"]}
        room = room_service.create(original)
        try:
            blocked = self.client.post(
                "/api/auth/me",
                headers=headers,
                json={"username": "new_detective", "display_name": "New Name"},
            )
            self.assertEqual(blocked.status_code, 409)
        finally:
            room_service.leave(room.code, original)
        changed = self.client.post(
            "/api/auth/me",
            headers=headers,
            json={"username": "new_detective", "display_name": "New Name"},
        )
        self.assertEqual(changed.status_code, 200)
        again, _ = self.google()
        self.assertEqual(
            again.json()["user"],
            {"username": "new_detective", "display_name": "New Name", "skin_id": "dexter"},
        )
        self.register(username="taken_name")
        for name in ["taken_name", "NOX", "admin"]:
            self.assertEqual(
                self.client.post(
                    "/api/auth/me",
                    headers=headers,
                    json={"username": name, "display_name": "Should Roll Back"},
                ).status_code,
                409,
            )
        self.assertEqual(
            self.client.get("/api/auth/me", headers=headers).json(),
            {"username": "new_detective", "display_name": "New Name", "skin_id": "dexter"},
        )

    # Email yang sama tidak menautkan akun: daftar dengan email korban lalu Google korban = dua akun terpisah.
    def test_google_mismatched_nonce_unverified_and_no_email_linking(self):
        self.assertEqual(self.google(nonce="wrong")[0].status_code, 401)
        self.assertEqual(self.google(email_verified=False)[0].status_code, 401)
        registered = self.register()
        self.assertEqual(registered.status_code, 201)
        google, _ = self.google(email=self.body["email"])
        self.assertEqual(google.status_code, 200)
        self.assertNotEqual(google.json()["user"]["username"], registered.json()["user"]["username"])
        with self.engine.connect() as db:
            self.assertEqual(db.execute(text("SELECT count(*) FROM user_accounts")).scalar(), 2)

    # M5: nonce Google ditandatangani, jadi banjir /google/challenge tidak menggusur nonce lama; nonce palsu, yang
    # diubah, atau yang sudah dipakai ditolak.
    def test_google_nonce_flood_tamper_and_replay(self):
        nonce_awal = nonces.issue()
        for _ in range(2000):
            nonces.issue()
        self.assertTrue(nonces.consume(nonce_awal))
        self.assertFalse(nonces.consume(nonce_awal))
        palsu = nonces.issue()
        batas, acak, tanda = palsu.split(".")
        self.assertFalse(nonces.consume(f"{int(batas) + 999}.{acak}.{tanda}"))
        self.assertFalse(nonces.consume("x" * 40))
        self.assertFalse(nonces.consume("1.2.\u00e9"))
        self.assertTrue(nonces.consume(palsu))

    # L8 + M10: nama Google dengan karakter kontrol/bidi, tanpa huruf/angka, atau berupa kata ganti diganti
    # "Detective"; nama biasa hanya dirapikan.
    def test_google_display_name_is_sanitized(self):
        for subjek, nama, hasil in [
            ("s1", "Bad\u202eName", "Detective"),
            ("s2", "Aku", "Detective"),
            ("s3", "\U0001f525\U0001f525", "Detective"),
            ("s4", "  Andy Saputra  ", "Andy Saputra"),
        ]:
            with self.subTest(nama=nama):
                response, _ = self.google(email=subjek + "@example.com", subject=subjek, name=nama)
                self.assertEqual(response.json()["user"]["display_name"], hasil)

    # M10 + M3: nama tampilan dari form daftar (atau username bila nama kosong) ikut diperiksa; username yang masih
    # punya riwayat pertandingan atau survei tidak bisa didaftarkan atau dipakai saat ganti username.
    def test_register_display_name_and_username_history(self):
        self.assertEqual(self.register(display_name="Gw").status_code, 422)
        self.assertEqual(self.register(username="Vote").status_code, 422)
        with self.engine.begin() as db:
            db.execute(text("INSERT INTO match_participants VALUES ('m1', 'pemain_lama')"))
            db.execute(text("INSERT INTO survey_responses VALUES ('m2', 'pengisi_lama')"))
        for username in ["pemain_lama", "pengisi_lama"]:
            self.assertEqual(self.register(username=username).status_code, 409)
        token = self.register().json()["access_token"]
        ganti = self.client.post(
            "/api/auth/me",
            headers={"Authorization": "Bearer " + token},
            json={"username": "pemain_lama", "display_name": "Nama Baru"},
        )
        self.assertEqual(ganti.status_code, 409)
        with self.engine.connect() as db:
            self.assertEqual(db.execute(text("SELECT count(*) FROM user_accounts")).scalar(), 1)

    # Library melempar GoogleAuthError untuk issuer salah, dan TransportError adalah turunannya.
    def test_google_wrong_issuer_is_401_and_network_failure_stays_503(self):
        with patch.object(settings, "google_client_id", "test-client"):
            for hasil_cek, status in [
                ({"return_value": {"iss": "https://evil.invalid"}}, 401),
                ({"side_effect": TransportError("putus")}, 503),
            ]:
                with (
                    self.subTest(status=status),
                    patch("app.services.auth_service.id_token.verify_token", **hasil_cek),
                ):
                    response = self.client.post(
                        "/api/auth/google",
                        headers=self.origin,
                        json={"credential": "test-token", "nonce": nonces.issue()},
                    )
                    self.assertEqual(response.status_code, status)
        with self.engine.connect() as db:
            self.assertEqual(db.execute(text("SELECT count(*) FROM user_accounts")).scalar(), 0)

    def test_google_bad_signature_or_audience_rejected(self):
        nonce = nonces.issue()
        with (
            patch.object(settings, "google_client_id", "test-client"),
            patch(
                "app.services.auth_service.id_token.verify_oauth2_token",
                side_effect=ValueError("bad token"),
            ),
        ):
            response = self.client.post(
                "/api/auth/google",
                headers=self.origin,
                json={"credential": "forged-token", "nonce": nonce},
            )
        self.assertEqual(response.status_code, 401)

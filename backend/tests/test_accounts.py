"""Regresi register/Google: SQLite menguji SQL, transaksi, dan sesi tanpa akun nyata."""

import unittest
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from controller.api.auth import router
from controller.middleware.auth_limits import _attempts
from config.settings import settings
from services.google_identity_service import nonces


class AccountTests(unittest.TestCase):
    def setUp(self):
        _attempts.clear()
        self.engine = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
        with self.engine.begin() as db:
            db.execute(
                text(
                    "CREATE TABLE user_accounts (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE, display_name TEXT, password_hash TEXT, is_active BOOLEAN DEFAULT 1)"
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
        self.session_patch = patch(
            "services.auth_service.SessionLocal", sessionmaker(bind=self.engine)
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
        _attempts.clear()

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
            response.json(), {"username": self.body["username"], "display_name": "Andy Saputra"}
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
        for name in ["", "   ", "x" * 101, "Bad\nName", "Bad\u202eName", 123, None]:
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
            "models.auth_queries.update_display_name", side_effect=SQLAlchemyError("test failure")
        ):
            response = self.client.post(
                "/api/auth/me", headers=headers, json={"display_name": "New Name"}
            )
        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            self.client.get("/api/auth/me", headers=headers).json()["display_name"],
            self.body["username"],
        )

    def test_register_password_hash_email_login_and_duplicates(self):
        response = self.register()
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertTrue(response.json()["access_token"])
        with self.engine.connect() as db:
            row = db.execute(text("SELECT password_hash FROM user_accounts")).scalar()
            self.assertNotEqual(row, self.body["password"])
            self.assertTrue(row.startswith("pbkdf2_sha256"))
            self.assertEqual(
                db.execute(text("SELECT email_verified FROM account_identities")).scalar(), 0
            )
        login = self.client.post(
            "/api/auth/login",
            json={"username": "test@example.com", "password": self.body["password"]},
        )
        self.assertEqual(login.status_code, 200)
        self.assertEqual(self.register().status_code, 409)
        self.assertEqual(self.register(username="another").status_code, 409)
        with self.engine.connect() as db:
            self.assertEqual(db.execute(text("SELECT count(*) FROM user_accounts")).scalar(), 1)

    def test_validation_reserved_and_rate_limit(self):
        self.assertEqual(self.register(password_confirmation="different-password").status_code, 422)
        self.assertEqual(self.register(email_confirmation="other@example.com").status_code, 422)
        self.assertEqual(self.register(username="NOX").status_code, 409)
        self.assertEqual(self.register(username="user1").status_code, 409)
        self.assertEqual(self.register(username="x<script>").status_code, 422)
        for _ in range(16):
            response = self.register(username="NOX")
        self.assertEqual(response.status_code, 429)

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
                "services.google_identity_service.id_token.verify_oauth2_token", return_value=claims
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
        from services.room_service import room_service

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
            again.json()["user"], {"username": "new_detective", "display_name": "New Name"}
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
            {"username": "new_detective", "display_name": "New Name"},
        )

    def test_google_mismatched_nonce_unverified_and_no_email_linking(self):
        self.assertEqual(self.google(nonce="wrong")[0].status_code, 401)
        self.assertEqual(self.google(email_verified=False)[0].status_code, 401)
        self.assertEqual(self.register().status_code, 201)
        self.assertEqual(self.google(email=self.body["email"])[0].status_code, 409)
        with self.engine.connect() as db:
            self.assertEqual(db.execute(text("SELECT count(*) FROM user_accounts")).scalar(), 1)

    def test_google_bad_signature_or_audience_rejected(self):
        nonce = nonces.issue()
        with (
            patch.object(settings, "google_client_id", "test-client"),
            patch(
                "services.google_identity_service.id_token.verify_oauth2_token",
                side_effect=ValueError("bad token"),
            ),
        ):
            response = self.client.post(
                "/api/auth/google",
                headers=self.origin,
                json={"credential": "forged-token", "nonce": nonce},
            )
        self.assertEqual(response.status_code, 401)

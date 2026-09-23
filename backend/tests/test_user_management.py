"""Regresi admin akun: reset mencabut sesi, Google ditolak, dan arsip tidak ikut terhapus."""

import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from controller.api.users import router
from controller.api.panel import require_panel
from services.password_service import hash_password, verify_password
from services.room_service import room_service


class UserManagementTests(unittest.TestCase):
    # Pakai database terisolasi supaya penghapusan uji tidak menyentuh akun pengguna sebenarnya.
    def setUp(self):
        self.engine = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
        with self.engine.begin() as db:
            for statement in [
                "CREATE TABLE user_accounts (id INTEGER PRIMARY KEY, username TEXT UNIQUE, display_name TEXT, password_hash TEXT, is_active BOOLEAN DEFAULT 1)",
                "CREATE TABLE account_identities (user_id INTEGER, email TEXT, google_subject TEXT)",
                "CREATE TABLE auth_sessions (user_id INTEGER, token_hash TEXT)",
                "CREATE TABLE chat_messages (id INTEGER PRIMARY KEY, sender_name TEXT, message TEXT)",
                "CREATE TABLE ai_analyses (id INTEGER PRIMARY KEY, chat_message_id INTEGER, llm_response TEXT)",
                "CREATE TABLE checker_traces (id INTEGER PRIMARY KEY, trace TEXT)",
            ]:
                db.execute(text(statement))
            self.old_hash = hash_password("old-password-123")
            db.execute(
                text(
                    "INSERT INTO user_accounts VALUES (1,'alice','Alice',:hash,1), (2,'google_random','Google Name','google_only',1)"
                ),
                {"hash": self.old_hash},
            )
            db.execute(
                text(
                    "INSERT INTO account_identities VALUES (1,'alice@example.com',NULL), (2,'google@example.com','subject')"
                )
            )
            db.execute(
                text("INSERT INTO auth_sessions VALUES (1,'first'),(1,'second'),(2,'google-token')")
            )
            db.execute(text("INSERT INTO chat_messages VALUES (1,'alice','Pesan tetap disimpan')"))
            db.execute(text("INSERT INTO ai_analyses VALUES (1,1,'Analisis tetap disimpan')"))
            db.execute(text("INSERT INTO checker_traces VALUES (1,'trace tetap disimpan')"))
        self.session_patch = patch(
            "services.auth_service.SessionLocal", sessionmaker(bind=self.engine)
        )
        self.session_patch.start()
        self.app = FastAPI()
        self.app.include_router(router)
        self.client = TestClient(self.app)
        room_service.rooms.clear()

    # Tutup seluruh sumber daya dan kembalikan registry ruangan setelah setiap skenario.
    def tearDown(self):
        self.client.close()
        self.session_patch.stop()
        self.engine.dispose()
        room_service.rooms.clear()

    # Sesi admin tiruan hanya menggantikan dependency panel, bukan logika operasi akun.
    def admin(self):
        self.app.dependency_overrides[require_panel] = lambda: "admin-session"

    def test_requires_admin_for_listing_password_and_deletion(self):
        self.assertEqual(self.client.get("/api/panel/users").status_code, 401)
        self.assertEqual(
            self.client.post(
                "/api/panel/users",
                json={
                    "username": "new_user",
                    "display_name": "New User",
                    "password": "test-password-123",
                    "password_confirmation": "test-password-123",
                },
            ).status_code,
            401,
        )

        self.assertEqual(
            self.client.post(
                "/api/panel/users/1/password",
                json={"password": "new-password-123", "password_confirmation": "new-password-123"},
            ).status_code,
            401,
        )
        self.assertEqual(
            self.client.post(
                "/api/panel/users/1/delete", json={"confirm_username": "alice"}
            ).status_code,
            401,
        )

    def test_admin_creates_local_account_without_session_or_plaintext_password(self):
        self.admin()
        body = {
            "username": "new_user",
            "display_name": "New User",
            "password": "test-password-123",
            "password_confirmation": "test-password-123",
        }
        response = self.client.post("/api/panel/users", json=body)
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["login_method"], "password")
        self.assertNotIn("password", response.json())
        with self.engine.connect() as db:
            encoded = db.execute(
                text("SELECT password_hash FROM user_accounts WHERE username='new_user'")
            ).scalar()
            self.assertTrue(verify_password(body["password"], encoded))
            self.assertEqual(db.execute(text("SELECT COUNT(*) FROM auth_sessions")).scalar(), 3)
        self.assertEqual(self.client.post("/api/panel/users", json=body).status_code, 409)

    def test_lists_provider_and_filters_without_exposing_secrets(self):
        self.admin()
        response = self.client.get("/api/panel/users")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [u["login_method"] for u in response.json()["users"]], ["password", "google"]
        )
        for secret in [
            "password_hash",
            "token_hash",
            "google_subject",
            "alice@example.com",
            self.old_hash,
        ]:
            self.assertNotIn(secret, response.text)
        self.assertEqual(len(self.client.get("/api/panel/users?search=Alice").json()["users"]), 1)
        self.assertEqual(self.client.get("/api/panel/users?after_id=1").json()["users"][0]["id"], 2)

    def test_resets_local_password_and_revokes_only_target_sessions(self):
        self.admin()
        response = self.client.post(
            "/api/panel/users/1/password",
            json={"password": "new-password-123", "password_confirmation": "new-password-123"},
        )
        self.assertEqual(response.status_code, 204)
        with self.engine.connect() as db:
            encoded = db.execute(
                text("SELECT password_hash FROM user_accounts WHERE id=1")
            ).scalar()
            self.assertTrue(verify_password("new-password-123", encoded))
            self.assertFalse(verify_password("old-password-123", encoded))
            self.assertEqual(
                db.execute(text("SELECT COUNT(*) FROM auth_sessions WHERE user_id=1")).scalar(), 0
            )
            self.assertEqual(
                db.execute(text("SELECT COUNT(*) FROM auth_sessions WHERE user_id=2")).scalar(), 1
            )

    def test_google_password_and_mismatched_confirmation_are_rejected(self):
        self.admin()
        self.assertEqual(
            self.client.post(
                "/api/panel/users/2/password",
                json={"password": "new-password-123", "password_confirmation": "new-password-123"},
            ).status_code,
            409,
        )
        self.assertEqual(
            self.client.post(
                "/api/panel/users/1/password",
                json={
                    "password": "new-password-123",
                    "password_confirmation": "different-password",
                },
            ).status_code,
            422,
        )
        with self.engine.connect() as db:
            self.assertEqual(
                db.execute(text("SELECT password_hash FROM user_accounts WHERE id=1")).scalar(),
                self.old_hash,
            )
            self.assertEqual(db.execute(text("SELECT COUNT(*) FROM auth_sessions")).scalar(), 3)

    def test_deletes_only_account_and_sessions_not_archives(self):
        self.admin()
        self.assertEqual(
            self.client.post(
                "/api/panel/users/1/delete", json={"confirm_username": "wrong"}
            ).status_code,
            409,
        )
        response = self.client.post("/api/panel/users/1/delete", json={"confirm_username": "alice"})
        self.assertEqual(response.status_code, 204)
        with self.engine.connect() as db:
            self.assertEqual(
                db.execute(text("SELECT COUNT(*) FROM user_accounts WHERE id=1")).scalar(), 0
            )
            self.assertEqual(
                db.execute(
                    text("SELECT COUNT(*) FROM account_identities WHERE user_id=1")
                ).scalar(),
                0,
            )
            self.assertEqual(
                db.execute(text("SELECT COUNT(*) FROM auth_sessions WHERE user_id=1")).scalar(), 0
            )
            for table in ["chat_messages", "ai_analyses", "checker_traces"]:
                self.assertEqual(db.execute(text("SELECT COUNT(*) FROM " + table)).scalar(), 1)
            self.assertEqual(
                db.execute(text("SELECT COUNT(*) FROM user_accounts WHERE id=2")).scalar(), 1
            )
        self.assertEqual(
            self.client.post(
                "/api/panel/users/1/delete", json={"confirm_username": "alice"}
            ).status_code,
            404,
        )

    def test_cannot_delete_a_user_still_in_a_room(self):
        self.admin()
        room = room_service.create("alice")
        response = self.client.post("/api/panel/users/1/delete", json={"confirm_username": "alice"})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(room_service.get(room.code, "alice").owner, "alice")

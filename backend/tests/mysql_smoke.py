"""Integration test for a disposable database initialized from migrations.

Never point this test at a user's database: it writes test rows.
Set STRUCTURE_TEST_DB=1 explicitly to run.
"""

import os
import unittest
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import text

from app.main import app
from app.module.mysql_connector import SessionLocal
from app.module.persistence_service import PersistenceError, persistence_service


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
        persistence_service.ensure_player(username)
        persistence_service.ensure_player(username)
        persistence_service.update_player_status(username=username, status="gagged")
        message_id = persistence_service.record_player_message(
            username=username,
            message="'quoted'; --",
            status="active",
        )
        persistence_service.set_phase("tribunal")
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
            persistence_service.record_player_message(
                username=bad_name,
                message="bad",
                status="INVALID",
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


if __name__ == "__main__":
    unittest.main()

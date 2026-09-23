"""Integration test for a disposable database initialized from migrations.

Never point this test at a user's database: it writes test rows.
Set STRUCTURE_TEST_DB=1 explicitly to run.
"""

import os
import unittest
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import text

from main import app
from module.mysql_connector import SessionLocal
from services.analysis_service import AnalysisResult
from services.persistence_service import PersistenceError, persistence_service


@unittest.skipUnless(os.getenv("STRUCTURE_TEST_DB") == "1", "requires disposable MySQL")
class MySQLIntegration(unittest.TestCase):
    # TES INTEGRASI KHUSUS DB SEMENTARA: uji login, endpoint chat, query dan rollback pada MySQL; jangan jalankan pada data pengguna.
    def test_http_auth_and_game_queries(self):
        client = TestClient(app)
        self.assertEqual(client.get("/api/auth/me").status_code, 401)
        self.assertEqual(
            client.post(
                "/api/auth/login",
                json={
                    "username": "user1",
                    "password": "wrong",
                },
            ).status_code,
            401,
        )
        login = client.post(
            "/api/auth/login",
            json={
                "username": "user1",
                "password": "user132",
            },
        )
        self.assertEqual(login.status_code, 200)
        headers = {"Authorization": "Bearer " + login.json()["access_token"]}
        self.assertEqual(client.get("/api/auth/me", headers=headers).json()["username"], "user1")
        result = AnalysisResult("neutral", 10, 20.0, "AMAN", "Test NOX reply")
        # AI transport is unchanged; this test targets the moved controllers and real SQL.
        with patch("services.analysis_service.analysis_service.analyze", return_value=result):
            response = client.post(
                "/api/analyze",
                headers=headers,
                json={
                    "player_name": "spoofed",
                    "message": "integration test",
                    "silence_percentage": 20,
                },
            )
        self.assertEqual(response.status_code, 200, response.text)
        with SessionLocal() as db:
            row = db.execute(
                text("SELECT sender_name FROM chat_messages ORDER BY id DESC LIMIT 1")
            ).scalar_one()
            self.assertEqual(row, "user1")
            self.assertEqual(db.execute(text("SELECT COUNT(*) FROM ai_analyses")).scalar_one(), 1)
        username = "sql-test-" + uuid4().hex[:10]
        persistence_service.ensure_player(username)
        persistence_service.ensure_player(username)
        persistence_service.update_player_status(username=username, status="gagged")
        persistence_service.update_player_scores(
            username=username, aggressiveness=12, suspicion_score=22
        )
        persistence_service.record_player_message(
            username=username,
            message="'quoted'; --",
            intent="neutral",
            aggressiveness=12,
            suspicion_score=22,
            status="active",
            llm_response="Reply",
        )
        persistence_service.set_phase("tribunal")
        with SessionLocal() as db:
            self.assertEqual(
                db.execute(
                    text("SELECT COUNT(*) FROM players WHERE username=:name"), {"name": username}
                ).scalar_one(),
                1,
            )
        # An invalid write must also roll back the player inserted earlier in the same transaction.
        bad_name = "rollback-" + uuid4().hex[:10]
        with self.assertRaises(PersistenceError):
            persistence_service.record_player_message(
                username=bad_name,
                message="bad",
                intent=None,
                aggressiveness=10,
                suspicion_score=10,
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

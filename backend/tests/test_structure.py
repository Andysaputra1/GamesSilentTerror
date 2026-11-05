"""Run with: python -m unittest discover -s tests -v (from backend)."""

import ast
from datetime import datetime, timedelta
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.config.mysql import MySQLSettings
from app.models import auth_queries


# Nama yang diimpor sebuah berkas dari satu modul, di mana pun letak impornya di dalam berkas itu.
def _impor_dari(berkas, modul):
    pohon = ast.parse(berkas.read_text(encoding="utf-8"))
    return {
        alias.name
        for simpul in ast.walk(pohon)
        if isinstance(simpul, ast.ImportFrom) and simpul.module == modul
        for alias in simpul.names
    }


class LayerRuleTests(unittest.TestCase):
    APP = Path(__file__).resolve().parents[1] / "app"

    # SQL hanya di models; satu-satunya pengecualian SELECT 1 pemeriksa koneksi di config/database.py.
    def test_sql_text_only_in_models(self):
        for berkas in self.APP.rglob("*.py"):
            relatif = berkas.relative_to(self.APP).as_posix()
            if relatif.startswith("models/") or relatif == "config/database.py":
                continue
            with self.subTest(berkas=relatif):
                self.assertNotIn("text", _impor_dari(berkas, "sqlalchemy"))


class ConfigurationTests(unittest.TestCase):
    # TES CONFIG: periksa alias DB_*, encoding password URL, dan penolakan port di luar rentang.
    def test_db_aliases_and_port_validation(self):
        config = MySQLSettings(DB_HOST="db", DB_PORT=3307, DB_PASSWORD="a@b")
        self.assertEqual(config.mysql_host, "db")
        self.assertEqual(config.mysql_port, 3307)
        self.assertIn("a%40b", config.sqlalchemy_database_url)
        with self.assertRaises(ValueError):
            MySQLSettings(DB_PORT=70000)

    # Password DB tidak punya nilai bawaan di kode.
    def test_db_password_is_required(self):
        with patch.dict(os.environ, {}, clear=True), self.assertRaises(ValueError):
            MySQLSettings()


class AccountQueryTests(unittest.TestCase):
    # TES SQL SQLITE: periksa parameter terikat, pencarian akun, kedaluwarsa sesi, dan pencabutan token.
    def test_bound_parameters_session_expiry_and_revoke(self):
        engine = create_engine("sqlite://")
        with Session(engine) as db:
            db.execute(text("""CREATE TABLE user_accounts (
                id INTEGER PRIMARY KEY, username TEXT, display_name TEXT,
                password_hash TEXT, is_active INTEGER, skin_id TEXT DEFAULT 'dexter')"""))
            db.execute(text("""CREATE TABLE auth_sessions (
                user_id INTEGER, token_hash TEXT, expires_at DATETIME)"""))
            db.execute(
                text("INSERT INTO user_accounts VALUES (1, 'user1', 'User 1', 'hash', 1, 'jenny')")
            )
            self.assertIsNone(auth_queries.account_by_username(db, "' OR 1=1 --"))
            self.assertEqual(auth_queries.account_by_username(db, "user1")["id"], 1)
            self.assertEqual(auth_queries.account_by_username(db, "user1")["skin_id"], "jenny")
            now = datetime.now()
            auth_queries.create_session(
                db, user_id=1, token_hash="test", expires_at=now + timedelta(hours=1)
            )
            self.assertEqual(auth_queries.account_by_token(db, "test", now)["username"], "user1")
            self.assertIsNone(auth_queries.account_by_token(db, "test", now + timedelta(hours=2)))
            self.assertEqual(auth_queries.delete_session(db, "test"), 1)
            self.assertIsNone(auth_queries.account_by_token(db, "test", now))
            # Membuat sesi baru membersihkan sesi yang sudah kedaluwarsa.
            auth_queries.create_session(
                db, user_id=1, token_hash="lama", expires_at=datetime(2000, 1, 1)
            )
            auth_queries.create_session(
                db, user_id=1, token_hash="baru", expires_at=datetime(2999, 1, 1)
            )
            self.assertEqual(
                db.execute(text("SELECT token_hash FROM auth_sessions")).scalars().all(), ["baru"]
            )
        engine.dispose()


if __name__ == "__main__":
    unittest.main()

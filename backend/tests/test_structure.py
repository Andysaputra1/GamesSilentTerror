"""Run with: python -m unittest discover -s tests -v (from backend)."""

from datetime import datetime, timedelta
import unittest

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from config.mysql import MySQLSettings
from models import auth_queries


class ConfigurationTests(unittest.TestCase):
    # TES CONFIG: periksa alias DB_*, encoding password URL, dan penolakan port di luar rentang.
    def test_db_aliases_and_port_validation(self):
        config = MySQLSettings(DB_HOST="db", DB_PORT=3307, DB_PASSWORD="a@b")
        self.assertEqual(config.mysql_host, "db")
        self.assertEqual(config.mysql_port, 3307)
        self.assertIn("a%40b", config.sqlalchemy_database_url)
        with self.assertRaises(ValueError):
            MySQLSettings(DB_PORT=70000)


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
            self.assertEqual(auth_queries.account_for_token(db, "test", now)["username"], "user1")
            self.assertIsNone(auth_queries.account_for_token(db, "test", now + timedelta(hours=2)))
            self.assertEqual(auth_queries.delete_session(db, "test"), 1)
            self.assertIsNone(auth_queries.account_for_token(db, "test", now))
        engine.dispose()


if __name__ == "__main__":
    unittest.main()

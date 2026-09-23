"""Run with: python -m unittest discover -s tests -v (from backend)."""

from datetime import datetime, timedelta
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from fastapi import UploadFile
from starlette.datastructures import Headers
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from config.mysql import MySQLSettings
from config.upload import UploadPolicy
from models import auth_queries
from module.upload import UploadError, save_upload, save_uploads


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
                password_hash TEXT, is_active INTEGER)"""))
            db.execute(text("""CREATE TABLE auth_sessions (
                user_id INTEGER, token_hash TEXT, expires_at DATETIME)"""))
            db.execute(text("INSERT INTO user_accounts VALUES (1, 'user1', 'User 1', 'hash', 1)"))
            self.assertIsNone(auth_queries.account_by_username(db, "' OR 1=1 --"))
            self.assertEqual(auth_queries.account_by_username(db, "user1")["id"], 1)
            now = datetime.now()
            auth_queries.create_session(
                db, user_id=1, token_hash="test", expires_at=now + timedelta(hours=1)
            )
            self.assertEqual(auth_queries.account_for_token(db, "test", now)["username"], "user1")
            self.assertIsNone(auth_queries.account_for_token(db, "test", now + timedelta(hours=2)))
            self.assertEqual(auth_queries.delete_session(db, "test"), 1)
            self.assertIsNone(auth_queries.account_for_token(db, "test", now))
        engine.dispose()


class UploadTests(unittest.IsolatedAsyncioTestCase):
    # HELPER TES: buat UploadFile di memori dengan nama berbahaya untuk menguji keamanan penamaan.
    def file(self, data, mime="image/png"):
        return UploadFile(
            BytesIO(data), filename="../../escape.png", headers=Headers({"content-type": mime})
        )

    # TES ASYNC UPLOAD: pastikan nama hasil unik, isi/ukuran benar, dan file berada di folder sementara.
    async def test_safe_unique_names(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            policy = UploadPolicy("icons", 100)
            data = b"\x89PNG\r\n\x1a\n" + b"example"
            first = await save_upload(self.file(data), policy, root=root)
            second = await save_upload(self.file(data), policy, root=root)
            self.assertNotEqual(first.filename, second.filename)
            self.assertEqual((root / first.relative_path).read_bytes(), data)
            self.assertEqual(first.size, len(data))

    # TES ASYNC UPLOAD: tolak tipe/ukuran salah dan pastikan kegagalan batch membersihkan file yang dibuat.
    async def test_rejects_type_and_size_and_rolls_back_batch(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            policy = UploadPolicy("icons", 20, max_files=2)
            for data in (b"not an image", b"\x89PNG\r\n\x1a\n" + b"x" * 30):
                with self.assertRaises(UploadError):
                    await save_upload(self.file(data), policy, root=root)
            good = self.file(b"\x89PNG\r\n\x1a\n" + b"example")
            with self.assertRaises(UploadError):
                await save_uploads([good, self.file(b"invalid")], policy, root=root)
            self.assertEqual(list(root.rglob("*.png")), [])


if __name__ == "__main__":
    unittest.main()

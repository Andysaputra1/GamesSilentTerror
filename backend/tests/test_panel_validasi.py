import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.controller.api.panel import require_panel, router
from app.controller.api.users import router as users_router
from app.controller.controller_main import api_router
from app.controller.middleware.auth_limits import _riwayat_percobaan


class PanelSafetyTests(unittest.TestCase):
    def setUp(self):
        self.app = FastAPI()
        self.app.include_router(router)
        self.app.include_router(users_router)
        self.client = TestClient(self.app)

    def tearDown(self):
        self.client.close()

    def test_validation_does_not_echo_passwords(self):
        self.app.dependency_overrides[require_panel] = lambda: "admin-fixture"
        secret = "fixture-password-must-not-echo"
        result = self.client.post(
            "/api/panel/users",
            json={
                "username": "alice",
                "display_name": "Alice",
                "password": secret,
                "password_confirmation": "different-password",
            },
        )
        self.assertEqual(result.status_code, 422)
        self.assertNotIn(secret, result.text)
        self.assertNotIn("input", result.text)


class PasswordValidationResponseTests(unittest.TestCase):
    def setUp(self):
        _riwayat_percobaan.clear()
        app = FastAPI()
        # Router gabungan, supaya route_class tiap router teruji lewat susunan yang dipakai aplikasi.
        app.include_router(api_router)
        app.dependency_overrides[require_panel] = lambda: "admin-fixture"
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()

    def test_password_never_returned_and_detail_keeps_its_shape(self):
        sandi = "fixture-password-must-not-echo"
        akun = {"username": "alice_uji", "display_name": "Alice"}
        permintaan = {
            "login password terlalu panjang": (
                "/api/auth/login",
                {"username": "alice", "password": sandi * 10},
            ),
            "register password terlalu pendek": (
                "/api/auth/register",
                {**akun, "password": "pendek", "password_confirmation": "pendek"},
            ),
            "register konfirmasi berbeda": (
                "/api/auth/register",
                {**akun, "password": sandi, "password_confirmation": sandi + "-beda"},
            ),
            "panel login password terlalu panjang": (
                "/api/panel/login",
                {"username": "admin", "password": sandi * 10},
            ),
            "panel reset password konfirmasi berbeda": (
                "/api/panel/users/1/password",
                {"password": sandi, "password_confirmation": sandi + "-beda"},
            ),
        }
        for nama, (alamat, isi) in permintaan.items():
            with self.subTest(nama):
                hasil = self.client.post(alamat, json=isi)
                self.assertEqual(hasil.status_code, 422)
                self.assertNotIn(isi["password"], hasil.text)
                self.assertEqual(hasil.headers["cache-control"], "no-store")
                # Frontend dan panel membaca detail sebagai daftar; string lewat jalur HTTPException.
                detail = hasil.json()["detail"]
                self.assertIsInstance(detail, list)
                for galat in detail:
                    self.assertEqual(set(galat), {"loc", "msg", "type"})

import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.controller.api.panel import require_panel, router
from app.controller.api.users import router as users_router


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

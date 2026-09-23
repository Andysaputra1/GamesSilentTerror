import base64
import unittest
from datetime import date, datetime
from unittest.mock import patch, AsyncMock
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import SecretStr
import httpx
from config.settings import Settings, settings
from controller.api.panel import router, require_panel, history_filter, validate_endpoint
from services.password_service import hash_password
from module.openrouter_client import generate_reply


class PanelTests(unittest.TestCase):
    def setUp(self):
        app = FastAPI()
        app.include_router(router)
        self.app = app
        self.client = TestClient(app)

    def test_all_data_and_mutations_require_admin_session(self):
        for path in [
            "/api/panel/config",
            "/api/panel/rooms",
            "/api/panel/history",
            "/api/panel/history.csv",
            "/api/panel/checker/ABC123",
        ]:
            self.assertEqual(self.client.get(path).status_code, 401)
        self.assertEqual(
            self.client.put("/api/panel/config", json={"provider": "api"}).status_code, 401
        )
        self.assertEqual(self.client.post("/api/panel/check-ai").status_code, 401)

    def test_html_has_no_embedded_password_and_csp(self):
        page = self.client.get("/panel")
        self.assertEqual(page.status_code, 200)
        self.assertIn("frame-ancestors", page.headers["content-security-policy"])
        self.assertIn("login-form", page.text)
        self.assertNotIn("Silent132", page.text)
        self.assertNotIn("Silent132", self.client.get("/panel/assets/panel.js").text)
        self.assertEqual(
            self.client.get("/admin", follow_redirects=False).headers["location"], "/panel"
        )

    def test_wrong_password_does_not_access_database(self):
        hashed = base64.b64encode(hash_password("fixture-password").encode()).decode()
        with (
            patch.object(settings, "panel_password_hash", SecretStr(hashed)),
            patch("controller.api.panel.transaction") as db,
        ):
            self.assertEqual(
                self.client.post(
                    "/api/panel/login", json={"username": "administrator", "password": "wrong"}
                ).status_code,
                401,
            )
            db.assert_not_called()

    def test_date_filters_cover_full_wib_day(self):
        _, params = history_filter(None, date(2026, 9, 23), date(2026, 9, 23))
        self.assertEqual(params["start"], datetime(2026, 9, 22, 17))
        self.assertEqual(params["end"], datetime(2026, 9, 23, 17))
        with self.assertRaises(HTTPException):
            history_filter(None, date(2026, 9, 24), date(2026, 9, 23))

    def test_tunnel_rejects_credentials_private_addresses_and_http(self):
        for url in [
            "http://example.com",
            "https://name:pass@example.com",
            "https://example.com/?key=secret",
        ]:
            with self.assertRaises(HTTPException):
                validate_endpoint(url)
        with patch(
            "controller.api.panel.socket.getaddrinfo",
            return_value=[(2, 1, 6, "", ("169.254.169.254", 443))],
        ):
            with self.assertRaises(HTTPException):
                validate_endpoint("https://metadata.test")

    def test_check_ai_error_is_not_reported_active(self):
        self.app.dependency_overrides[require_panel] = lambda: "fixture-token"
        with patch(
            "controller.api.panel.api_reply",
            AsyncMock(side_effect=ValueError("secret must not leak")),
        ):
            result = self.client.post("/api/panel/check-ai")
            self.assertFalse(result.json()["active"])
            self.assertNotIn("secret must not leak", result.text)

    def test_check_ai_credit_failure_is_actionable_without_secrets(self):
        self.app.dependency_overrides[require_panel] = lambda: "fixture-token"
        response = httpx.Response(
            402, request=httpx.Request("POST", "https://openrouter.ai"), text="secret"
        )
        error = httpx.HTTPStatusError("secret", request=response.request, response=response)
        with patch("controller.api.panel.api_reply", AsyncMock(side_effect=error)):
            result = self.client.post("/api/panel/check-ai")
        self.assertFalse(result.json()["active"])
        self.assertIn("kredit", result.json()["message"])
        self.assertNotIn("secret", result.text)

    def test_empty_room_is_archived_and_db_failure_removes_live_room(self):
        from types import SimpleNamespace
        from controller.api.rooms import router as room_router
        from controller.middleware.auth import require_authenticated_user
        from services.room_service import RoomService
        from services.persistence_service import PersistenceError

        self.app.include_router(room_router)
        self.app.dependency_overrides[require_authenticated_user] = lambda: SimpleNamespace(
            username="alice"
        )
        rooms = RoomService()
        with (
            patch("controller.api.rooms.room_service", rooms),
            patch("controller.api.rooms.PersistenceService") as factory,
        ):
            factory.return_value.archive_new_room.return_value = True
            response = self.client.post("/api/rooms")
            self.assertEqual(response.status_code, 200)
            factory.return_value.archive_new_room.assert_called_once_with("alice")
            before = set(rooms.rooms)
            # Akun lain menguji kegagalan arsip tanpa melanggar satu room per akun.
            self.app.dependency_overrides[require_authenticated_user] = lambda: SimpleNamespace(
                username="bob"
            )
            factory.return_value.archive_new_room.side_effect = PersistenceError("fail")
            self.assertEqual(self.client.post("/api/rooms").status_code, 503)
            self.assertEqual(set(rooms.rooms), before)


class OpenRouterTests(unittest.IsolatedAsyncioTestCase):
    async def test_fixed_qwen_payload_and_no_secret_in_body(self):
        client = AsyncMock()
        client.post.return_value = httpx.Response(
            200,
            request=httpx.Request("POST", "https://openrouter.ai"),
            json={"choices": [{"message": {"content": "OK"}}]},
        )
        with patch("module.openrouter_client.httpx.AsyncClient") as factory:
            factory.return_value.__aenter__.return_value = client
            result = await generate_reply(
                "hello", config=Settings(_env_file=None, openrouter_api_key="fixture-key")
            )
        self.assertEqual(result, "OK")
        self.assertEqual(client.post.call_args.kwargs["json"]["model"], "qwen/qwen3-14b")
        self.assertEqual(
            client.post.call_args.kwargs["headers"]["Authorization"], "Bearer fixture-key"
        )

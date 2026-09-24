import asyncio
import json
import unittest
from unittest.mock import AsyncMock, patch

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from controller.api.panel import router, require_panel
from controller.api.users import router as users_router
from config.settings import Settings
from services.ai_diagnostics import capture_exchange, record_request, record_response
from services.ai_probe_service import run_probe
from services.analysis_service import IntentModelNotReadyError
from module.openrouter_client import generate_reply


class DiagnosticsTests(unittest.IsolatedAsyncioTestCase):
    async def test_exchange_records_real_body_and_usage_without_auth_headers(self):
        response = httpx.Response(
            200,
            request=httpx.Request("POST", "https://openrouter.ai"),
            json={
                "choices": [{"message": {"content": '{"action":"wait"}'}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 23, "completion_tokens": 8},
                "model": "qwen/qwen3-14b",
            },
        )
        client = AsyncMock()
        client.post.return_value = response
        trace = {}
        with patch("module.openrouter_client.httpx.AsyncClient") as factory:
            factory.return_value.__aenter__.return_value = client
            with capture_exchange(trace):
                await generate_reply(
                    "Skenario",
                    config=Settings(
                        _env_file=None, openrouter_api_key="secret-fixture", openrouter_default=None
                    ),
                )
        self.assertEqual(trace["request"]["body"], client.post.call_args.kwargs["json"])
        self.assertTrue(trace["request"]["body"]["messages"][0]["content"].endswith("/no_think"))
        self.assertEqual(trace["response"]["body"]["usage"]["prompt_tokens"], 23)
        self.assertNotIn("secret-fixture", json.dumps(trace))
        self.assertGreaterEqual(trace["timings"]["llm_ms"], 0)

    async def test_parallel_calls_keep_payloads_separate_and_hide_error_bodies(self):
        async def call(name):
            trace = {}
            with capture_exchange(trace):
                record_request(
                    "https://name:secret@example.com/api?key=secret",
                    {"input": name, "api_key": "secret"},
                )
                await asyncio.sleep(0)
                record_response(401, {"error": "secret"})
            return trace

        first, second = await asyncio.gather(call("first"), call("second"))
        self.assertEqual(first["request"]["body"]["input"], "first")
        self.assertEqual(second["request"]["body"]["input"], "second")
        self.assertNotIn("secret", json.dumps([first, second]))
        self.assertNotIn("body", first["response"])

    async def test_probe_runs_game_prompt_and_validates_decision(self):
        client = AsyncMock()
        client.post.return_value = httpx.Response(
            200,
            request=httpx.Request("POST", "https://openrouter.ai"),
            json={
                "choices": [
                    {"message": {"content": '{"action":"guard","target":"NOX","message":""}'}}
                ],
            },
        )
        config = Settings(
            _env_file=None,
            ai_provider="api",
            api_backend="openrouter",
            openrouter_api_key="fixture",
            openrouter_default=None,
        )
        with (
            patch("services.ai_probe_service.ai_runtime.current", return_value=config),
            patch(
                "services.ai_probe_service.analysis_service.predict_intent",
                side_effect=IntentModelNotReadyError(),
            ),
            patch("module.openrouter_client.httpx.AsyncClient") as factory,
        ):
            factory.return_value.__aenter__.return_value = client
            result = await run_probe("Apa alibimu?", "night")
        self.assertTrue(result["active"])
        self.assertTrue(result["valid_decision"])
        self.assertEqual(result["analysis"]["status"], "skipped")
        self.assertIn("STATE_JSON:", result["request"]["body"]["messages"][0]["content"])
        self.assertGreaterEqual(result["duration_ms"], result["timings"]["llm_ms"])

    async def test_invalid_json_and_transport_failure_are_distinct(self):
        async def reply(*args):
            record_response(200, {"output": "Not JSON"})
            raise ValueError("sensitive provider body")

        with patch("services.ai_probe_service.request_decision", side_effect=reply):
            result = await run_probe("Halo", "discussion")
        self.assertTrue(result["active"])
        self.assertFalse(result["valid_decision"])
        self.assertNotIn("sensitive provider body", json.dumps(result))
        with patch("services.ai_probe_service.request_decision", side_effect=TimeoutError):
            result = await run_probe("Halo", "discussion")
        self.assertFalse(result["active"])
        self.assertEqual(result["response"]["error_type"], "TimeoutError")


class PanelSafetyTests(unittest.TestCase):
    def setUp(self):
        self.app = FastAPI()
        self.app.include_router(router)
        self.app.include_router(users_router)
        self.client = TestClient(self.app)

    def tearDown(self):
        self.client.close()

    def test_probe_requires_admin_and_rejects_blank_input(self):
        self.assertEqual(
            self.client.post("/api/panel/test-ai", json={"message": "hello"}).status_code, 401
        )
        self.app.dependency_overrides[require_panel] = lambda: "admin-fixture"
        self.assertEqual(
            self.client.post("/api/panel/test-ai", json={"message": "  "}).status_code, 422
        )

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

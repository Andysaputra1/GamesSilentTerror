import json
import unittest
from unittest.mock import AsyncMock, Mock, patch
from cryptography.fernet import Fernet
from pydantic import SecretStr
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.config.settings import settings
from app.module.ai_runtime_service import (
    ai_runtime,
    save_panel_configuration,
    load_panel_configuration,
)
from app.module.persistence_service import PersistenceError
from app.controller.api.panel import router, require_panel


class PanelSecretsTests(unittest.TestCase):
    def setUp(self):
        self.stored = None
        self.db = Mock()

        def execute(sql, params=None):
            if str(sql).lstrip().startswith("SELECT"):
                return Mock(scalar=lambda: self.stored)
            self.stored = params["config"]
            return Mock()

        self.db.execute.side_effect = execute
        self.run = patch(
            "app.module.persistence_service.PersistenceService._run",
            side_effect=lambda fn: fn(self.db),
        )
        self.run.start()
        self.key = patch.object(
            settings, "panel_encryption_key", SecretStr(Fernet.generate_key().decode())
        )
        self.key.start()
        ai_runtime.reset()
        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[require_panel] = lambda: "test-token"
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        self.run.stop()
        self.key.stop()
        ai_runtime.reset()

    def test_save_encrypt_restart_blank_and_replace_without_echo(self):
        result = self.client.put(
            "/api/panel/config", json={"provider": "api", "api_key": "fixture-private-key"}
        )
        self.assertEqual(result.status_code, 200)
        self.assertNotIn("fixture-private-key", result.text)
        self.assertNotIn("fixture-private-key", self.stored)
        self.assertIn("openrouter_key_encrypted", json.loads(self.stored))
        ai_runtime.reset()
        load_panel_configuration()
        self.assertEqual(
            ai_runtime.current().openrouter_api_key.get_secret_value(), "fixture-private-key"
        )
        self.assertNotIn("fixture-private-key", self.client.get("/api/panel/config").text)
        self.client.put("/api/panel/config", json={"provider": "api", "api_key": "  "})
        ai_runtime.reset()
        load_panel_configuration()
        self.assertEqual(
            ai_runtime.current().openrouter_api_key.get_secret_value(), "fixture-private-key"
        )
        save_panel_configuration("docker", "https://example.com")
        self.assertEqual(
            ai_runtime.current().openrouter_api_key.get_secret_value(), "fixture-private-key"
        )
        save_panel_configuration("api", "https://example.com", "replacement-key")
        self.assertEqual(
            ai_runtime.current().openrouter_api_key.get_secret_value(), "replacement-key"
        )
        self.assertNotIn("replacement-key", self.stored)

    # TOKEN TUNNEL: disimpan terenkripsi dari panel, bertahan saat dikosongkan, dihapus → kembali ke .env.
    def test_tunnel_token_from_panel_is_encrypted_kept_and_clearable(self):
        with patch.object(settings, "ollama_tunnel_token", SecretStr("env-token")):
            body = {"provider": "docker", "endpoint": "https://example.com"}
            with patch("app.controller.api.panel.validate_endpoint", side_effect=lambda e: e):
                self.assertEqual(self.client.get("/api/panel/config").json()["token_source"], "env")
                result = self.client.put(
                    "/api/panel/config", json={**body, "tunnel_token": "panel-token-123"}
                )
                self.assertEqual(result.json()["token_source"], "panel")
                self.assertNotIn("panel-token-123", result.text + self.stored)
                ai_runtime.reset()
                load_panel_configuration()
                token = ai_runtime.current().ollama_tunnel_token.get_secret_value()
                self.assertEqual(token, "panel-token-123")
                self.client.put("/api/panel/config", json={**body, "tunnel_token": "  "})
                token = ai_runtime.current().ollama_tunnel_token.get_secret_value()
                self.assertEqual(token, "panel-token-123")  # kosong: token lama dipertahankan
                bad = self.client.put("/api/panel/config", json={**body, "tunnel_token": "a b"})
                self.assertEqual(bad.status_code, 400)
                result = self.client.put(
                    "/api/panel/config", json={**body, "clear_tunnel_token": True}
                )
                self.assertEqual(result.json()["token_source"], "env")
                token = ai_runtime.current().ollama_tunnel_token.get_secret_value()
                self.assertEqual(token, "env-token")

    # MODEL LOKAL: dipilih di panel (4B/14B), dipertahankan bila kosong, dan dipakai tes koneksi.
    def test_local_model_is_selectable_kept_and_used_by_check(self):
        body = {"provider": "docker", "endpoint": "https://example.com"}
        with patch("app.controller.api.panel.validate_endpoint", side_effect=lambda e: e):
            view = self.client.put("/api/panel/config", json=body).json()
            self.assertEqual(view["local_model"], "qwen3:14b")  # bawaan pertama kali
            self.assertIn("qwen3:4b-instruct", view["local_models"])
            view = self.client.put(
                "/api/panel/config", json={**body, "model": "qwen3:4b-instruct"}
            ).json()
            self.assertEqual((view["local_model"], view["model"]), ("qwen3:4b-instruct",) * 2)
            self.client.put("/api/panel/config", json=body)  # tanpa model: pilihan lama tetap
            ai_runtime.reset()
            load_panel_configuration()
            self.assertEqual(ai_runtime.current().ollama_model, "qwen3:4b-instruct")
            bad = self.client.put("/api/panel/config", json={**body, "model": "qwen3 4b; rm"})
            self.assertEqual(bad.status_code, 400)
            reply = AsyncMock(return_value="OK")
            with patch("app.controller.api.panel.local_reply", reply):
                self.assertTrue(self.client.post("/api/panel/check-ai").json()["active"])
            self.assertEqual(reply.call_args.kwargs["config"].ollama_model, "qwen3:4b-instruct")

    def test_missing_encryption_key_cannot_save_plaintext(self):
        with patch.object(settings, "panel_encryption_key", None):
            with self.assertRaises(PersistenceError):
                save_panel_configuration("api", "https://example.com", "fixture-private-key")
        self.assertIsNone(self.stored)
        self.assertIsNone(ai_runtime.override)

    def test_wrong_key_cannot_decrypt(self):
        save_panel_configuration("api", "https://example.com", "fixture-private-key")
        ai_runtime.reset()
        with patch.object(
            settings, "panel_encryption_key", SecretStr(Fernet.generate_key().decode())
        ):
            with self.assertRaises(PersistenceError):
                load_panel_configuration()
        self.assertIsNone(ai_runtime.override)

    def test_invalid_key_validation_does_not_echo_secret(self):
        response = self.client.put(
            "/api/panel/config", json={"provider": "api", "api_key": "private key with whitespace"}
        )
        self.assertEqual(response.status_code, 400)
        self.assertNotIn("private key with whitespace", response.text)

    def test_default_and_custom_switch_preserves_secret_across_restart(self):
        with patch.object(settings, "openrouter_default", SecretStr("server-default-fixture")):
            response = self.client.put(
                "/api/panel/config", json={"provider": "api", "key_source": "default"}
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["key_source"], "default")
            self.assertEqual(
                ai_runtime.current().openrouter_api_key_value, "server-default-fixture"
            )
            self.assertNotIn("server-default-fixture", response.text)
            self.assertNotIn("server-default-fixture", self.stored)
            response = self.client.put(
                "/api/panel/config",
                json={"provider": "api", "key_source": "custom", "api_key": "custom-fixture"},
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(ai_runtime.current().openrouter_api_key_value, "custom-fixture")
            self.client.put("/api/panel/config", json={"provider": "api", "key_source": "default"})
            ai_runtime.reset()
            load_panel_configuration()
            self.assertEqual(
                ai_runtime.current().openrouter_api_key_value, "server-default-fixture"
            )
            self.assertTrue(self.client.get("/api/panel/config").json()["custom_configured"])
            self.client.put("/api/panel/config", json={"provider": "api", "key_source": "custom"})
            ai_runtime.reset()
            load_panel_configuration()
            self.assertEqual(ai_runtime.current().openrouter_api_key_value, "custom-fixture")
            self.assertNotIn("custom-fixture", self.stored)

    def test_empty_custom_does_not_fall_back_to_default(self):
        with patch.object(settings, "openrouter_default", SecretStr("server-default-fixture")):
            response = self.client.put(
                "/api/panel/config", json={"provider": "api", "key_source": "custom"}
            )
            self.assertEqual(response.status_code, 400)
            self.assertIsNone(self.stored)

    def test_lowercase_environment_alias(self):
        from app.config.settings import Settings

        with patch.dict("os.environ", {"openrouter_default": "alias-fixture"}):
            config = Settings(_env_file=None)
            self.assertEqual(config.openrouter_api_key_value, "alias-fixture")

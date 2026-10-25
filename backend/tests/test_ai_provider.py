"""Settings provider/model dan payload adapter Ollama, tanpa akses jaringan."""

import unittest
from unittest.mock import AsyncMock, patch
import httpx
from app.config.settings import Settings
from app.services import ollama_client


class ProviderTests(unittest.IsolatedAsyncioTestCase):
    # TES ASYNC ADAPTER: periksa payload model/non-streaming dan pengambilan teks dengan HTTP mock.
    async def test_ollama_payload_and_response(self):
        request = httpx.Request("POST", "http://ollama:11434/api/chat")
        mock_client = AsyncMock()
        mock_client.post.return_value = httpx.Response(
            200, request=request, json={"message": {"content": " Reply "}}
        )
        with (
            patch("app.services.ollama_client.settings", Settings(_env_file=None, OLLAMA_MODEL="8")),
            patch("app.services.ollama_client.httpx.AsyncClient") as factory,
        ):
            factory.return_value.__aenter__.return_value = mock_client
            self.assertEqual(await ollama_client.generate_reply("hello"), "Reply")
            body = mock_client.post.call_args.kwargs["json"]
            self.assertFalse(body["stream"])
            self.assertFalse(body["think"])
            self.assertEqual(body["model"], "qwen3:8b")

    # TES VALIDASI: tolak provider selain api atau docker.
    def test_invalid_provider_rejected(self):
        with self.assertRaises(ValueError):
            Settings(_env_file=None, ai_provider="invalid")

    # TES VALIDASI: petakan pilihan 4/8/14 ke model yang tepat dan tolak ukuran lain.
    def test_model_size_selection(self):
        for value, expected in [
            (8, "qwen3:8b"),
            ("14", "qwen3:14b"),
            ("qwen3:8b", "qwen3:8b"),
            ("4", "qwen3:4b-instruct"),
        ]:
            with self.subTest(value=value):
                config = Settings(_env_file=None, ollama_model=value)
                self.assertEqual(config.ollama_model, expected)
        with self.assertRaises(ValueError):
            Settings(_env_file=None, ollama_model="7")

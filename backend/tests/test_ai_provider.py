"""Provider selection and Ollama payload/error handling, without network access."""

import unittest
from unittest.mock import AsyncMock, patch
import httpx
from config.settings import Settings
from module import ollama_client
from services.analysis_service import AnalysisService


class ProviderTests(unittest.IsolatedAsyncioTestCase):
    # HELPER TES ASYNC: panggil jalur respons dengan input tetap; provider dimock oleh masing-masing skenario.
    async def reply(self):
        return await AnalysisService().create_host_response(
            player_name="user1",
            message="Halo",
            intent="neutral",
            aggressiveness=10,
            suspicion_score=20,
            suspicion_status="AMAN",
        )

    # TES ASYNC: mode Docker hanya memakai Ollama dan tidak memanggil klien cloud.
    async def test_docker_never_calls_openai(self):
        with (
            patch(
                "services.analysis_service.settings", Settings(_env_file=None, ai_provider="docker")
            ),
            patch(
                "services.analysis_service.generate_reply",
                AsyncMock(return_value="Halo dari lokal."),
            ),
            patch("services.analysis_service.AsyncOpenAI") as cloud,
        ):
            self.assertEqual(await self.reply(), "Halo dari lokal.")
            cloud.assert_not_called()

    # TES ASYNC: mode API memakai klien OpenAI mock dan tidak memanggil Ollama.
    async def test_api_never_calls_ollama(self):
        with (
            patch(
                "services.analysis_service.settings",
                Settings(
                    _env_file=None, ai_provider="api", api_backend="openai", OPENAI_API_KEY="test"
                ),
            ),
            patch("services.analysis_service.generate_reply", AsyncMock()) as local,
            patch("services.analysis_service.AsyncOpenAI") as cloud,
        ):
            cloud.return_value.responses.create = AsyncMock(
                return_value=type("Response", (), {"output_text": "API reply"})()
            )
            cloud.return_value.close = AsyncMock()
            self.assertEqual(await self.reply(), "API reply")
            local.assert_not_called()

    # TES ASYNC: timeout Ollama menghasilkan pesan kegagalan tanpa beralih ke cloud berbayar.
    async def test_docker_timeout_is_visible_without_cloud_fallback(self):
        with (
            patch(
                "services.analysis_service.settings", Settings(_env_file=None, ai_provider="docker")
            ),
            patch(
                "services.analysis_service.generate_reply",
                AsyncMock(side_effect=httpx.ReadTimeout("test")),
            ),
            patch("services.analysis_service.AsyncOpenAI") as cloud,
        ):
            self.assertIn("Ollama", await self.reply())
            cloud.assert_not_called()

    # TES ASYNC ADAPTER: periksa payload model/non-streaming dan pengambilan teks dengan HTTP mock.
    async def test_ollama_payload_and_response(self):
        request = httpx.Request("POST", "http://ollama:11434/api/chat")
        mock_client = AsyncMock()
        mock_client.post.return_value = httpx.Response(
            200, request=request, json={"message": {"content": " Reply "}}
        )
        with (
            patch("module.ollama_client.settings", Settings(_env_file=None, OLLAMA_MODEL="8")),
            patch("module.ollama_client.httpx.AsyncClient") as factory,
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

    # TES VALIDASI: petakan pilihan 8/14 ke model yang tepat dan tolak ukuran lain.
    def test_model_size_selection(self):
        for value, expected in [(8, "qwen3:8b"), ("14", "qwen3:14b"), ("qwen3:8b", "qwen3:8b")]:
            with self.subTest(value=value):
                config = Settings(_env_file=None, ollama_model=value)
                self.assertEqual(config.ollama_model, expected)
        with self.assertRaises(ValueError):
            Settings(_env_file=None, ollama_model="7")

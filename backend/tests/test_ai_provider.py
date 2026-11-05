"""Validasi settings provider dan model, tanpa akses jaringan."""

import unittest
from app.config.settings import Settings
from app.controller.api.panel import MODEL_LOKAL


class ProviderTests(unittest.TestCase):
    # TES VALIDASI: tolak provider selain api atau docker.
    def test_invalid_provider_rejected(self):
        with self.assertRaises(ValueError):
            Settings(_env_file=None, ai_provider="invalid")

    # Bawaan settings harus sama dengan bawaan panel dan termasuk pilihan model di panel.
    def test_default_local_model_matches_panel(self):
        bawaan = Settings.model_fields["ollama_model"].default
        self.assertEqual(bawaan, "qwen3:14b")
        self.assertIn(bawaan, MODEL_LOKAL)

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

import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from controller.api.rooms import router
from services.checker_service import CheckerService
from services.analysis_service import AnalysisService


class CheckerTests(unittest.TestCase):
    # TES CHECKER: periksa batas 100 trace, pemisahan ruangan, dan snapshot yang tidak mengubah data internal.
    def test_history_is_bounded_scoped_and_copied(self):
        checker = CheckerService()
        for index in range(105):
            checker.begin('ABC123', 'alice', str(index))
        self.assertEqual(len(checker.list('ABC123')), 100)
        self.assertEqual(checker.list('ABC123')[0]['message'], '104')
        self.assertEqual(checker.list('FFFFFF'), [])
        snapshot = checker.list('ABC123')
        snapshot[0]['message'] = 'changed'
        self.assertEqual(checker.list('ABC123')[0]['message'], '104')

    # TES API DEBUG: pastikan checker publik di development, tetapi format kode ruangan tetap divalidasi.
    def test_dev_endpoint_requires_no_login_but_validates_code(self):
        app = FastAPI()
        app.include_router(router)
        checker = CheckerService()
        checker.begin('ABC123', 'alice', 'hello')
        with patch('controller.api.rooms.checker_service', checker), TestClient(app) as client:
            response = client.get('/api/rooms/abc123/checker')
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()['traces'][0]['message'], 'hello')
            self.assertEqual(client.get('/api/rooms/FFFFFF/checker').json()['traces'], [])
            self.assertEqual(client.get('/api/rooms/invalid/checker').status_code, 400)


class PromptTraceTests(unittest.IsolatedAsyncioTestCase):
    # TES ASYNC TRACE: cocokkan prompt yang dicatat checker dengan input persis yang diterima adapter mock.
    async def test_captured_prompt_is_exact_provider_input(self):
        analysis = AnalysisService()
        trace = {}
        sent = []
        # CALLBACK MOCK ASYNC: rekam prompt pengujian lalu kembalikan jawaban tiruan tanpa menghubungi LLM.
        async def generate(prompt):
            sent.append(prompt)
            return 'Respons nyata adapter mock'
        with patch('services.analysis_service.settings') as settings, patch('services.analysis_service.generate_reply', generate):
            settings.ai_provider = 'docker'
            settings.ollama_model = 'qwen3:8b'
            result = await analysis.create_host_response(player_name='alice', message='Halo NOX',
                intent='neutral', aggressiveness=10, suspicion_score=12.5,
                suspicion_status='low', trace=trace)
        self.assertEqual(trace['prompt'], sent[0])
        self.assertIn('Halo NOX', trace['prompt'])
        self.assertEqual(trace['model'], 'qwen3:8b')
        self.assertEqual(result, 'Respons nyata adapter mock')

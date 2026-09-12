import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from config.settings import Settings
from controller.api.admin import router
from controller.middleware.auth import require_authenticated_user
from services.activity_service import ActivityService
from services.ai_runtime_service import ai_runtime
from services.match_engine import Match


class PublicVoteTests(unittest.TestCase):
    def test_five_votes_counted_once_with_names_only_during_tribunal(self):
        game = Match(list('abcdef'), [])
        game.phase = 'tribunal'
        for voter in 'abcde':
            game.vote(voter, 'f')
        with self.assertRaises(ValueError):
            game.vote('a', 'b')
        for viewer in game.players:
            public = game.snapshot(viewer)
            votes = next(item for item in public['tribunal_votes'] if item['target'] == 'f')
            self.assertEqual(votes['voters'], list('abcde'))
            self.assertTrue(all(set(p) == {'name','bot','alive'} for p in public['players']))
        game.phase = 'day'
        self.assertEqual(game.snapshot('a')['tribunal_votes'], [])

    def test_gag_and_hostage_cannot_add_public_votes(self):
        game = Match(list('abcd'), [])
        game.phase = 'tribunal'
        game.players['a'].gagged = True
        game.players['b'].hostage = True
        for voter in 'ab':
            with self.assertRaises(ValueError):
                game.vote(voter,'c')
        self.assertTrue(all(not item['voters'] for item in game.snapshot('d')['tribunal_votes']))


class AdminTests(unittest.TestCase):
    def setUp(self):
        ai_runtime.reset()
        self.app = FastAPI()
        self.app.include_router(router)
        self.client = TestClient(self.app)

    def tearDown(self):
        ai_runtime.reset()
        self.client.close()

    def admin(self):
        self.app.dependency_overrides[require_authenticated_user] = lambda: SimpleNamespace(username='user1')

    def test_anonymous_and_nonadmin_denied_for_read_and_write(self):
        self.assertEqual(self.client.get('/api/admin/rooms').status_code, 401)
        self.assertEqual(self.client.post('/api/admin/provider',json={'provider':'api','model':'8'}).status_code, 401)
        self.app.dependency_overrides[require_authenticated_user] = lambda: SimpleNamespace(username='janice')
        for path in ['/api/admin/rooms','/api/admin/activity','/api/admin/rooms/ABC123/traces']:
            self.assertEqual(self.client.get(path).status_code, 403)
        self.assertEqual(self.client.post('/api/admin/provider',json={'provider':'api','model':'8'}).status_code, 403)

    def test_admin_html_and_assets_have_no_embedded_credentials(self):
        page = self.client.get('/admin')
        self.assertEqual(page.status_code, 200)
        self.assertIn('frame-ancestors',page.headers['content-security-policy'])
        self.assertNotIn('user132', page.text)
        self.assertEqual(self.client.get('/admin/assets/admin.js').status_code,200)
        self.assertEqual(self.client.get('/admin/assets/anything').status_code,422)

    def test_provider_validate_check_availability_and_reset(self):
        self.admin()
        config = Settings(_env_file=None, ai_provider='api', OLLAMA_MODEL='8', OPENAI_API_KEY='fixture-secret')
        with patch('services.ai_runtime_service.settings',config):
            with patch('controller.api.admin.model_available',AsyncMock(return_value=False)):
                self.assertEqual(self.client.post('/api/admin/provider',json={'provider':'docker','model':'14'}).status_code,400)
                self.assertEqual(ai_runtime.current().ai_provider,'api')
            with patch('controller.api.admin.model_available',AsyncMock(return_value=True)):
                response = self.client.post('/api/admin/provider',json={'provider':'docker','model':'14'})
                self.assertEqual(response.status_code,200)
                self.assertEqual(response.json()['model'],'qwen3:14b')
                self.assertNotIn('fixture-secret', response.text)
                self.assertEqual(self.client.get('/api/admin/status').headers['cache-control'],'no-store')
            self.assertEqual(self.client.post('/api/admin/provider',json={'provider':'other','model':'14'}).status_code,422)
            self.client.post('/api/admin/provider/reset')
            self.assertEqual(ai_runtime.current().ai_provider,'api')
            self.assertIsNone(ai_runtime.override)

    def test_selection_does_not_mutate_inflight_snapshot(self):
        before = ai_runtime.current(Settings(_env_file=None, ai_provider='api'))
        ai_runtime.select('docker','14')
        self.assertEqual(before.ai_provider,'api')
        self.assertEqual(ai_runtime.current().ai_provider,'docker')

    def test_activity_redacts_nested_secrets_and_bounds_history(self):
        log = ActivityService()
        for index in range(2010):
            log.record('ABC123','test',{'index':index,'headers':{'Authorization':'secret'},'password':'secret','api_key':'secret'})
        self.assertEqual(len(log.events),2000)
        self.assertEqual(len(log.list('ABC123')),200)
        self.assertEqual(log.list('other'),[])
        params = log.list()[0]['params']
        self.assertEqual(params['headers']['Authorization'],'[REDACTED]')
        self.assertEqual(params['password'],'[REDACTED]')
        self.assertEqual(params['api_key'],'[REDACTED]')

    def test_production_denies_admin_even_with_admin_account(self):
        self.admin()
        with patch('controller.api.admin.settings',Settings(_env_file=None, app_environment='production')):
            self.assertEqual(self.client.get('/admin').status_code,404)
            self.assertEqual(self.client.get('/api/admin/rooms').status_code,403)

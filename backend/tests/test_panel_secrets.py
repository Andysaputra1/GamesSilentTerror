import json
import unittest
from unittest.mock import Mock, patch
from cryptography.fernet import Fernet
from pydantic import SecretStr
from fastapi import FastAPI
from fastapi.testclient import TestClient
from config.settings import settings
from services.ai_runtime_service import ai_runtime, save_panel_configuration, load_panel_configuration
from services.persistence_service import PersistenceError
from controller.api.panel import router, require_panel

class PanelSecretsTests(unittest.TestCase):
    def setUp(self):
        self.stored = None
        self.db = Mock()
        def execute(sql, params=None):
            if str(sql).lstrip().startswith('SELECT'):
                return Mock(scalar=lambda: self.stored)
            self.stored=params['config']
            return Mock()
        self.db.execute.side_effect=execute
        self.run=patch('services.persistence_service.PersistenceService._run',side_effect=lambda fn:fn(self.db))
        self.run.start()
        self.key=patch.object(settings,'panel_encryption_key',SecretStr(Fernet.generate_key().decode()))
        self.key.start()
        ai_runtime.reset()
        app=FastAPI();app.include_router(router)
        app.dependency_overrides[require_panel]=lambda:'test-token'
        self.client=TestClient(app)

    def tearDown(self):
        self.client.close();self.run.stop();self.key.stop();ai_runtime.reset()

    def test_save_encrypt_restart_blank_and_replace_without_echo(self):
        result=self.client.put('/api/panel/config',json={'provider':'api','api_key':'fixture-private-key'})
        self.assertEqual(result.status_code,200)
        self.assertNotIn('fixture-private-key',result.text)
        self.assertNotIn('fixture-private-key',self.stored)
        self.assertIn('openrouter_key_encrypted',json.loads(self.stored))
        ai_runtime.reset();load_panel_configuration()
        self.assertEqual(ai_runtime.current().openrouter_api_key.get_secret_value(),'fixture-private-key')
        self.assertNotIn('fixture-private-key',self.client.get('/api/panel/config').text)
        self.client.put('/api/panel/config',json={'provider':'api','api_key':'  '})
        ai_runtime.reset();load_panel_configuration()
        self.assertEqual(ai_runtime.current().openrouter_api_key.get_secret_value(),'fixture-private-key')
        save_panel_configuration('docker','https://example.com')
        self.assertEqual(ai_runtime.current().openrouter_api_key.get_secret_value(),'fixture-private-key')
        save_panel_configuration('api','https://example.com','replacement-key')
        self.assertEqual(ai_runtime.current().openrouter_api_key.get_secret_value(),'replacement-key')
        self.assertNotIn('replacement-key',self.stored)

    def test_missing_encryption_key_cannot_save_plaintext(self):
        with patch.object(settings,'panel_encryption_key',None):
            with self.assertRaises(PersistenceError):
                save_panel_configuration('api','https://example.com','fixture-private-key')
        self.assertIsNone(self.stored)
        self.assertIsNone(ai_runtime.override)

    def test_wrong_key_cannot_decrypt(self):
        save_panel_configuration('api','https://example.com','fixture-private-key')
        ai_runtime.reset()
        with patch.object(settings,'panel_encryption_key',SecretStr(Fernet.generate_key().decode())):
            with self.assertRaises(PersistenceError):load_panel_configuration()
        self.assertIsNone(ai_runtime.override)

    def test_invalid_key_validation_does_not_echo_secret(self):
        response=self.client.put('/api/panel/config',json={'provider':'api','api_key':'private key with whitespace'})
        self.assertEqual(response.status_code,400)
        self.assertNotIn('private key with whitespace',response.text)

    def test_default_and_custom_switch_preserves_secret_across_restart(self):
        with patch.object(settings, 'openrouter_default', SecretStr('server-default-fixture')):
            response = self.client.put('/api/panel/config', json={'provider':'api','key_source':'default'})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()['key_source'], 'default')
            self.assertEqual(ai_runtime.current().openrouter_api_key_value, 'server-default-fixture')
            self.assertNotIn('server-default-fixture', response.text)
            self.assertNotIn('server-default-fixture', self.stored)
            response = self.client.put('/api/panel/config', json={'provider':'api','key_source':'custom','api_key':'custom-fixture'})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(ai_runtime.current().openrouter_api_key_value, 'custom-fixture')
            self.client.put('/api/panel/config', json={'provider':'api','key_source':'default'})
            ai_runtime.reset(); load_panel_configuration()
            self.assertEqual(ai_runtime.current().openrouter_api_key_value, 'server-default-fixture')
            self.assertTrue(self.client.get('/api/panel/config').json()['custom_configured'])
            self.client.put('/api/panel/config', json={'provider':'api','key_source':'custom'})
            ai_runtime.reset(); load_panel_configuration()
            self.assertEqual(ai_runtime.current().openrouter_api_key_value, 'custom-fixture')
            self.assertNotIn('custom-fixture', self.stored)

    def test_empty_custom_does_not_fall_back_to_default(self):
        with patch.object(settings, 'openrouter_default', SecretStr('server-default-fixture')):
            response=self.client.put('/api/panel/config',json={'provider':'api','key_source':'custom'})
            self.assertEqual(response.status_code,400)
            self.assertIsNone(self.stored)

    def test_lowercase_environment_alias(self):
        from config.settings import Settings
        with patch.dict('os.environ', {'openrouter_default':'alias-fixture'}):
            config=Settings(_env_file=None)
            self.assertEqual(config.openrouter_api_key_value, 'alias-fixture')

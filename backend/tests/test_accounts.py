"""Regresi register/Google: SQLite menguji SQL, transaksi, dan sesi tanpa akun nyata."""
import unittest
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from controller.api.auth import router
from controller.middleware.auth_limits import _attempts
from config.settings import settings
from services.google_identity_service import nonces


class AccountTests(unittest.TestCase):
    def setUp(self):
        _attempts.clear()
        self.engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
        with self.engine.begin() as db:
            db.execute(text('CREATE TABLE user_accounts (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE, display_name TEXT, password_hash TEXT, is_active BOOLEAN DEFAULT 1)'))
            db.execute(text('CREATE TABLE account_identities (user_id INTEGER PRIMARY KEY, email TEXT UNIQUE, google_subject TEXT UNIQUE, email_verified BOOLEAN)'))
            db.execute(text('CREATE TABLE auth_sessions (user_id INTEGER, token_hash TEXT, expires_at DATETIME)'))
        self.session_patch = patch('services.auth_service.SessionLocal', sessionmaker(bind=self.engine))
        self.session_patch.start()
        app = FastAPI()
        app.include_router(router)
        self.client = TestClient(app)
        self.origin = {'Origin': 'http://localhost:4200'}
        self.body = {'username': 'detective_test', 'email': 'test@example.com',
            'email_confirmation': 'test@example.com', 'password': 'strong-test-password',
            'password_confirmation': 'strong-test-password'}

    def tearDown(self):
        self.client.close()
        self.session_patch.stop()
        self.engine.dispose()
        _attempts.clear()

    def register(self, **changes):
        return self.client.post('/api/auth/register', json={**self.body, **changes})

    def test_register_password_hash_email_login_and_duplicates(self):
        response = self.register()
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.headers['cache-control'], 'no-store')
        self.assertTrue(response.json()['access_token'])
        with self.engine.connect() as db:
            row = db.execute(text('SELECT password_hash FROM user_accounts')).scalar()
            self.assertNotEqual(row, self.body['password'])
            self.assertTrue(row.startswith('pbkdf2_sha256'))
            self.assertEqual(db.execute(text('SELECT email_verified FROM account_identities')).scalar(), 0)
        login = self.client.post('/api/auth/login', json={'username': 'test@example.com', 'password': self.body['password']})
        self.assertEqual(login.status_code, 200)
        self.assertEqual(self.register().status_code, 409)
        self.assertEqual(self.register(username='another').status_code, 409)
        with self.engine.connect() as db:
            self.assertEqual(db.execute(text('SELECT count(*) FROM user_accounts')).scalar(), 1)

    def test_validation_reserved_and_rate_limit(self):
        self.assertEqual(self.register(password_confirmation='different-password').status_code, 422)
        self.assertEqual(self.register(email_confirmation='other@example.com').status_code, 422)
        self.assertEqual(self.register(username='NOX').status_code, 409)
        self.assertEqual(self.register(username='user1').status_code, 409)
        self.assertEqual(self.register(username='x<script>').status_code, 422)
        for _ in range(16):
            response = self.register(username='NOX')
        self.assertEqual(response.status_code, 429)

    def test_google_disabled_and_wrong_origin(self):
        with patch.object(settings, 'google_client_id', ''):
            self.assertEqual(self.client.post('/api/auth/google/challenge', headers=self.origin).status_code, 503)
        self.assertEqual(self.client.post('/api/auth/google/challenge', headers={'Origin':'http://evil.invalid'}).status_code, 403)

    def google(self, email='google@example.com', subject='google-subject', **changes):
        nonce = nonces.issue()
        claims = {'sub': subject, 'email': email, 'email_verified': True, 'nonce': nonce, 'name': 'Google Detective', **changes}
        with patch.object(settings, 'google_client_id', 'test-client'), patch('services.google_identity_service.id_token.verify_oauth2_token', return_value=claims) as verify:
            response = self.client.post('/api/auth/google', headers=self.origin, json={'credential':'test-token', 'nonce':nonce})
            self.assertEqual(verify.call_args.args[2], 'test-client')
        return response, nonce

    def test_google_account_reuse_and_nonce_replay(self):
        first, nonce = self.google()
        self.assertEqual(first.status_code, 200)
        second, _ = self.google()
        self.assertEqual(first.json()['user'], second.json()['user'])
        with patch.object(settings, 'google_client_id', 'test-client'):
            replay = self.client.post('/api/auth/google', headers=self.origin, json={'credential':'test-token', 'nonce':nonce})
        self.assertEqual(replay.status_code, 401)

    def test_google_mismatched_nonce_unverified_and_no_email_linking(self):
        self.assertEqual(self.google(nonce='wrong')[0].status_code, 401)
        self.assertEqual(self.google(email_verified=False)[0].status_code, 401)
        self.assertEqual(self.register().status_code, 201)
        self.assertEqual(self.google(email=self.body['email'])[0].status_code, 409)
        with self.engine.connect() as db:
            self.assertEqual(db.execute(text('SELECT count(*) FROM user_accounts')).scalar(), 1)

    def test_google_bad_signature_or_audience_rejected(self):
        nonce = nonces.issue()
        with patch.object(settings, 'google_client_id', 'test-client'), patch('services.google_identity_service.id_token.verify_oauth2_token', side_effect=ValueError('bad token')):
            response = self.client.post('/api/auth/google', headers=self.origin, json={'credential':'forged-token', 'nonce':nonce})
        self.assertEqual(response.status_code, 401)

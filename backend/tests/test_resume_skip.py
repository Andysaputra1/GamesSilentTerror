"""Regresi: satu pertandingan aktif per akun dan persetujuan diskusi privat."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from fastapi import FastAPI, Header
from fastapi.testclient import TestClient
from controller.api.rooms import router
from controller.middleware.auth import require_authenticated_user
from services.match_engine import Match
from services.room_service import RoomService


class SkipTests(unittest.TestCase):
    def setUp(self):
        self.game = Match(['alice', 'bob', 'carol'], ['NOX'], now=0)

    def test_requires_all_humans_but_not_bot_and_duplicate_is_idempotent(self):
        self.game.skip_discussion('alice', now=1)
        self.game.skip_discussion('alice', now=1)
        self.assertEqual(self.game.snapshot('bob')['discussion_skip']['agreed'], 1)
        self.game.skip_discussion('bob', now=2)
        self.assertEqual(self.game.phase, 'day')
        with self.assertRaises(ValueError):
            self.game.skip_discussion('NOX')
        self.game.skip_discussion('carol', now=3)
        self.assertEqual(self.game.phase, 'night')
        self.assertEqual(self.game.deadline, 33)
        self.assertFalse(self.game.can_chat('alice'))

    def test_muted_humans_still_consent_without_revealing_status(self):
        self.game.players['bob'].hostage = True
        self.game.players['carol'].gagged = True
        for name in ['bob', 'carol']:
            self.assertTrue(self.game.snapshot(name)['discussion_skip']['can_consent'])
        self.game.skip_discussion('alice', now=1)
        self.assertEqual(self.game.snapshot('alice')['discussion_skip']['required'], 3)
        self.game.skip_discussion('bob', now=1)
        self.game.skip_discussion('carol', now=1)
        self.assertEqual(self.game.phase, 'night')

    def test_dead_excluded_outsider_wrong_phase_rejected(self):
        self.game.players['bob'].alive = False
        for name in ['bob', 'outsider']:
            with self.assertRaises(ValueError):
                self.game.skip_discussion(name)
        self.assertEqual(self.game.snapshot('alice')['discussion_skip']['required'], 2)
        self.game.skip_discussion('alice', now=1)
        self.game.skip_discussion('carol', now=1)
        with self.assertRaises(ValueError):
            self.game.skip_discussion('alice')

    def test_partial_consent_keeps_deadline_and_resets_next_day(self):
        self.game.skip_discussion('alice', now=1)
        self.assertEqual(self.game.deadline, 120)
        self.game.phase = 'tribunal'
        # Fokus pada reset consent tanpa eksekusi. Vote bot acak dapat membunuh
        # Hitman dan mengakhiri match secara sah sebelum ronde berikutnya.
        self.game.bot_vote_done = True
        self.game.tick(120)
        self.assertEqual(self.game.round, 2)
        self.assertEqual(self.game.skip_consents, set())

    def test_single_human_can_skip_alone(self):
        game = Match(['alice'], ['NOX', 'ECHO', 'VEIL'], now=0)
        game.skip_discussion('alice', now=1)
        self.assertEqual(game.phase, 'night')


class ActiveRoomTests(unittest.TestCase):
    def setUp(self):
        self.rooms = RoomService()
        self.room = self.rooms.create('alice')
        self.rooms.join(self.room.code, 'bob')
        self.rooms.set_bot(self.room.code, 'alice', True)
        self.other = self.rooms.create('carol')
        self.rooms.start(self.room.code, 'alice')

    def test_lookup_and_no_second_room(self):
        active = self.rooms.active('alice')
        self.assertEqual(active['code'], self.room.code)
        self.assertEqual(set(active), {'code', 'match_id'})
        self.assertIsNone(self.rooms.active('outsider'))
        self.assertIs(self.rooms.join(self.room.code, 'alice'), self.room)
        with self.assertRaises(ValueError):
            self.rooms.create('alice')
        with self.assertRaises(ValueError):
            self.rooms.join(self.other.code, 'bob')

    def test_no_start_with_busy_member_and_finished_releases_account(self):
        self.other.members.append('alice')  # akun sudah bergabung sebelum match pertama mulai
        self.rooms.set_bot(self.other.code, 'carol', True)
        with self.assertRaises(ValueError):
            self.rooms.start(self.other.code, 'carol')
        hitman = next(p for p in self.room.match.players.values() if p.role == 'hitman')
        hitman.alive = False
        self.room.match.check_winner()
        self.assertIsNone(self.rooms.active('alice'))
        self.rooms.start(self.other.code, 'carol')

    def test_api_lookup_route_and_skip_validation(self):
        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[require_authenticated_user] = lambda x_user=Header('alice'): SimpleNamespace(username=x_user)
        with patch('controller.api.rooms.room_service', self.rooms), TestClient(app) as client:
            self.assertEqual(client.get('/api/rooms/active').json()['active']['code'], self.room.code)
            self.assertIsNone(client.get('/api/rooms/active', headers={'x-user':'outsider'}).json()['active'])
            current = client.get('/api/rooms/current').json()['room']
            self.assertEqual(current['code'], self.room.code)
            self.assertNotIn('players', current)
            self.assertIsNone(client.get('/api/rooms/current', headers={'x-user':'outsider'}).json()['room'])
            endpoint = '/api/rooms/' + self.room.code + '/skip-discussion'
            payload = {'match_id':self.room.match.id, 'round_number':1, 'phase':'day'}
            self.assertEqual(client.post(endpoint, json={**payload, 'match_id':'stale'}).status_code, 400)
            self.assertEqual(client.post(endpoint, json=payload, headers={'x-user':'outsider'}).status_code, 400)
            self.assertEqual(client.post(endpoint, json=payload).json()['game']['phase'], 'day')
            self.assertEqual(client.post(endpoint, json=payload, headers={'x-user':'bob'}).json()['game']['phase'], 'night')
            self.assertEqual(client.post(endpoint, json=payload).status_code, 400)

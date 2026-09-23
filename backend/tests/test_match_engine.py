"""Aturan game diuji tanpa LLM/DB agar hasil deterministik dan cepat."""

import random
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from fastapi import FastAPI, Header
from fastapi.testclient import TestClient
from controller.api.rooms import router
from controller.middleware.auth import require_authenticated_user
from realtime.socket_handlers import SocketGameController
from services.match_engine import Match
from services.room_service import RoomService


class EngineTests(unittest.TestCase):
    # FIXTURE: nama sama dengan role supaya setiap skenario mudah dibaca.
    def setUp(self):
        self.game = Match(['hitman', 'spy', 'stalker', 'civilian'], [], now=0, rng=random.Random(7))
        for name, player in self.game.players.items():
            player.role = name

    def night(self):
        self.game.phase = 'night'
        self.game.actions.clear()

    def test_idle_match_finishes_after_eight_rounds(self):
        for _ in range(24):
            self.game.tick(self.game.deadline)
        self.assertEqual((self.game.round, self.game.phase, self.game.winner), (8, 'finished', 'draw'))
        self.assertTrue(all('role' in p for p in self.game.snapshot('spy')['players']))
        self.assertFalse(self.game.can_chat('spy'))
        events = list(self.game.events)
        self.game.tick(self.game.deadline + 1000)
        self.game.check_winner()
        self.assertEqual(self.game.events, events)

    def test_final_round_execution_takes_priority_over_draw(self):
        self.game.round = 8
        self.game.phase = 'tribunal'
        self.game.vote('spy', 'hitman')
        self.game.tick(self.game.deadline)
        self.assertEqual(self.game.winner, 'civilians')

    def test_ai_grace_is_bounded_and_does_not_extend_night(self):
        self.game.reserve_ai_reply(now=115)
        self.assertEqual(self.game.deadline, 150)
        self.game.reserve_ai_reply(now=149)
        self.assertEqual(self.game.deadline, 150)
        self.game.tick(150)
        deadline = self.game.deadline
        self.game.reserve_ai_reply(now=179)
        self.assertEqual(self.game.deadline, deadline)

    def test_role_distribution_and_size(self):
        for count in range(4, 7):
            game = Match([str(i) for i in range(count)], [])
            roles = [p.role for p in game.players.values()]
            for role in ['hitman', 'spy', 'stalker']:
                self.assertEqual(roles.count(role), 1)
            self.assertEqual(roles.count('civilian'), count - 3)
        for humans in [[], ['a'] * 4, list('abcdefg')]:
            with self.assertRaises(ValueError):
                Match(humans, [])

    def test_blind_actions_and_guard_priority(self):
        self.night()
        self.game.act('hitman', 'hostage', 'civilian')
        self.game.act('spy', 'guard', 'civilian')
        self.assertFalse(self.game.players['civilian'].hostage)
        self.assertIsNone(self.game.snapshot('stalker')['me']['action'])
        self.game.resolve_night()
        self.assertFalse(self.game.players['civilian'].hostage)
        self.assertEqual(self.game.players['spy'].last_guard, 'civilian')

    def test_guard_consecutive_nights_but_can_self_guard(self):
        self.night()
        self.game.act('spy', 'guard', 'spy')
        self.game.resolve_night()
        self.game.round = 2
        self.game.actions.clear()
        with self.assertRaises(ValueError):
            self.game.act('spy', 'guard', 'spy')
        self.game.act('spy', 'guard', 'civilian')
        self.game.resolve_night()
        self.game.round = 3
        self.game.actions.clear()
        self.game.act('spy', 'guard', 'spy')

    def test_peek_private_and_cooldown(self):
        self.night()
        self.game.act('stalker', 'peek', 'hitman')
        self.assertEqual(self.game.snapshot('stalker')['me']['intel'], [])
        self.game.resolve_night()
        self.assertEqual(self.game.snapshot('stalker')['me']['intel'][0]['role'], 'hitman')
        self.assertEqual(self.game.snapshot('spy')['me']['intel'], [])
        self.game.round = 2
        self.game.actions.clear()
        with self.assertRaises(ValueError):
            self.game.act('stalker', 'peek', 'spy')
        self.game.round = 3
        self.game.act('stalker', 'peek', 'spy')

    def test_gag_blocks_chat_vote_expires_and_skips_one_round(self):
        self.game.act('hitman', 'gag', 'civilian')
        self.assertFalse(self.game.can_chat('civilian'))
        with self.assertRaises(ValueError):
            self.game.act('hitman', 'gag', 'spy')
        self.game.phase = 'tribunal'
        with self.assertRaises(ValueError):
            self.game.vote('civilian', 'hitman')
        self.game.tick(self.game.deadline)
        self.assertEqual(self.game.round, 2)
        self.assertTrue(self.game.can_chat('civilian'))
        with self.assertRaises(ValueError):
            self.game.act('hitman', 'gag', 'civilian')
        self.game.round = 3
        self.game.act('hitman', 'gag', 'civilian')

    def test_hostage_silent_alive_permanent(self):
        self.night()
        self.game.act('hitman', 'hostage', 'civilian')
        self.game.resolve_night()
        self.game.phase = 'tribunal'
        self.assertTrue(self.game.players['civilian'].alive)
        self.assertFalse(self.game.can_chat('civilian'))
        with self.assertRaises(ValueError):
            self.game.vote('civilian', 'hitman')
        self.game.tick(self.game.deadline)
        self.assertFalse(self.game.can_chat('civilian'))
        for viewer in self.game.players:
            snapshot = self.game.snapshot(viewer)
            for player in snapshot['players']:
                self.assertEqual(set(player), {'name', 'bot', 'alive'})
            self.assertNotIn('civilian', ' '.join(snapshot['events']))
            self.assertNotIn('actions', snapshot)
            self.assertNotIn('votes', snapshot)

    def test_wrong_role_phase_target_and_duplicate_rejected(self):
        for name, ability, target in [('spy', 'gag', 'civilian'), ('hitman', 'hostage', 'spy'), ('hitman', 'gag', 'hitman'), ('hitman', 'gag', 'unknown')]:
            with self.assertRaises(ValueError):
                self.game.act(name, ability, target)
        self.night()
        for ability in [None, 'peek', 'guard']:
            with self.assertRaises(ValueError):
                self.game.act('civilian', ability, 'hitman')
        self.game.act('hitman', 'hostage', 'spy')
        with self.assertRaises(ValueError):
            self.game.act('hitman', 'hostage', 'stalker')
        self.assertFalse(self.game.can_chat('hitman'))

    def test_vote_unique_tie_and_civilian_victory(self):
        self.game.phase = 'tribunal'
        self.game.vote('civilian', 'hitman')
        with self.assertRaises(ValueError):
            self.game.vote('civilian', 'spy')
        self.game.vote('hitman', 'civilian')
        self.game.resolve_votes()
        self.assertTrue(all(p.alive for p in self.game.players.values()))
        self.game.votes.clear()
        self.game.vote('spy', 'hitman')
        self.game.vote('stalker', 'hitman')
        self.game.vote('hitman', 'civilian')
        self.game.resolve_votes()
        self.assertEqual(self.game.winner, 'civilians')
        self.assertEqual(self.game.phase, 'finished')
        self.assertTrue(all('role' in p for p in self.game.snapshot('spy')['players']))
        self.assertFalse(self.game.can_chat('spy'))

    def test_hitman_victory_when_remaining_citizens_hostage(self):
        self.game.players['spy'].alive = False
        self.game.players['stalker'].hostage = True
        self.night()
        self.game.act('hitman', 'hostage', 'civilian')
        self.game.resolve_night()
        self.assertEqual(self.game.winner, 'hitman')

    def test_timer_and_bots_complete_games_without_browser(self):
        for seed in range(30):
            game = Match([], ['a', 'b', 'c', 'd'], now=0, quick=True, rng=random.Random(seed))
            game.tick(1)
            self.assertFalse(game.bot_day_done)
            phases = set()
            for _ in range(300):
                phases.add(game.phase)
                if game.winner:
                    break
                game.tick(game.deadline)
            self.assertIsNotNone(game.winner, f'seed={seed}')
            self.assertTrue({'day', 'night', 'tribunal'} <= phases)


class RoomGameTests(unittest.TestCase):
    def setUp(self):
        self.rooms = RoomService()
        self.room = self.rooms.create('alice')
        self.rooms.set_bot(self.room.code, 'alice', True)

    def test_bot_fill_host_start_rejoin_and_roster_lock(self):
        self.assertEqual(len(self.rooms.snapshot(self.room)['bots']), 3)
        self.rooms.join(self.room.code, 'bob')
        self.assertEqual(len(self.rooms.snapshot(self.room)['bots']), 2)
        with self.assertRaises(ValueError):
            self.rooms.start(self.room.code, 'bob')
        self.rooms.start(self.room.code, 'alice')
        self.rooms.join(self.room.code, 'bob')
        for operation in [lambda: self.rooms.join(self.room.code, 'outsider'), lambda: self.rooms.set_bot(self.room.code, 'alice', False), lambda: self.rooms.leave(self.room.code, 'alice'), lambda: self.rooms.start(self.room.code, 'alice')]:
            with self.assertRaises(ValueError):
                operation()
        self.assertEqual(self.rooms.state(self.room.code, 'alice')['game']['me']['role'], self.room.match.players['alice'].role)

    def test_stale_phase_and_nonmember(self):
        self.rooms.start(self.room.code, 'alice')
        with self.assertRaises(ValueError):
            self.rooms.play(self.room.code, 'alice', match_id='old', round_number=1, phase='day', target='NOX', ability='gag')
        with self.assertRaises(ValueError):
            self.rooms.state(self.room.code, 'outsider')

    def test_leave_transfers_owner_and_cleans_empty_room(self):
        self.rooms.join(self.room.code, 'bob')
        self.rooms.leave(self.room.code, 'alice')
        self.assertEqual(self.room.owner, 'bob')
        self.rooms.leave(self.room.code, 'bob')
        self.assertNotIn(self.room.code, self.rooms.rooms)

    # HTTP integration dengan identitas fixture; otorisasi room tetap service sungguhan.
    def test_http_membership_checker_and_play_validation(self):
        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[require_authenticated_user] = lambda x_user=Header('alice'): SimpleNamespace(username=x_user)
        with patch('controller.api.rooms.room_service', self.rooms), TestClient(app) as client:
            base = '/api/rooms/' + self.room.code
            self.assertEqual(client.post(base + '/start', json={'quick': True}, headers={'x-user': 'outsider'}).status_code, 400)
            self.assertEqual(client.get(base + '/checker').status_code, 410)
            self.assertEqual(client.post(base + '/start', json={'quick': True}).status_code, 200)
            self.assertEqual(client.get(base + '/checker').status_code, 410)
            response = client.get(base + '/game')
            self.assertEqual(response.status_code, 200)
            self.assertEqual(len(response.json()['game']['players']), 4)
            self.assertEqual(client.get(base + '/game', headers={'x-user': 'outsider'}).status_code, 400)
            self.assertEqual(client.post(base + '/play', json={'ability': 'kill'}).status_code, 422)
            self.room.match.players[next(n for n, p in self.room.match.players.items() if p.role == 'hitman')].alive = False
            self.room.match.check_winner()
            self.assertEqual(client.get(base + '/checker').status_code, 410)


class SocketGameTests(unittest.IsolatedAsyncioTestCase):
    async def test_revoked_socket_token_cannot_send(self):
        from services.auth_service import SessionValidationError
        sio = Mock(emit=AsyncMock())
        controller = SocketGameController(sio, Mock(), Mock())
        controller.socket_players['sid'] = 'alice'
        controller.socket_tokens['sid'] = 'revoked-test-token'
        with patch('realtime.socket_handlers.auth_service.user_for_token', side_effect=SessionValidationError()):
            await controller.send_chat('sid', {'username':'alice', 'message':'halo'})
        self.assertEqual(sio.emit.call_args.args[0], 'system_alert')
        self.assertIn('login', sio.emit.call_args.args[1]['msg'])

    async def test_night_hostage_gag_malformed_and_spoof_never_echo(self):
        rooms = RoomService()
        room = rooms.create('alice')
        rooms.set_bot(room.code, 'alice', True)
        rooms.start(room.code, 'alice')
        sio = Mock(emit=AsyncMock(), enter_room=AsyncMock())
        controller = SocketGameController(sio, Mock(), Mock())
        controller.socket_players['sid'] = 'alice'
        controller.socket_rooms['sid'] = room.code
        with patch('realtime.socket_handlers.room_service', rooms), patch('realtime.socket_handlers.PersistenceService'):
            for data in [None, [], {'username': 'alice', 'message': {}}, {'username': 'NOX', 'message': 'spoof'}]:
                await controller.send_chat('sid', data)
            room.match.phase = 'night'
            await controller.send_chat('sid', {'username': 'alice', 'message': 'night'})
            room.match.phase = 'day'
            room.match.players['alice'].gagged = True
            await controller.send_chat('sid', {'username': 'alice', 'message': 'gag'})
            room.match.players['alice'].gagged = False
            room.match.players['alice'].hostage = True
            await controller.send_chat('sid', {'username': 'alice', 'message': 'hostage'})
        self.assertFalse(any(c.args[0] == 'receive_chat' for c in sio.emit.call_args_list))
        self.assertEqual(room.match.messages, [])

    async def test_late_ai_cannot_speak_at_night(self):
        rooms = RoomService()
        room = rooms.create('alice')
        rooms.set_bot(room.code, 'alice', True)
        rooms.start(room.code, 'alice')
        sio = Mock(emit=AsyncMock(), enter_room=AsyncMock())
        analysis = Mock()
        analysis.predict_intent.return_value = 'neutral'
        analysis.aggressiveness_for_intent.return_value = 0
        async def late_reply(**kwargs):
            room.match.phase = 'night'
            return 'Balasan terlambat'
        analysis.create_host_response = AsyncMock(side_effect=late_reply)
        controller = SocketGameController(sio, analysis, Mock())
        controller.socket_players['sid'] = 'alice'
        controller.socket_rooms['sid'] = room.code
        controller.room_analysis[room.code] = analysis
        with patch('realtime.socket_handlers.room_service', rooms), patch('realtime.socket_handlers.PersistenceService'):
            await controller.send_chat('sid', {'username': 'alice', 'message': 'halo'})
        self.assertEqual(len(room.match.messages), 1)
        self.assertEqual(room.match.messages[0]['sender'], 'alice')
        self.assertEqual(controller.ai_pending, set())

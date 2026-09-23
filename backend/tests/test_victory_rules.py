"""Aturan kemenangan dan privasi dapat diuji tanpa database maupun AI."""
import random
import unittest

from services.match_engine import Match
from services.room_service import RoomService


class VictoryRulesTests(unittest.TestCase):
    def setUp(self):
        self.game = Match(['hitman', 'spy', 'stalker', 'civilian'], [], now=0, rng=random.Random(7))
        for name, player in self.game.players.items():
            player.role = name

    def test_last_survivor_hostage_wins_at_night_before_voting(self):
        self.game.players['spy'].alive = False
        self.game.players['stalker'].hostage = True
        self.game.phase = 'night'
        self.game.act('hitman', 'hostage', 'civilian')
        self.game.tick(self.game.deadline)
        self.assertEqual(self.game.phase, 'finished')
        result = self.game.snapshot('hitman')['result']
        self.assertEqual(result, {'reason': 'all_survivors_hostage', 'team': 'hitman', 'outcome': 'won',
                                 'civilians_alive': 2, 'civilians_hostage': 2, 'civilians_eliminated': 1})
        self.assertEqual(self.game.snapshot('civilian')['result']['outcome'], 'lost')

    def test_gag_and_equal_numbers_never_count_as_hostage_victory(self):
        self.game.players['spy'].alive = False
        self.game.players['stalker'].hostage = True
        self.game.players['civilian'].gagged = True
        self.game.check_winner()
        self.assertIsNone(self.game.winner)
        self.game.players['stalker'].alive = False
        self.game.check_winner()
        self.assertIsNone(self.game.winner)  # Hitman vs satu warga bebas (walaupun Gag).

    def test_guard_can_prevent_last_hostage_and_game_continues(self):
        self.game.players['stalker'].hostage = True
        self.game.players['civilian'].hostage = True
        self.game.phase = 'night'
        self.game.act('hitman', 'hostage', 'spy')
        self.game.act('spy', 'guard', 'spy')
        self.game.tick(self.game.deadline)
        self.assertIsNone(self.game.winner)
        self.assertEqual(self.game.phase, 'tribunal')

    def test_execution_wins_for_all_civilian_roles_including_dead_and_hostage(self):
        self.game.players['spy'].alive = False
        self.game.players['civilian'].hostage = True
        self.game.phase = 'tribunal'
        self.game.vote('stalker', 'hitman')
        self.game.tick(self.game.deadline)
        self.assertEqual(self.game.winner, 'civilians')
        for name in ['spy', 'stalker', 'civilian']:
            result = self.game.snapshot(name)['result']
            self.assertEqual((result['reason'], result['team'], result['outcome']),
                             ('hitman_executed', 'civilians', 'won'))
        self.assertEqual(self.game.snapshot('hitman')['result']['outcome'], 'lost')

    def test_executing_last_free_civilian_can_give_hitman_victory(self):
        self.game.players['spy'].hostage = True
        self.game.players['stalker'].hostage = True
        self.game.phase = 'tribunal'
        self.game.vote('hitman', 'civilian')
        self.game.tick(self.game.deadline)
        self.assertEqual(self.game.winner_reason, 'all_survivors_hostage')

    def test_no_surviving_civilians_has_distinct_reason(self):
        for name in ['spy', 'stalker']:
            self.game.players[name].alive = False
        self.game.phase = 'tribunal'
        self.game.vote('hitman', 'civilian')
        self.game.tick(self.game.deadline)
        self.assertEqual(self.game.winner_reason, 'no_civilians_alive')
        self.assertEqual(self.game.snapshot('hitman')['result']['civilians_alive'], 0)

    def test_final_round_normal_win_precedes_draw_and_finish_is_immutable(self):
        self.game.round = 8
        self.game.phase = 'tribunal'
        self.game.vote('spy', 'hitman')
        self.game.tick(self.game.deadline)
        events = list(self.game.events)
        self.game.check_winner()
        self.game.tick(self.game.deadline + 100)
        self.assertEqual(self.game.winner_reason, 'hitman_executed')
        self.assertEqual(events, self.game.events)
        self.assertFalse(self.game.snapshot('spy')['me']['can_vote'])
        self.assertFalse(self.game.snapshot('spy')['me']['can_act'])

    def test_draw_has_no_winning_team(self):
        self.game.round = 8
        self.game.phase = 'tribunal'
        self.game.tick(self.game.deadline)
        for viewer in self.game.players:
            self.assertEqual(self.game.snapshot(viewer)['result']['outcome'], 'draw')
        self.assertEqual(self.game.winner_reason, 'round_limit')

    def test_active_snapshot_keeps_other_hostages_private(self):
        self.game.players['spy'].hostage = True
        self.game.players['stalker'].gagged = True
        for viewer in self.game.players:
            snapshot = self.game.snapshot(viewer)
            self.assertIsNone(snapshot['result'])
            self.assertTrue(all(set(p) == {'name', 'bot', 'alive'} for p in snapshot['players']))
            self.assertEqual(snapshot['me']['hostage'], viewer == 'spy')
            self.assertEqual(snapshot['me']['gagged'], viewer == 'stalker')


class SingleRoomTests(unittest.TestCase):
    def setUp(self):
        self.rooms = RoomService()
        self.first = self.rooms.create('alice')
        self.other = self.rooms.create('bob')

    def test_no_duplicate_lobby_membership_and_leave_allows_switch(self):
        with self.assertRaises(ValueError):
            self.rooms.create('alice')
        with self.assertRaises(ValueError):
            self.rooms.join(self.other.code, 'alice')
        self.assertIs(self.rooms.current('alice'), self.first)
        self.assertIs(self.rooms.join(self.first.code, 'alice'), self.first)
        self.rooms.leave(self.first.code, 'alice')
        self.assertIs(self.rooms.join(self.other.code, 'alice'), self.other)
        self.assertNotIn(self.first.code, self.rooms.rooms)

    def test_finished_room_is_recoverable_until_player_leaves(self):
        self.rooms.set_bot(self.first.code, 'alice', True)
        self.rooms.start(self.first.code, 'alice')
        hitman = next(p for p in self.first.match.players.values() if p.role == 'hitman')
        hitman.alive = False
        self.first.match.check_winner()
        self.assertIsNone(self.rooms.active('alice'))
        self.assertEqual(self.rooms.snapshot(self.rooms.current('alice'))['phase'], 'finished')
        with self.assertRaises(ValueError):
            self.rooms.join(self.other.code, 'alice')
        self.rooms.leave(self.first.code, 'alice')
        self.assertIsNone(self.rooms.current('alice'))
        self.rooms.create('alice')


if __name__ == '__main__':
    unittest.main()

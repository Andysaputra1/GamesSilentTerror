"""Aturan kemenangan dan privasi dapat diuji tanpa database maupun AI."""

import random
import unittest

from services.match_engine import Match
from services.room_service import RoomService


class VictoryRulesTests(unittest.TestCase):
    def setUp(self):
        self.game = Match(
            ["hitman", "spy", "stalker", "civilian", "civilian2", "civilian3"],
            [],
            now=0,
            rng=random.Random(7),
        )
        for name, player in self.game.players.items():
            player.role = name if name in {"hitman", "spy", "stalker"} else "civilian"

    def test_last_survivor_hostage_wins_at_night_before_voting(self):
        self.game.players["civilian2"].alive = False
        self.game.players["civilian3"].alive = False
        self.game.players["spy"].alive = False
        self.game.players["stalker"].hostage = True
        self.game.phase = "night"
        self.game.act("hitman", "hostage", "civilian")
        self.game.tick(self.game.deadline)
        self.assertEqual(self.game.phase, "finished")
        result = self.game.snapshot("hitman")["result"]
        self.assertEqual(
            result,
            {
                "reason": "all_survivors_hostage",
                "team": "hitman",
                "outcome": "won",
                "civilians_alive": 2,
                "civilians_hostage": 2,
                "civilians_eliminated": 3,
                "civilians_voters": 0,
            },
        )
        self.assertEqual(self.game.snapshot("civilian")["result"]["outcome"], "lost")

    def test_gag_does_not_reduce_votes_but_parity_wins(self):
        for name in ["spy", "stalker", "civilian2"]:
            self.game.players[name].hostage = True
        self.game.players["civilian"].gagged = True
        self.game.check_winner()
        self.assertIsNone(self.game.winner)  # Two free citizens still outvote Hitman.
        self.game.players["civilian3"].alive = False
        self.game.check_winner()
        self.assertEqual(self.game.winner_reason, "vote_control")
        self.assertEqual(self.game.result("hitman")["civilians_voters"], 1)

    def test_guard_can_prevent_last_hostage_and_game_continues(self):
        self.game.players["stalker"].hostage = True
        self.game.players["civilian"].hostage = True
        self.game.players["civilian2"].hostage = True
        self.game.phase = "night"
        self.game.act("hitman", "hostage", "spy")
        self.game.act("spy", "guard", "spy")
        self.game.tick(self.game.deadline)
        self.assertIsNone(self.game.winner)
        self.assertEqual(self.game.phase, "tribunal")

    def test_hostage_and_execution_reach_vote_control_from_two_free_citizens(self):
        for name in ["stalker", "civilian", "civilian2"]:
            self.game.players[name].hostage = True
        self.game.phase = "night"
        self.game.act("hitman", "hostage", "spy")
        self.game.tick(self.game.deadline)
        self.assertEqual(self.game.winner_reason, "vote_control")
        self.setUp()
        for name in ["stalker", "civilian", "civilian2"]:
            self.game.players[name].hostage = True
        self.game.phase = "tribunal"
        self.game.vote("hitman", "spy")
        self.game.tick(self.game.deadline)
        self.assertEqual(self.game.winner_reason, "vote_control")

    def test_execution_wins_for_all_civilian_roles_including_dead_and_hostage(self):
        self.game.players["spy"].alive = False
        self.game.players["civilian"].hostage = True
        self.game.phase = "tribunal"
        self.game.vote("stalker", "hitman")
        self.game.tick(self.game.deadline)
        self.assertEqual(self.game.winner, "civilians")
        for name in ["spy", "stalker", "civilian"]:
            result = self.game.snapshot(name)["result"]
            self.assertEqual(
                (result["reason"], result["team"], result["outcome"]),
                ("hitman_executed", "civilians", "won"),
            )
        self.assertEqual(self.game.snapshot("hitman")["result"]["outcome"], "lost")

    def test_executing_last_free_civilian_can_give_hitman_victory(self):
        self.game.players["civilian2"].hostage = True
        self.game.players["civilian3"].hostage = True
        self.game.players["spy"].hostage = True
        self.game.players["stalker"].hostage = True
        self.game.phase = "tribunal"
        self.game.vote("hitman", "civilian")
        self.game.tick(self.game.deadline)
        self.assertEqual(self.game.winner_reason, "all_survivors_hostage")

    def test_no_surviving_civilians_has_distinct_reason(self):
        for name in ["spy", "stalker", "civilian2", "civilian3"]:
            self.game.players[name].alive = False
        self.game.phase = "tribunal"
        self.game.vote("hitman", "civilian")
        self.game.tick(self.game.deadline)
        self.assertEqual(self.game.winner_reason, "no_civilians_alive")
        self.assertEqual(self.game.snapshot("hitman")["result"]["civilians_alive"], 0)

    def test_win_after_many_rounds_is_immutable(self):
        self.game.round = 25
        self.game.phase = "tribunal"
        self.game.vote("spy", "hitman")
        self.game.tick(self.game.deadline)
        events = list(self.game.events)
        self.game.check_winner()
        self.game.tick(self.game.deadline + 100)
        self.assertEqual(self.game.winner_reason, "hitman_executed")
        self.assertEqual(events, self.game.events)
        self.assertFalse(self.game.snapshot("spy")["me"]["can_vote"])
        self.assertFalse(self.game.snapshot("spy")["me"]["can_act"])

    def test_no_winner_after_many_rounds_keeps_roles_private(self):
        self.game.round = 25
        self.game.phase = "tribunal"
        self.game.tick(self.game.deadline)
        for viewer in self.game.players:
            view = self.game.snapshot(viewer)
            self.assertIsNone(view["result"])
            self.assertTrue(all("role" not in p for p in view["players"]))
        self.assertIsNone(self.game.winner)
        self.assertEqual((self.game.round, self.game.phase), (26, "day"))

    def test_active_snapshot_keeps_other_hostages_private(self):
        self.game.players["spy"].hostage = True
        self.game.players["stalker"].gagged = True
        for viewer in self.game.players:
            snapshot = self.game.snapshot(viewer)
            self.assertIsNone(snapshot["result"])
            self.assertTrue(all(set(p) == {"name", "alive"} for p in snapshot["players"]))
            self.assertEqual(snapshot["me"]["hostage"], viewer == "spy")
            self.assertEqual(snapshot["me"]["gagged"], viewer == "stalker")


class SingleRoomTests(unittest.TestCase):
    def setUp(self):
        self.rooms = RoomService()
        self.first = self.rooms.create("alice")
        self.other = self.rooms.create("bob")

    def test_no_duplicate_lobby_membership_and_leave_allows_switch(self):
        with self.assertRaises(ValueError):
            self.rooms.create("alice")
        with self.assertRaises(ValueError):
            self.rooms.join(self.other.code, "alice")
        self.assertIs(self.rooms.current("alice"), self.first)
        self.assertIs(self.rooms.join(self.first.code, "alice"), self.first)
        self.rooms.leave(self.first.code, "alice")
        self.assertIs(self.rooms.join(self.other.code, "alice"), self.other)
        self.assertNotIn(self.first.code, self.rooms.rooms)

    def test_finished_room_is_recoverable_until_player_leaves(self):
        self.rooms.set_bot(self.first.code, "alice", True)
        self.rooms.start(self.first.code, "alice")
        hitman = next(p for p in self.first.match.players.values() if p.role == "hitman")
        hitman.alive = False
        self.first.match.check_winner()
        self.assertIsNone(self.rooms.active("alice"))
        self.assertEqual(self.rooms.snapshot(self.rooms.current("alice"))["phase"], "finished")
        with self.assertRaises(ValueError):
            self.rooms.join(self.other.code, "alice")
        self.rooms.leave(self.first.code, "alice")
        self.assertIsNone(self.rooms.current("alice"))
        self.rooms.create("alice")


if __name__ == "__main__":
    unittest.main()

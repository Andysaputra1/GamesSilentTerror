import unittest
from app.services.activity_service import ActivityService
from app.services.match_engine import Match


class PublicVoteTests(unittest.TestCase):
    def test_five_votes_counted_once_with_names_only_during_tribunal(self):
        game = Match(list("abcdef"), [])
        game.phase = "tribunal"
        for voter in "abcde":
            game.vote(voter, "f")
        with self.assertRaises(ValueError):
            game.vote("a", "b")
        for viewer in game.players:
            public = game.snapshot(viewer)
            votes = next(item for item in public["tribunal_votes"] if item["target"] == "f")
            self.assertEqual(votes["voters"], list("abcde"))
            self.assertTrue(
                all(set(p) == {"name", "label", "alive", "skin_id"} for p in public["players"])
            )
        game.phase = "day"
        self.assertEqual(game.snapshot("a")["tribunal_votes"], [])

    def test_gag_can_vote_but_hostage_cannot(self):
        game = Match(list("abcdef"), [])
        game.phase = "tribunal"
        game.players["a"].gagged = True
        game.players["b"].hostage = True
        game.vote("a", "c")
        with self.assertRaises(ValueError):
            game.vote("b", "c")
        self.assertEqual(
            next(
                item["voters"]
                for item in game.snapshot("d")["tribunal_votes"]
                if item["target"] == "c"
            ),
            ["a"],
        )


class ActivityLogTests(unittest.TestCase):
    def test_activity_redacts_nested_secrets_and_bounds_history(self):
        log = ActivityService()
        for index in range(2010):
            log.record(
                "ABC123",
                "test",
                {
                    "index": index,
                    "headers": {"Authorization": "secret"},
                    "password": "secret",
                    "api_key": "secret",
                },
            )
        self.assertEqual(len(log.events), 2000)
        self.assertEqual(len(log.list("ABC123")), 200)
        self.assertEqual(log.list("other"), [])
        params = log.list()[0]["params"]
        self.assertEqual(params["headers"]["Authorization"], "[REDACTED]")
        self.assertEqual(params["password"], "[REDACTED]")
        self.assertEqual(params["api_key"], "[REDACTED]")

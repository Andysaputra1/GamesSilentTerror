"""Layar persiapan: ronde 1 menunggu AI siap, waktu baca minimal, atau semua manusia menekan Siap."""

import unittest

from services.match_engine import PREPARATION_MAX_SECONDS, PREPARATION_MIN_SECONDS, Match


class PreparationTests(unittest.TestCase):
    def setUp(self):
        self.match = Match(["alice", "bob"], ["NOX", "ECHO"], now=0.0, preparing=True)

    def test_timer_does_not_run_and_nothing_is_allowed_while_preparing(self):
        self.assertEqual(self.match.phase, "preparing")
        self.match.tick(PREPARATION_MIN_SECONDS + 5)  # AI belum siap: tetap menunggu
        self.assertEqual(self.match.phase, "preparing")
        self.assertFalse(self.match.can_chat("alice"))
        with self.assertRaises(ValueError):
            self.match.vote("alice", "bob")
        with self.assertRaises(ValueError):
            self.match.act("NOX", "gag", "alice")
        view = self.match.snapshot("alice")
        self.assertFalse(view["me"]["can_act"] or view["me"]["can_vote"])
        self.assertFalse(view["preparation"]["ready"])
        self.assertEqual(view["preparation"]["required"], 2)
        self.assertEqual(view["preparation"]["bots"], 2)

    def test_ai_ready_starts_round_after_minimum_reading_time(self):
        self.match.mark_ai_ready(now=2.0, detail="AI siap: 2 bot.")
        self.assertEqual(self.match.phase, "preparing")  # waktu baca minimal belum lewat
        self.match.tick(PREPARATION_MIN_SECONDS)
        self.assertEqual((self.match.phase, self.match.round), ("day", 1))
        # Timer siang dihitung dari saat mulai, bukan dari saat tombol Start ditekan.
        self.assertEqual(self.match.deadline, PREPARATION_MIN_SECONDS + self.match.durations["day"])
        self.assertIsNone(self.match.snapshot("alice")["preparation"])

    def test_all_humans_ready_skip_the_wait_but_never_skip_the_ai(self):
        self.match.ready_consent("alice", now=1.0)
        self.match.ready_consent("bob", now=1.0)
        self.assertEqual(self.match.phase, "preparing")  # AI belum siap
        self.assertTrue(self.match.snapshot("bob")["preparation"]["consented"])
        self.match.mark_ai_ready(now=3.0)
        self.assertEqual(self.match.phase, "day")
        with self.assertRaises(ValueError):
            self.match.ready_consent("alice")  # hanya saat persiapan

    def test_bots_cannot_press_ready(self):
        with self.assertRaises(ValueError):
            self.match.ready_consent("NOX")

    def test_maximum_wait_starts_with_fallback_bots(self):
        self.match.tick(PREPARATION_MAX_SECONDS)
        self.assertEqual(self.match.phase, "day")
        self.assertIn("cadangan", self.match.events[-1])

    def test_room_without_bots_is_ready_immediately(self):
        match = Match(["a", "b", "c", "d"], [], now=0.0, preparing=True)
        self.assertTrue(match.snapshot("a")["preparation"]["ready"])
        for name in "abcd":
            match.ready_consent(name, now=0.5)
        self.assertEqual(match.phase, "day")

    def test_progress_is_clamped_and_only_while_preparing(self):
        self.match.update_preparation(detail="Memuat IndoBERT…", progress=4)
        self.assertEqual(self.match.snapshot("alice")["preparation"]["progress"], 1.0)
        self.match.begin(now=1.0)
        self.match.update_preparation(detail="tidak berlaku", progress=0.1)
        self.assertIsNone(self.match.preparation.get("ignored"))
        self.assertEqual(self.match.phase, "day")

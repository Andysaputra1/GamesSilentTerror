"""Layar persiapan: ronde 1 menunggu AI siap, minimal sepuluh detik, dan kartu role dibuka."""

import unittest
import unittest.mock

from app.module.match_engine import (
    PREPARATION_MAX_SECONDS,
    PREPARATION_MIN_SECONDS,
    REVEAL_WAIT_SECONDS,
    Match,
)


class PreparationTests(unittest.TestCase):
    def setUp(self):
        self.match = Match(["alice", "bob"], ["NOX", "ECHO"], now=0.0, preparing=True)

    def reveal_all(self, match=None, now=0.5):
        match = match or self.match
        for name in match.unrevealed():
            match.reveal_role(name, now=now)

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
        self.reveal_all()
        self.match.mark_ai_ready(now=2.0, detail="AI siap: 2 bot.")
        self.assertEqual(self.match.phase, "preparing")  # waktu baca minimal belum lewat
        self.match.tick(PREPARATION_MIN_SECONDS)
        self.assertEqual((self.match.phase, self.match.round), ("day", 1))
        # Timer siang dihitung dari saat mulai, bukan dari saat tombol Start ditekan.
        self.assertEqual(self.match.deadline, PREPARATION_MIN_SECONDS + self.match.durations["day"])
        self.assertIsNone(self.match.snapshot("alice")["preparation"])

    def test_all_humans_ready_cannot_skip_ten_seconds_or_ai(self):
        self.reveal_all()
        self.match.ready_consent("alice", now=1.0)
        self.match.ready_consent("bob", now=1.0)
        self.assertEqual(self.match.phase, "preparing")  # AI belum siap
        self.assertTrue(self.match.snapshot("bob")["preparation"]["consented"])
        self.match.mark_ai_ready(now=3.0)
        self.match.tick(9.999)
        self.assertEqual(self.match.phase, "preparing")
        self.match.tick(10.0)
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
        self.reveal_all(match)
        match.tick(9.999)
        self.assertEqual(match.phase, "preparing")
        match.tick(10.0)
        self.assertEqual(match.phase, "day")

    def test_ai_ready_after_minimum_starts_without_an_extra_wait(self):
        self.reveal_all()
        self.match.mark_ai_ready(now=12.0)
        self.assertEqual(self.match.phase, "day")
        self.assertEqual(self.match.deadline, 12.0 + self.match.durations["day"])

    def test_progress_is_clamped_and_only_while_preparing(self):
        self.match.update_preparation(detail="Memuat IndoBERT…", progress=4)
        self.assertEqual(self.match.snapshot("alice")["preparation"]["progress"], 1.0)
        self.match.begin(now=1.0)
        self.match.update_preparation(detail="tidak berlaku", progress=0.1)
        self.assertIsNone(self.match.preparation.get("ignored"))
        self.assertEqual(self.match.phase, "day")

    def test_waits_for_unrevealed_humans_at_most_the_reveal_limit(self):
        self.match.mark_ai_ready(now=2.0)
        self.match.tick(PREPARATION_MIN_SECONDS)
        self.assertEqual(self.match.phase, "preparing")  # belum ada yang membuka kartu
        with unittest.mock.patch("app.module.match_engine.time.time", return_value=12.0):
            view = self.match.snapshot("alice")["preparation"]
        self.assertEqual((view["unrevealed"], view["revealed"], view["elapsed"]), (2, False, 12))
        self.assertEqual(view["starts_in"], PREPARATION_MIN_SECONDS + REVEAL_WAIT_SECONDS - 12)
        self.match.reveal_role("alice", now=12.0)
        self.assertEqual(self.match.phase, "preparing")  # bob masih menutup kartu
        self.match.tick(PREPARATION_MIN_SECONDS + REVEAL_WAIT_SECONDS - 0.001)
        self.assertEqual(self.match.phase, "preparing")
        self.match.tick(PREPARATION_MIN_SECONDS + REVEAL_WAIT_SECONDS)
        self.assertEqual(self.match.phase, "day")
        self.assertNotIn("cadangan", self.match.events[-1])

    def test_last_reveal_after_minimum_starts_at_once(self):
        self.match.mark_ai_ready(now=2.0)
        self.match.reveal_role("alice", now=3.0)
        self.match.tick(13.0)
        self.assertEqual(self.match.phase, "preparing")
        self.match.reveal_role("bob", now=13.5)
        self.assertEqual(self.match.phase, "day")
        self.assertEqual(self.match.deadline, 13.5 + self.match.durations["day"])

    def test_reveal_does_not_skip_minimum_or_ai(self):
        self.reveal_all(now=1.0)
        self.assertTrue(self.match.snapshot("bob")["preparation"]["revealed"])
        self.assertEqual(self.match.snapshot("bob")["preparation"]["unrevealed"], 0)
        self.match.tick(PREPARATION_MIN_SECONDS + 1)
        self.assertEqual(self.match.phase, "preparing")  # AI belum siap

    def test_only_humans_reveal_and_only_while_preparing(self):
        with self.assertRaises(ValueError):
            self.match.reveal_role("NOX")
        self.match.begin(now=1.0)
        with self.assertRaises(ValueError):
            self.match.reveal_role("alice")

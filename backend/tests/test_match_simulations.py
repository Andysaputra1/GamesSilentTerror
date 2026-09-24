"""Simulasi deterministik menguji pertandingan utuh tanpa jaringan/DB/LLM."""

import random
import unittest

from services.match_engine import Match


class MatchSimulationTests(unittest.TestCase):
    def test_complete_matches_preserve_permissions_privacy_and_final_results(self):
        for count in range(4, 11):
            for seed in range(30):
                with self.subTest(players=count, seed=seed):
                    rng = random.Random(seed)
                    game = Match(
                        [f"player-{i}" for i in range(count)],
                        [],
                        quick=bool(seed % 2),
                        now=0,
                        rng=rng,
                    )
                    # Batas loop hanya untuk tes, bukan batas ronde permainan.
                    for _ in range(300):
                        if game.winner:
                            break
                        for name, player in game.players.items():
                            view = game.snapshot(name)
                            me = view["me"]
                            self.assertTrue(
                                all(set(p) == {"name", "alive"} for p in view["players"])
                            )
                            if not player.alive:
                                self.assertFalse(me["can_chat"] or me["can_act"] or me["can_vote"])
                            if player.hostage:
                                self.assertFalse(me["can_chat"] or me["can_vote"])
                            if game.phase == "night" or player.gagged:
                                self.assertFalse(me["can_chat"])
                            if rng.random() < 0.25:
                                continue  # Termasuk peserta yang tidak mengirim pilihan.
                            ability = me["ability"] if me["can_act"] else None
                            if not ability and not me["can_vote"]:
                                continue
                            targets = [
                                p.name
                                for p in game.players.values()
                                if p.alive
                                and (p.name != name or ability == "guard")
                                and not (ability == "guard" and p.name == me["last_guard"])
                            ]
                            if targets:
                                target = rng.choice(targets)
                                if ability:
                                    game.act(name, ability, target)
                                else:
                                    game.vote(name, target)
                        game.tick(game.deadline)
                    self.assertEqual(game.phase, "finished")
                    self.assertIn(game.winner, {"civilians", "hitman"})
                    hitman = next(p for p in game.players.values() if p.role == "hitman")
                    free_citizens = sum(
                        p.alive and not p.hostage and p.role != "hitman"
                        for p in game.players.values()
                    )
                    if game.winner == "civilians":
                        self.assertFalse(hitman.alive)
                    elif game.winner == "hitman":
                        self.assertTrue(hitman.alive)
                        self.assertLessEqual(free_citizens, 1)
                    result = game.result(hitman.name)
                    game.tick(game.deadline + 10000)
                    self.assertEqual(game.result(hitman.name), result)

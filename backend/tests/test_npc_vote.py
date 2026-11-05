"""Vote dan ajak vote otak NPC (Fase 6): kalimat ajak vote, vote paksa, vote Hitman, dan pindah suara saat waktu tambahan."""

import random
import unittest
from types import SimpleNamespace

from app.module.match_engine import Match
from app.module.npc_brain.generated import nlg, otak_fuzzy
from app.module.npc_brain.penjelasan import jelaskan

ENAM = ["hitman", "spy", "stalker", "warga1", "warga2", "warga3"]


# Tribunal ronde 3 dengan role tetap, supaya bukti dan target tidak bergantung pada pembagian acak.
def tribunal():
    game = Match([], ENAM, rng=random.Random(1), now=0.0)
    for nama, pemain in game.players.items():
        pemain.role = nama if not nama.startswith("warga") else "civilian"
    game.round, game.phase = 3, "tribunal"
    game.deadline = float(game.durations["tribunal"])
    return game


class AjakVoteTests(unittest.TestCase):
    # Kalimat khusus ajak vote baru ada di Fase 8, jadi sampai itu templat tuduh harus tetap lolos pemeriksa aturan.
    def test_vote_invitation_plans_pass_the_rule_checker(self):
        for jenis in ("ajak_pindah", "ajak_menyatukan", "jelaskan_vote"):
            with self.subTest(jenis=jenis):
                rencana = {"pembicara": "NOX", "aksi": "tuduh", "jenis": jenis, "intent": "offend",
                           "target": "ECHO", "klaim": False, "bukti": ["ECHO aneh dari tadi."]}  # fmt: skip
                konteks = {"roster": ["NOX", "ECHO", "VEIL"], "chat_terbaru": []}
                hasil = nlg.tulis_pesan(rencana, konteks, None, "santai")
                self.assertEqual(hasil["pelanggaran"], [])
                self.assertIn("ECHO", hasil["teks"])


class VotePaksaTests(unittest.TestCase):
    # Warga bebas tinggal tiga: warga3 tersingkir dan warga2 disandera, jadi warga kritis.
    def langkah_kritis(self, detik):
        game = tribunal()
        game.players["warga3"].alive = False
        game.players["warga2"].hostage, game.players["warga2"].hostage_round = True, 2
        ingatan = otak_fuzzy.Ingatan("warga1")
        view = ingatan.sinkron_snapshot(game.snapshot("warga1"), detik)
        return game, ingatan, view, otak_fuzzy.putuskan(ingatan, view)

    def test_critical_citizen_votes_and_the_engine_accepts_it(self):
        game, _, _, hasil = self.langkah_kritis(60.0)
        rencana = hasil["rencana_vote"]
        self.assertTrue(rencana["paksa"])
        self.assertNotIn(rencana["target"], ("warga2", "warga3", "warga1"))
        game.vote("warga1", hasil["npc_decision"]["target"])
        self.assertEqual(game.votes["warga1"], rencana["target"])

    def test_panel_explains_forced_vote(self):
        _, _, view, hasil = self.langkah_kritis(60.0)
        bot = SimpleNamespace(nama="warga1", metode="fuzzy", persona="santai", peran="civilian", langkah=1)
        p = jelaskan(bot, otak_fuzzy, view, hasil)
        self.assertTrue(p["keputusan"]["vote"]["paksa"])
        self.assertIn("PAKSA_VOTE_KRITIS", p["penalaran"]["vote"]["catatan"])

    def test_early_tribunal_still_waits_even_when_critical(self):
        _, _, _, hasil = self.langkah_kritis(5.0)
        self.assertEqual(hasil["rencana_vote"]["aksi"], "tunggu")
        self.assertNotIn("paksa", hasil["rencana_vote"])


if __name__ == "__main__":
    unittest.main()

"""Vote dan ajak vote otak NPC (Fase 6): kalimat ajak vote, vote paksa, vote Hitman, dan pindah suara saat waktu tambahan."""

import random
import time
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from app.module.match_engine import Match
from app.module.npc_brain.generated import nlg, otak_fuzzy
from app.module.npc_brain.penjelasan import jelaskan
from app.module.npc_service import NPCService, pindahkan_vote
from app.services.room_service import RoomService
from tests.test_npc_brain import runtime_siap

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


class PindahSuaraOtakTests(unittest.TestCase):
    # warga3 pernah vote warga1, jadi menurut warga1 ia lebih dicurigai daripada warga2 yang sudah dipilihnya. Suara warga1 dan spy seri.
    def waktu_tambahan(self, suara_warga1="warga2"):
        game = tribunal()
        ingatan = otak_fuzzy.Ingatan("warga1")
        view = ingatan.sinkron_snapshot(game.snapshot("warga1"), 1.0)
        ingatan.catat_vote(2, "warga3", "warga1")
        game.vote("warga1", suara_warga1)
        ingatan.catat_vote_bot(view, otak_fuzzy.rencana_vote("vote", suara_warga1, ["pilihan awal"]))
        game.vote("spy", "stalker")
        game.npc_decisions = {(3, "tribunal", nama) for nama in ENAM}
        game.tick(game.deadline)
        self.assertTrue(game.tribunal_extra)
        return game, ingatan

    def langkah(self, game, ingatan):
        view = ingatan.sinkron_snapshot(game.snapshot("warga1"), game.deadline - 5)
        return view, otak_fuzzy.putuskan(ingatan, view)

    def test_bot_moves_once_to_a_stronger_target(self):
        game, ingatan = self.waktu_tambahan()
        view, hasil = self.langkah(game, ingatan)
        self.assertEqual(hasil["npc_decision"]["action"], "vote")
        self.assertEqual(hasil["npc_decision"]["target"], "warga3")
        self.assertIs(hasil["npc_decision"]["pindah"], True)
        pindahkan_vote(game, "warga1", hasil["npc_decision"]["target"])
        ingatan.catat_vote_bot(view, hasil["rencana_vote"])
        self.assertEqual(game.votes["warga1"], "warga3")
        self.assertEqual([v["target"] for v in ingatan.vote_bot], ["warga3"])
        self.assertTrue(ingatan.vote_bot[0]["dinilai_ulang"])
        # warga2 kini jauh lebih dicurigai pun, bot tidak pindah lagi: suara hanya pindah sekali.
        ingatan.catat_vote(2, "warga2", "warga1")
        _, hasil = self.langkah(game, ingatan)
        self.assertEqual(hasil["npc_decision"]["action"], "wait")
        self.assertNotIn("pindah", hasil["npc_decision"])

    def test_bot_keeps_its_vote_without_a_stronger_target(self):
        game, ingatan = self.waktu_tambahan("warga3")
        _, hasil = self.langkah(game, ingatan)
        self.assertEqual(hasil["npc_decision"]["action"], "wait")
        self.assertNotIn("pindah", hasil["npc_decision"])
        self.assertEqual(game.votes["warga1"], "warga3")
        self.assertFalse(ingatan.vote_bot[0]["dinilai_ulang"])

    def test_panel_explains_a_moved_vote(self):
        game, ingatan = self.waktu_tambahan()
        view, hasil = self.langkah(game, ingatan)
        bot = SimpleNamespace(nama="warga1", metode="fuzzy", persona="santai", peran="civilian", langkah=1)
        p = jelaskan(bot, otak_fuzzy, view, hasil)
        self.assertTrue(p["keputusan"]["vote"]["pindah"])
        self.assertIn("dipindah", p["penalaran"]["vote"]["catatan"])


class PindahkanVoteTests(unittest.TestCase):
    def test_vote_moves_to_the_new_target(self):
        game = tribunal()
        game.vote("warga1", "warga2")
        pindahkan_vote(game, "warga1", "warga3")
        self.assertEqual(game.votes["warga1"], "warga3")

    def test_failed_cancel_changes_nothing(self):
        game = tribunal()
        with self.assertRaises(ValueError):
            pindahkan_vote(game, "warga1", "warga3")
        self.assertNotIn("warga1", game.votes)

    def test_rejected_new_vote_restores_the_old_vote(self):
        game = tribunal()
        game.vote("warga1", "warga2")
        game.players["warga3"].alive = False
        with self.assertRaises(ValueError):
            pindahkan_vote(game, "warga1", "warga3")
        self.assertEqual(game.votes["warga1"], "warga2")


class KirimPindahTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.runtime = runtime_siap()
        self.rooms = RoomService()
        self.room = self.rooms.create("human")
        self.rooms.set_bot(self.room.code, "human", True)
        self.rooms.start(self.room.code, "human")
        self.match = self.room.match
        self.service = NPCService(Mock(emit=AsyncMock()), runtime=self.runtime)
        self.enterContext(patch("app.module.npc_service.room_service", self.rooms))
        self.enterContext(patch("app.module.npc_service.PersistenceService"))
        self.enterContext(patch("app.module.npc_service.survey_service"))
        await self.service.prepare(self.room.code, self.match)
        self.match.begin()
        self.match.round, self.match.phase = 2, "tribunal"
        self.match.deadline = time.time() + 60
        self.otak = self.runtime.otak_bot(self.match.id, "NOX")
        self.match.vote("NOX", "human")
        self.otak.ingatan.vote_bot.append({"ronde": 2, "target": "human", "alasan": ["lama"], "dinilai_ulang": False})

    async def asyncTearDown(self):
        await self.service.close()
        self.runtime.tutup()

    def kirim(self, target):
        keputusan = {"npc_decision": {"action": "vote", "target": target, "message": "", "pindah": True},
                     "rencana_vote": {"aksi": "vote", "target": target, "alasan": ["baru"], "pindah": True}}  # fmt: skip
        return self.service._kirim_vote_atau_aksi(
            self.room.code, self.match, (self.match.id, 2, "tribunal"), self.otak, {"ronde": 2}, keputusan
        )

    async def test_moved_vote_reaches_the_engine_and_the_memory(self):
        self.assertEqual(self.kirim("ECHO"), (True, None))
        self.assertEqual(self.match.votes["NOX"], "ECHO")
        self.assertEqual(self.otak.ingatan.vote_bot[0]["target"], "ECHO")
        self.assertTrue(self.otak.ingatan.vote_bot[0]["dinilai_ulang"])

    async def test_rejected_move_keeps_the_old_vote_and_memory(self):
        self.match.players["ECHO"].alive = False
        berlaku, penolakan = self.kirim("ECHO")
        self.assertTrue(berlaku)
        self.assertIsNotNone(penolakan)
        self.assertEqual(self.match.votes["NOX"], "human")
        self.assertEqual(self.otak.ingatan.vote_bot[0]["target"], "human")
        self.assertFalse(self.otak.ingatan.vote_bot[0]["dinilai_ulang"])


if __name__ == "__main__":
    unittest.main()

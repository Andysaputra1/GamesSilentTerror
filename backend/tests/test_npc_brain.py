"""Otak NPC hasil ekspor notebook: multi-bot melawan engine asli, NPCService, dan kesesuaian dengan notebook.

NLU memakai pengganti deterministik (tanpa IndoBERT) agar test cepat dan tidak butuh model.
"""

import asyncio
import json
import random
import re
import time
import unittest
from unittest.mock import AsyncMock, Mock, patch

from services.match_engine import Match
from services.npc_brain.runtime import BrainRuntime, NLUBersama, NLUCadangan
from services.npc_service import NPCService
from services.room_service import RoomService

AKSI_RAHASIA = {"gag", "hostage", "guard", "peek"}


class AnalisisKataKunci:
    """Pengganti SVM: label lama dari kata kunci supaya NLU cadangan bisa dipakai di test."""

    def predict_intent(self, teks):
        kecil = teks.casefold()
        if re.search(r"bukan hitman|jangan vote|jangan buru|disandera|percaya", kecil):
            return "defending"
        if re.search(r"curiga|hitman|vote|mencurigakan", kecil):
            return "accusing"
        return "neutral"


def runtime_siap(metode="campuran"):
    runtime = BrainRuntime()
    runtime.konfigurasi.metode = metode
    runtime.konfigurasi.penulis = "templat"
    runtime.muat_sekarang(nlu=NLUBersama(NLUCadangan(AnalisisKataKunci()), "cadangan"))
    return runtime


class BrainRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runtime = runtime_siap()

    @classmethod
    def tearDownClass(cls):
        cls.runtime.tutup()

    def test_modules_loaded_and_mixed_methods_with_distinct_personas(self):
        self.assertTrue(self.runtime.ringkasan()["siap"])
        match = Match(["human"], ["NOX", "ECHO", "VEIL", "RAVEN", "ASH"], now=0.0)
        rows = self.runtime.siapkan_pertandingan(match, "ROOM01")
        self.assertEqual({r["bot_name"] for r in rows}, {"NOX", "ECHO", "VEIL", "RAVEN", "ASH"})
        self.assertEqual({r["method"] for r in rows}, {"fuzzy", "utility", "bt"})
        tiga_pertama = [r["persona"] for r in sorted(rows, key=lambda r: r["bot_name"])][:3]
        self.assertEqual(len(set(tiga_pertama)), 3)
        self.assertEqual(self.runtime.siapkan_pertandingan(match, "ROOM01"), [])  # sekali saja
        self.runtime.lupakan_kecuali(set())
        self.assertIsNone(self.runtime.otak_bot(match.id, "NOX"))

    def test_bots_do_not_echo_each_others_sentences(self):
        match = Match(["human"], ["NOX", "ECHO", "VEIL"], now=0.0)
        self.runtime.siapkan_pertandingan(match, "ROOM02")
        nox = self.runtime.otak_bot(match.id, "NOX")
        echo = self.runtime.otak_bot(match.id, "ECHO")
        rencana = {"pembicara": "NOX", "aksi": "tanya_info", "intent": "neutral", "target": None,
                   "klaim": False, "bukti": []}  # fmt: skip
        konteks = {"roster": ["human", "NOX", "ECHO", "VEIL"], "chat_terbaru": []}
        pertama = self.runtime.tulis(nox, rencana, konteks)["teks"]
        konteks["chat_terbaru"].append(
            {"pengirim": "NOX", "teks": pertama, "intent": "neutral", "target": []}
        )
        kedua = self.runtime.tulis(echo, {**rencana, "pembicara": "ECHO"}, konteks)["teks"]
        dasar = self.runtime.nlg.bentuk_dasar
        self.assertNotEqual(dasar(pertama), dasar(kedua))

    def test_shared_nlu_passes_roster_for_name_normalization_and_memoizes(self):
        # IndoBERT mengganti nama pemain (nama pengguna bebas) sebelum membaca intent; roster wajib diteruskan.
        model = Mock()
        model.intent.return_value = ("offend", 0.9)
        nlu = NLUBersama(model, "palsu")
        for _ in range(2):
            self.assertEqual(
                nlu.intent("Gw curiga sama tester.", ["tester", "NOX"]), ("offend", 0.9)
            )
        model.intent.assert_called_once_with("Gw curiga sama tester.", ("tester", "NOX"))

    def test_loaded_runtime_is_not_reloaded_in_background(self):
        # prepare() selalu memanggil mulai_memuat(); NLU yang sedang dipakai tidak boleh tertukar.
        nlu = self.runtime.nlu
        self.runtime.mulai_memuat()
        self.assertIsNone(self.runtime._thread)
        self.assertIs(self.runtime.nlu, nlu)

    def test_invalid_panel_values_are_rejected(self):
        with self.assertRaises(ValueError):
            self.runtime.atur(metode="acak")
        with self.assertRaises(ValueError):
            self.runtime.atur(penulis="gpt")

    # Satu pertandingan penuh: semua peserta bot memakai otak, keputusan diterapkan ke engine asli.
    def main_game(self, seed, jumlah=6, langkah=3):
        nama = ["NOX", "ECHO", "VEIL", "RAVEN", "ASH", "DUSK", "IRIS", "SAGE", "ONYX", "LARK"][
            :jumlah
        ]
        match = Match([], nama, rng=random.Random(seed), now=0.0)
        match.npc_decisions = set()
        self.runtime.siapkan_pertandingan(match, f"SIM{seed}")
        catatan = {"ilegal": 0, "chat": [], "langgar": 0}
        t = 0.0
        while not match.winner and match.round <= 15:
            ronde, fase, durasi = match.round, match.phase, match.durations[match.phase]
            for k in range(1, langkah + 1):
                waktu = t + durasi * k / (langkah + 1)
                for bot in sorted(match.players):
                    otak = self.runtime.otak_bot(match.id, bot)
                    if not match.players[bot].alive or match.winner:
                        continue
                    view, hasil, konteks = self.runtime.langkah(otak, match.snapshot(bot), waktu)
                    match.npc_decisions.add((ronde, fase, bot))
                    npc = hasil["npc_decision"]
                    try:
                        if hasil["nlg"] is not None:
                            tulisan = self.runtime.tulis(otak, hasil["nlg"], konteks)
                            if not match.can_chat(bot):
                                raise ValueError("chat tanpa izin")
                            match.add_message(bot, tulisan["teks"])
                            self.runtime.catat_chat(
                                otak, view, hasil["rencana_chat"], tulisan["teks"]
                            )
                            catatan["chat"].append((bot, tulisan))
                            catatan["langgar"] += bool(tulisan["pelanggaran"])
                        if npc["action"] == "vote":
                            match.vote(bot, npc["target"])
                        elif npc["action"] in AKSI_RAHASIA:
                            match.act(bot, npc["action"], npc["target"])
                            self.runtime.catat_aksi(otak, ronde, npc["action"], npc["target"])
                    except ValueError:
                        catatan["ilegal"] += 1
            t += durasi
            match.tick(t)
        return match, catatan

    def test_multi_bot_games_are_legal_and_chats_are_safe(self):
        for seed, jumlah in [(1, 6), (2, 8), (3, 5)]:
            match, catatan = self.main_game(seed, jumlah)
            self.assertEqual(catatan["ilegal"], 0, f"seed {seed}")
            self.assertEqual(catatan["langgar"], 0, f"seed {seed}")
            self.assertTrue(catatan["chat"], "bot harus berbicara")
            for bot, tulisan in catatan["chat"]:
                teks = tulisan["teks"].casefold()
                self.assertTrue(0 < len(tulisan["teks"]) <= 220)
                self.assertNotRegex(teks, r"\b(?:bot|ai|prompt|npc)\b")
                if match.players[bot].role == "hitman":
                    self.assertNotRegex(teks, r"\b(?:aku|saya|gw)\s+(?:ini\s+)?hitman\b")
                    self.assertNotRegex(
                        teks, r"\b(?:aku|saya|gw)\s+(?:sudah\s+)?(?:menyandera|sandera|gag)\b"
                    )
            # Ingatan terpisah: catatan chat setiap bot hanya berisi chat miliknya sendiri.
            for bot, otak in self.runtime.pertandingan[match.id].items():
                jumlah_chat = sum(b == bot for b, _ in catatan["chat"])
                self.assertEqual(len(otak.ingatan.aksi_bot), jumlah_chat)
                self.assertEqual(len(otak.riwayat), jumlah_chat)


class NPCServiceBrainTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        # Behavior tree: bela diri adalah cabang prioritas saat dituduh, jadi hasilnya deterministik.
        self.runtime = runtime_siap("bt")
        self.rooms = RoomService()
        self.room = self.rooms.create("human")
        self.rooms.set_bot(self.room.code, "human", True)
        self.rooms.start(self.room.code, "human")
        self.match = self.room.match
        self.sio = Mock(emit=AsyncMock())
        self.service = NPCService(self.sio, runtime=self.runtime)
        self.enterContext(patch("services.npc_service.room_service", self.rooms))
        self.persistence = self.enterContext(
            patch("services.npc_service.PersistenceService")
        ).return_value
        self.survey = self.enterContext(patch("services.npc_service.survey_service"))

    async def asyncTearDown(self):
        await self.service.close()
        self.runtime.tutup()

    async def test_preparation_assigns_brains_records_methods_and_opens_round(self):
        await self.service.prepare(self.room.code, self.match)
        self.assertTrue(self.match.preparation["ready"])
        self.assertIn("AI siap", self.match.preparation["detail"])
        rows = self.survey.record_match_bots.call_args.args[0]
        self.assertEqual(len(rows), 5)
        self.match.tick(self.match.preparation["min_until"])
        self.assertEqual(self.match.phase, "day")

    async def test_brains_join_late_when_round_started_before_ai_was_ready(self):
        self.match.tick(self.match.deadline)  # batas tunggu habis: ronde 1 mulai dengan cadangan
        self.assertEqual(self.match.phase, "day")
        await self.service.prepare(self.room.code, self.match)
        self.assertIsNotNone(self.runtime.otak_bot(self.match.id, "NOX"))
        self.assertEqual(self.match.phase, "day")

    async def test_bot_defends_itself_after_accusation_and_holds_its_phase(self):
        await self.service.prepare(self.room.code, self.match)
        self.match.begin()
        otak = self.runtime.otak_bot(self.match.id, "NOX")
        with self.rooms.lock:
            self.match.add_message("human", "Aku curiga NOX, dia Hitman. Ayo vote NOX!")
        self.match.deadline = time.time() + 60
        with patch("services.npc_service.asyncio.sleep", AsyncMock()):
            otak.sibuk = True
            await self.service.brain_turn(self.room.code, self.match, otak)
        self.assertFalse(otak.sibuk)
        self.assertIn((1, "day", "NOX"), self.match.npc_decisions)
        self.assertEqual(self.match.messages[-1]["sender"], "NOX")
        self.persistence.record_bot_message.assert_called_once()
        self.sio.emit.assert_awaited_once()
        self.assertEqual(otak.riwayat, [self.match.messages[-1]["message"]])

    async def test_stale_decision_is_not_applied(self):
        await self.service.prepare(self.room.code, self.match)
        self.match.begin()
        otak = self.runtime.otak_bot(self.match.id, "NOX")
        npc = {"action": "vote", "target": "human", "message": ""}
        self.match.phase = "tribunal"
        stale_key = (self.match.id, self.match.round, "day")
        berlaku, penolakan = self.service._terapkan_aksi(
            self.room.code, self.match, stale_key, otak, npc
        )
        self.assertEqual((berlaku, penolakan), (False, None))
        self.assertEqual(self.match.votes, {})

    async def test_floor_allows_one_bot_and_drops_plans_older_than_another_bots_chat(self):
        await self.service.prepare(self.room.code, self.match)
        self.match.begin()
        nox = self.runtime.otak_bot(self.match.id, "NOX")
        self.service.lantai[self.match.id] = "ECHO"
        self.assertFalse(self.service._ambil_lantai(self.match, nox, None))  # ECHO sedang mengetik
        del self.service.lantai[self.match.id]
        with self.rooms.lock:
            terlihat = self.match.add_message("human", "Halo semua.")["id"]
            self.match.add_message("human", "Ada yang curiga?")
        # Chat manusia sesudah snapshot tidak membatalkan rencana; chat bot lain membatalkannya.
        self.assertTrue(self.service._ambil_lantai(self.match, nox, terlihat))
        self.assertEqual(self.service.lantai, {self.match.id: "NOX"})
        del self.service.lantai[self.match.id]
        with self.rooms.lock:
            self.match.add_message("ECHO", "Aku belum yakin.")
        self.assertFalse(self.service._ambil_lantai(self.match, nox, terlihat))

    async def test_concurrent_bots_do_not_talk_over_each_other(self):
        await self.service.prepare(self.room.code, self.match)
        self.match.begin()
        with self.rooms.lock:
            self.match.add_message("human", "NOX dan ECHO mencurigakan, kalian Hitman. Vote NOX!")
        self.match.deadline = time.time() + 60
        nox, echo = (self.runtime.otak_bot(self.match.id, nama) for nama in ("NOX", "ECHO"))
        with patch("services.npc_service.asyncio.sleep", AsyncMock()):
            nox.sibuk = echo.sibuk = True
            await asyncio.gather(
                self.service.brain_turn(self.room.code, self.match, nox),
                self.service.brain_turn(self.room.code, self.match, echo),
            )
            pengirim = [m["sender"] for m in self.match.messages[1:]]
            self.assertEqual(len(pengirim), 1, "hanya satu bot yang boleh bicara pada satu waktu")
            self.assertEqual(self.service.lantai, {})
            # Bot yang tertunda bicara di langkah berikutnya, setelah membaca chat bot pertama.
            kedua = echo if pengirim == ["NOX"] else nox
            kedua.sibuk = True
            await self.service.brain_turn(self.room.code, self.match, kedua)
        self.assertEqual([m["sender"] for m in self.match.messages[1:]], pengirim + [kedua.nama])

    async def test_scheduler_runs_brain_steps_for_every_live_bot(self):
        await self.service.prepare(self.room.code, self.match)
        self.match.begin(now=time.time() - 30)
        with patch("services.npc_service.asyncio.sleep", AsyncMock()):
            self.service.schedule()
            self.service.schedule()  # bot yang sibuk tidak dijadwalkan dua kali
            await asyncio.gather(*list(self.service.tasks))
        langkah = {nama: o.langkah for nama, o in self.runtime.pertandingan[self.match.id].items()}
        self.assertEqual(langkah, {nama: 1 for nama in langkah})


class ExportFreshnessTests(unittest.TestCase):
    def test_generated_modules_match_notebooks_when_available(self):
        from pathlib import Path

        from scripts.ekspor_otak_npc import DEFAULT_NOTEBOOK_DIR, TUJUAN, sidik_notebook

        tercatat = {
            b["modul"]: b["sidik"] for b in json.loads((TUJUAN / "SUMBER.json").read_text())
        }
        self.assertEqual(set(tercatat), {"otak_fuzzy", "otak_utility", "otak_bt", "nlg"})
        if not Path(DEFAULT_NOTEBOOK_DIR, "npc_fuzzy.ipynb").is_file():
            self.skipTest("Notebook skripsi tidak tersedia di mesin ini.")
        self.assertEqual(sidik_notebook(DEFAULT_NOTEBOOK_DIR), tercatat,
                         "Notebook berubah: jalankan scripts/ekspor_otak_npc.py")  # fmt: skip

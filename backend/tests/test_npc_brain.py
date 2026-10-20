"""Otak NPC hasil ekspor notebook: multi-bot melawan engine asli, NPCService, dan kesesuaian dengan notebook.

NLU memakai pengganti deterministik (tanpa IndoBERT) agar test cepat dan tidak butuh model.
"""

import asyncio
import contextlib
import json
import random
import re
import time
import unittest
from unittest.mock import AsyncMock, Mock, patch

from services.match_engine import Match
from services.npc_brain.runtime import BrainRuntime, NLUBersama, NLUCadangan
from services.npc_service import LANTAI_MAKS, NPCService, catat_nlu
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

    def test_baca_chat_adds_neutral_targets_from_the_name_rule(self):
        # NLU cadangan tidak memberi target untuk pesan neutral; aturan nama di anotasi_chat yang memberinya.
        roster = ["human", "NOX", "ECHO", "VEIL"]
        sapa = self.runtime.baca_chat([], "human", "Vei, kamu semalam ngapain?", roster)
        self.assertEqual(sapa["intent"], "neutral")
        self.assertEqual(
            sapa["target"],
            [{"pemain": "VEIL", "relasi": "neutral", "prob": None, "sumber": ["nama"]}],
        )
        semua = self.runtime.baca_chat([], "human", "Ada yang tau sisa waktu?", roster)
        self.assertEqual(semua["target"], [])
        # Aturan nama tidak pernah membuat target offend/defend: tuduhan tetap dari NLU (sumber cadangan).
        tuduh = self.runtime.baca_chat([], "human", "Aku curiga NOX, vote NOX.", roster)
        self.assertEqual(
            [(t["pemain"], t["relasi"], t["sumber"]) for t in tuduh["target"]],
            [("NOX", "offend", ["cadangan"])],
        )

    # Riwayat panel menyimpan chat yang ikut dibaca sebagai konteks: 12 terakhir, urut kronologis.
    def test_baca_chat_keeps_at_most_twelve_previous_chats_as_context(self):
        roster, riwayat = ["human", "NOX", "ECHO", "VEIL"], []
        for i in range(14):
            self.runtime.baca_chat(riwayat, "human", f"Chat ke-{i}, aku curiga NOX.", roster)
        hasil = self.runtime.baca_chat(riwayat, "ECHO", "Aku bukan Hitman.", roster)
        self.assertEqual([c["teks"] for c in hasil["konteks"]],
                         [f"Chat ke-{i}, aku curiga NOX." for i in range(2, 14)])  # fmt: skip
        self.assertEqual(hasil["konteks"][-1]["intent"], "offend")
        self.assertEqual(hasil["konteks"][-1]["target"], [{"pemain": "NOX", "relasi": "offend"}])
        self.assertEqual(hasil["daftar_pemain"], roster)
        self.assertEqual(self.runtime.baca_chat([], "human", "Halo.", roster)["konteks"], [])

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
        # 10 bot: komposisi terbesar memakai lebih dari satu Hitman (Syndicate) dan dua Spy.
        for seed, jumlah in [(1, 6), (2, 8), (3, 5), (4, 10)]:
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

    # Label metode (BT/UA/FL) harus jujur: setiap keputusan chat/vote/aksi bot dihitung oleh modul metodenya
    # sendiri, dan fungsi keputusan modul metode lain tidak pernah dipanggil untuk bot itu.
    def test_each_bot_is_decided_only_by_its_labelled_method(self):
        dipanggil = {}
        with contextlib.ExitStack() as tumpukan:
            for metode, modul in self.runtime.modul.items():
                for nama_fungsi in ("keputusan_chat", "keputusan_vote", "keputusan_aksi"):

                    def rekam(ctx, *args, _asli=getattr(modul, nama_fungsi), _metode=metode):
                        dipanggil.setdefault(ctx["bot"], set()).add(_metode)
                        return _asli(ctx, *args)

                    tumpukan.enter_context(patch.object(modul, nama_fungsi, rekam))
            match, _ = self.main_game(seed=11, jumlah=9)
        label = {b: o.metode for b, o in self.runtime.pertandingan[match.id].items()}
        self.assertEqual(set(label.values()), {"fuzzy", "utility", "bt"})
        self.assertEqual(dipanggil, {bot: {metode} for bot, metode in label.items()})


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
        # Label metode di game = metode yang tercatat untuk survei = otak yang dipasang ke bot.
        otak = {b: self.runtime.otak_bot(self.match.id, b).metode for b in self.match.bot_methods}
        self.assertEqual(self.match.bot_methods, {r["bot_name"]: r["method"] for r in rows})
        self.assertEqual(self.match.bot_methods, otak)
        tampil = {p["name"]: p.get("metode") for p in self.match.snapshot("human")["players"]}
        self.assertEqual(tampil, {"human": None, **otak})
        self.match.reveal_role("human", now=self.match.preparation["started_at"])
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

    async def test_floor_lets_bots_write_in_parallel_without_twin_or_stale_plans(self):
        await self.service.prepare(self.room.code, self.match)
        self.match.begin()
        nox = self.runtime.otak_bot(self.match.id, "NOX")
        tuduh_ash = {"intent": "offend", "target": "ASH"}
        # Lantai penuh (LANTAI_MAKS bot sedang menulis) dan rencana kembar ditolak.
        penuh = {f"B{i}": ("neutral", f"P{i}") for i in range(LANTAI_MAKS)}
        self.service.lantai[self.match.id] = penuh
        self.assertFalse(self.service._ambil_lantai(self.match, nox, None, tuduh_ash))
        self.service.lantai[self.match.id] = {"ECHO": ("offend", "ASH")}
        self.assertFalse(self.service._ambil_lantai(self.match, nox, None, tuduh_ash))
        # Rencana berbeda boleh ditulis bersamaan; chat manusia sesudah snapshot tidak membatalkannya.
        with self.rooms.lock:
            terlihat = self.match.add_message("human", "Halo semua.")["id"]
            self.match.add_message("human", "Ada yang curiga?")
        bela_ash = {"intent": "defend", "target": "ASH"}
        self.assertTrue(self.service._ambil_lantai(self.match, nox, terlihat, bela_ash))
        self.assertEqual(
            self.service.lantai[self.match.id],
            {"ECHO": ("offend", "ASH"), "NOX": ("defend", "ASH")},
        )
        # Pemain melihat awan berpikir pada bot yang sedang menyusun kalimat.
        berpikir = [p["name"] for p in self.match.snapshot("human")["players"] if p.get("thinking")]
        self.assertEqual(berpikir, ["NOX"])
        # Chat bot lain yang masuk sesudah snapshot membatalkan rencana lama.
        self.service.lantai.clear()
        self.match.bot_berpikir.clear()
        with self.rooms.lock:
            self.match.add_message("ECHO", "Aku belum yakin.")
        self.assertFalse(self.service._ambil_lantai(self.match, nox, terlihat, bela_ash))

    async def test_accused_bots_defend_themselves_in_parallel(self):
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
        # Rencana berbeda (masing-masing membela diri): keduanya menulis bersamaan, tidak ada yang ditunda.
        pengirim = sorted(m["sender"] for m in self.match.messages[1:])
        self.assertEqual(pengirim, ["ECHO", "NOX"])
        self.assertEqual(self.service.lantai, {})
        self.assertEqual(self.match.bot_berpikir, set())  # awan hilang setelah kalimat terkirim

    async def test_scheduler_runs_brain_steps_for_every_live_bot(self):
        await self.service.prepare(self.room.code, self.match)
        self.match.begin(now=time.time() - 30)
        with patch("services.npc_service.asyncio.sleep", AsyncMock()):
            self.service.schedule()
            self.service.schedule()  # bot yang sibuk tidak dijadwalkan dua kali
            await asyncio.gather(*list(self.service.tasks))
        langkah = {nama: o.langkah for nama, o in self.runtime.pertandingan[self.match.id].items()}
        self.assertEqual(langkah, {nama: 1 for nama in langkah})

    async def test_called_or_accused_bot_steps_promptly_and_answers_once(self):
        await self.service.prepare(self.room.code, self.match)
        self.match.begin(now=time.time() - 30)
        self.match.deadline = time.time() + 60
        otak = {
            nama: self.runtime.otak_bot(self.match.id, nama) for nama in ("NOX", "ECHO", "VEIL")
        }
        sekarang = time.time()
        for o in otak.values():
            o.langkah_terakhir = sekarang - 1.5  # di bawah NPC_STEP_SECONDS (3 detik)
        with self.rooms.lock:
            self.match.add_message("human", "Nox, kamu semalam ngapain?")
        # Bacaan NLU chat baru (yang sama dengan bacaan bot) memicu langkah segera bot yang dipanggil/dituduh.
        await catat_nlu(self.match, "human", "Nox, kamu semalam ngapain?", runtime=self.runtime)
        await catat_nlu(self.match, "human", "Aku curiga ECHO, dia Hitman.", runtime=self.runtime)
        self.assertEqual(
            {n: o.segera for n, o in otak.items()}, {"NOX": True, "ECHO": True, "VEIL": False}
        )
        elapsed = self.match.durations["day"] - (self.match.deadline - sekarang)
        self.assertTrue(self.service._due(otak["NOX"], self.match, elapsed, sekarang, 0))
        self.assertFalse(self.service._due(otak["VEIL"], self.match, elapsed, sekarang, 0))
        # Batas laju tetap ada: langkah segera minimal JEDA_SEGERA_DETIK sesudah langkah terakhir.
        otak["NOX"].langkah_terakhir = sekarang - 0.5
        self.assertFalse(self.service._due(otak["NOX"], self.match, elapsed, sekarang, 0))
        with patch("services.npc_service.asyncio.sleep", AsyncMock()):
            otak["NOX"].sibuk = True
            await self.service.brain_turn(self.room.code, self.match, otak["NOX"])
            self.assertFalse(otak["NOX"].segera)
            self.assertEqual(self.match.messages[-1]["sender"], "NOX")
            self.assertEqual(otak["NOX"].ingatan.aksi_bot[-1]["aksi"], "jawab")
            # Panggilan yang sudah dijawab tidak dijawab lagi pada langkah berikutnya.
            otak["NOX"].sibuk = True
            await self.service.brain_turn(self.room.code, self.match, otak["NOX"])
        self.assertEqual([a["aksi"] for a in otak["NOX"].ingatan.aksi_bot].count("jawab"), 1)


class ExportFreshnessTests(unittest.TestCase):
    def test_generated_modules_match_notebooks_when_available(self):
        from pathlib import Path

        from scripts.ekspor_otak_npc import DEFAULT_NOTEBOOK_DIR, TUJUAN, sidik_notebook

        tercatat = {
            b["modul"]: b["sidik"] for b in json.loads((TUJUAN / "SUMBER.json").read_text())
        }
        self.assertEqual(set(tercatat), {"otak_fuzzy", "otak_utility", "otak_bt", "nlg"})
        # Kepala tiap modul harus cocok dengan SUMBER.json: ekspor parsial atau edit manual ketahuan
        # walau notebook skripsi tidak tersedia di mesin ini.
        for modul, sidik in tercatat.items():
            kepala = (TUJUAN / f"{modul}.py").read_text(encoding="utf-8")[:600]
            self.assertIn(f"Sidik  : {sidik}", kepala,
                          f"{modul}.py tidak sama dengan SUMBER.json: ekspor ulang semua modul")  # fmt: skip
        if not Path(DEFAULT_NOTEBOOK_DIR, "npc_fuzzy.ipynb").is_file():
            self.skipTest("Notebook skripsi tidak tersedia di mesin ini.")
        self.assertEqual(sidik_notebook(DEFAULT_NOTEBOOK_DIR), tercatat,
                         "Notebook berubah: jalankan scripts/ekspor_otak_npc.py")  # fmt: skip

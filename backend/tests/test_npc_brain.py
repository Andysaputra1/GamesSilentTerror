"""Otak NPC hasil ekspor notebook: multi-bot melawan engine asli, NPCService, dan kesesuaian dengan notebook.

NLU memakai pengganti deterministik (tanpa IndoBERT) agar test cepat dan tidak butuh model.
"""

import asyncio
import contextlib
import json
import random
import time
import unittest
from unittest.mock import AsyncMock, Mock, patch

from app.module.match_engine import Match
from app.module.npc_brain.runtime import BrainRuntime, NLUBersama
from app.module.npc_service import LANTAI_MAKS, NPCService, catat_nlu
from app.module.persistence_service import PersistenceError
from app.module.room_service import RoomService
from tests.nlu_palsu import NLUPalsu

AKSI_RAHASIA = {"gag", "hostage", "guard", "peek"}


def runtime_siap():
    runtime = BrainRuntime()
    runtime.konfigurasi.penulis = "templat"
    pola_offend = r"curiga|hitman|vote|mencurigakan"
    pola_defend = r"bukan hitman|jangan vote|jangan buru|disandera|percaya"
    runtime.muat_sekarang(nlu=NLUBersama(NLUPalsu(pola_offend, pola_defend), "cadangan"))
    return runtime


class BrainRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runtime = runtime_siap()

    @classmethod
    def tearDownClass(cls):
        cls.runtime.tutup()

    def test_modules_loaded_and_all_bots_fuzzy_with_distinct_personas(self):
        self.assertTrue(self.runtime.ringkasan()["siap"])
        match = Match(["human"], ["NOX", "ECHO", "VEIL", "RAVEN", "ASH"], now=0.0)
        rows = self.runtime.siapkan_pertandingan(match, "ROOM01")
        self.assertEqual({r["bot_name"] for r in rows}, {"NOX", "ECHO", "VEIL", "RAVEN", "ASH"})
        self.assertEqual({r["method"] for r in rows}, {"fuzzy"})
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
        # NLU palsu tidak memberi target untuk pesan neutral; aturan nama di anotasi_chat yang memberinya.
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

    # Konteks NLG dari langkah: 12 chat terakhir dan suara Tribunal. Prompt menampilkan tuduhan dan suara ke bot
    # sebagai pemicu, dan tidak lagi memuat contoh kalimat templat.
    def test_nlg_context_carries_trigger_chat_and_tribunal_votes(self):
        match = Match(["human"], ["NOX", "ECHO", "VEIL"], rng=random.Random(1), now=0.0)
        self.runtime.siapkan_pertandingan(match, "ROOM03")
        match.round, match.phase = 2, "tribunal"
        match.deadline = 10.0 + match.durations["tribunal"]
        match.votes = {"human": "NOX"}
        for i in range(14):
            match.add_message("ECHO", f"Obrolan ke-{i}.", now=5.0)
        match.add_message("human", "Aku curiga NOX, vote NOX.", now=9.0)
        otak = self.runtime.otak_bot(match.id, "NOX")
        _, _, konteks = self.runtime.langkah(otak, match.snapshot("NOX"), 10.0)
        self.assertEqual(len(konteks["chat_terbaru"]), 12)
        self.assertEqual(konteks["suara_tribunal"], {"human": "NOX"})
        bela = {"pembicara": "NOX", "aksi": "bela_diri", "intent": "defend", "target": "NOX",
                "klaim": False, "bukti": ["Aku bukan Hitman; tuduhan ke aku belum punya bukti."]}  # fmt: skip
        _, pesan = self.runtime.nlg.buat_prompt(bela, konteks, "santai")
        self.assertIn("<pemicu>\nhuman: Aku curiga NOX, vote NOX.", pesan)
        self.assertIn("Suara Tribunal ke NOX saat ini: human", pesan)
        self.assertNotIn("Contoh", pesan)

    def test_loaded_runtime_is_not_reloaded_in_background(self):
        # prepare() selalu memanggil mulai_memuat(); NLU yang sedang dipakai tidak boleh tertukar.
        nlu = self.runtime.nlu
        self.runtime.mulai_memuat()
        self.assertIsNone(self.runtime._thread)
        self.assertIs(self.runtime.nlu, nlu)

    def test_invalid_panel_values_are_rejected(self):
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
                            match.add_message(bot, tulisan["teks"], now=waktu)
                            self.runtime.catat_chat(
                                otak, view, hasil["rencana_chat"], tulisan["teks"]
                            )
                            catatan["chat"].append((bot, tulisan))
                            catatan["langgar"] += bool(tulisan["pelanggaran"])
                        if npc["action"] == "vote":
                            match.vote(bot, npc["target"])
                            self.runtime.catat_vote(otak, view, hasil["rencana_vote"])
                        elif npc["action"] in AKSI_RAHASIA:
                            match.act(bot, npc["action"], npc["target"])
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

    # Label metode harus jujur: setiap keputusan chat/vote/aksi bot dihitung oleh modul metodenya sendiri.
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
        self.assertEqual(set(label.values()), {"fuzzy"})
        self.assertEqual(dipanggil, {bot: {metode} for bot, metode in label.items()})


class NPCServiceBrainTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.runtime = runtime_siap()
        self.rooms = RoomService()
        self.room = self.rooms.create("human")
        self.rooms.set_bot(self.room.code, "human", True)
        self.rooms.start(self.room.code, "human")
        self.match = self.room.match
        self.sio = Mock(emit=AsyncMock())
        self.service = NPCService(self.sio, runtime=self.runtime)
        self.enterContext(patch("app.module.npc_service.room_service", self.rooms))
        self.persistence = self.enterContext(
            patch("app.module.npc_service.PersistenceService")
        ).return_value
        self.survey = self.enterContext(patch("app.module.npc_service.survey_service"))

    async def asyncTearDown(self):
        await self.service.close()
        self.runtime.tutup()

    async def test_preparation_assigns_brains_records_methods_and_opens_round(self):
        await self.service.prepare(self.room.code, self.match)
        self.assertTrue(self.match.preparation["ready"])
        self.assertIn("AI siap", self.match.preparation["detail"])
        rows = self.survey.record_match_bots.call_args.args[0]
        self.assertEqual(len(rows), 5)
        # Metode yang tercatat untuk survei = otak yang dipasang ke bot; pemain tidak melihatnya.
        for r in rows:
            self.assertEqual(r["method"], self.runtime.otak_bot(self.match.id, r["bot_name"]).metode)
        self.assertEqual(self.match.preparation["detail"], "AI siap: 5 bot.")
        self.assertTrue(all("metode" not in p for p in self.match.snapshot("human")["players"]))
        self.match.reveal_role("human", now=self.match.preparation["min_until"] - 1)
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
        with patch("app.module.npc_service.asyncio.sleep", AsyncMock()):
            otak.sibuk = True
            await self.service.brain_turn(self.room.code, self.match, otak)
        self.assertFalse(otak.sibuk)
        self.assertIn((1, "day", "NOX"), self.match.npc_decisions)
        self.assertEqual(self.match.messages[-1]["sender"], "NOX")
        self.persistence.record_bot_message.assert_called_once()
        self.sio.emit.assert_awaited_once()
        self.assertEqual(otak.riwayat, [self.match.messages[-1]["message"]])

    async def test_unsaved_bot_chat_is_never_broadcast(self):
        await self.service.prepare(self.room.code, self.match)
        self.match.begin()
        otak = self.runtime.otak_bot(self.match.id, "NOX")
        with self.rooms.lock:
            self.match.add_message("human", "Aku curiga NOX, dia Hitman. Ayo vote NOX!")
        jumlah_pesan = len(self.match.messages)
        self.match.deadline = time.time() + 60
        self.persistence.record_bot_message.side_effect = PersistenceError("fixture")
        with patch("app.module.npc_service.asyncio.sleep", AsyncMock()):
            await self.service.brain_turn(self.room.code, self.match, otak)
        self.persistence.record_bot_message.assert_called_once()
        self.assertEqual(len(self.match.messages), jumlah_pesan)
        self.sio.emit.assert_not_awaited()

    async def test_stale_decision_is_not_applied(self):
        await self.service.prepare(self.room.code, self.match)
        self.match.begin()
        otak = self.runtime.otak_bot(self.match.id, "NOX")
        keputusan = {
            "npc_decision": {"action": "vote", "target": "human", "message": ""},
            "rencana_vote": {"aksi": "vote", "target": "human", "alasan": [], "skor": None},
        }
        self.match.phase = "tribunal"
        stale_key = (self.match.id, self.match.round, "day")
        berlaku, penolakan = self.service._kirim_vote_atau_aksi(
            self.room.code, self.match, stale_key, otak, {"ronde": self.match.round}, keputusan
        )
        self.assertEqual((berlaku, penolakan), (False, None))
        self.assertEqual(self.match.votes, {})
        self.assertEqual(otak.ingatan.vote_bot, [])

    # Hanya vote yang diterima engine yang masuk ingatan; vote yang ditolak tidak meninggalkan catatan.
    async def test_only_accepted_vote_is_recorded_in_bot_memory(self):
        await self.service.prepare(self.room.code, self.match)
        self.match.begin()
        self.match.round, self.match.phase = 2, "tribunal"
        self.match.deadline = time.time() + 60
        otak = self.runtime.otak_bot(self.match.id, "NOX")
        fase, view = (self.match.id, 2, "tribunal"), {"ronde": 2}
        keputusan = {
            "npc_decision": {"action": "vote", "target": "human", "message": ""},
            "rencana_vote": {"aksi": "vote", "target": "human", "alasan": ["Dia aneh."]},
        }
        hasil = self.service._kirim_vote_atau_aksi(
            self.room.code, self.match, fase, otak, view, keputusan
        )
        self.assertEqual(hasil, (True, None))
        catatan = [{"ronde": 2, "target": "human", "alasan": ["Dia aneh."], "dinilai_ulang": False}]
        self.assertEqual(otak.ingatan.vote_bot, catatan)
        keputusan["npc_decision"]["target"] = "ECHO"  # suara sudah terkunci: engine menolak
        keputusan["rencana_vote"]["target"] = "ECHO"
        berlaku, penolakan = self.service._kirim_vote_atau_aksi(
            self.room.code, self.match, fase, otak, view, keputusan
        )
        self.assertTrue(berlaku)
        self.assertIsNotNone(penolakan)
        self.assertEqual(otak.ingatan.vote_bot, catatan)

    async def test_floor_lets_bots_write_in_parallel_without_twin_or_stale_plans(self):
        await self.service.prepare(self.room.code, self.match)
        self.match.begin()
        nox = self.runtime.otak_bot(self.match.id, "NOX")
        tuduh_ash = {"intent": "offend", "target": "ASH"}
        # Lantai penuh (LANTAI_MAKS bot sedang menulis) dan rencana kembar ditolak.
        penuh = {f"B{i}": ("neutral", f"P{i}") for i in range(LANTAI_MAKS)}
        self.service.lantai[self.match.id] = penuh
        self.assertFalse(self.service._ambil_giliran_bicara(self.match, nox, None, tuduh_ash))
        self.service.lantai[self.match.id] = {"ECHO": ("offend", "ASH")}
        self.assertFalse(self.service._ambil_giliran_bicara(self.match, nox, None, tuduh_ash))
        # Rencana berbeda boleh ditulis bersamaan; chat manusia sesudah snapshot tidak membatalkannya.
        with self.rooms.lock:
            terlihat = self.match.add_message("human", "Halo semua.")["id"]
            self.match.add_message("human", "Ada yang curiga?")
        bela_ash = {"intent": "defend", "target": "ASH"}
        self.assertTrue(self.service._ambil_giliran_bicara(self.match, nox, terlihat, bela_ash))
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
        self.assertFalse(self.service._ambil_giliran_bicara(self.match, nox, terlihat, bela_ash))

    async def test_accused_bots_defend_themselves_in_parallel(self):
        await self.service.prepare(self.room.code, self.match)
        self.match.begin()
        with self.rooms.lock:
            self.match.add_message("human", "NOX dan ECHO mencurigakan, kalian Hitman. Vote NOX!")
        self.match.deadline = time.time() + 60
        nox, echo = (self.runtime.otak_bot(self.match.id, nama) for nama in ("NOX", "ECHO"))
        with patch("app.module.npc_service.asyncio.sleep", AsyncMock()):
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
        with patch("app.module.npc_service.asyncio.sleep", AsyncMock()):
            self.service.jalankan_bot_yang_sudah_waktunya()
            self.service.jalankan_bot_yang_sudah_waktunya()  # bot yang sibuk tidak dijadwalkan dua kali
            await asyncio.gather(*list(self.service.tasks))
        langkah = {nama: o.langkah for nama, o in self.runtime.pertandingan[self.match.id].items()}
        self.assertEqual(langkah, {nama: 1 for nama in langkah})
        # Langkah selesai → tahap O di kartu setiap bot (I dan L sudah dilewati).
        tahap = {p["name"]: p.get("tahap") for p in self.match.snapshot("human")["players"]}
        self.assertEqual({nama: tahap[nama] for nama in langkah}, {nama: "O" for nama in langkah})

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
        self.assertTrue(
            self.service._sudah_waktunya_melangkah(otak["NOX"], self.match, elapsed, sekarang, 0)
        )
        self.assertFalse(
            self.service._sudah_waktunya_melangkah(otak["VEIL"], self.match, elapsed, sekarang, 0)
        )
        # Batas laju tetap ada: langkah segera minimal JEDA_SEGERA_DETIK sesudah langkah terakhir.
        otak["NOX"].langkah_terakhir = sekarang - 0.5
        self.assertFalse(
            self.service._sudah_waktunya_melangkah(otak["NOX"], self.match, elapsed, sekarang, 0)
        )
        with patch("app.module.npc_service.asyncio.sleep", AsyncMock()):
            otak["NOX"].sibuk = True
            await self.service.brain_turn(self.room.code, self.match, otak["NOX"])
            self.assertFalse(otak["NOX"].segera)
            self.assertEqual(self.match.messages[-1]["sender"], "NOX")
            self.assertEqual(otak["NOX"].ingatan.aksi_bot[-1]["aksi"], "jawab")
            # Panggilan yang sudah dijawab tidak dijawab lagi pada langkah berikutnya.
            otak["NOX"].sibuk = True
            await self.service.brain_turn(self.room.code, self.match, otak["NOX"])
        self.assertEqual([a["aksi"] for a in otak["NOX"].ingatan.aksi_bot].count("jawab"), 1)


class HostageResultTests(unittest.TestCase):
    # Bot Hitman memakai hasil Hostage pasti dari server (me.syndicate_hostages), bukan dugaan dari aktivitas
    # target: ingatan yang baru melihat snapshot siang tetap tahu korban berhasil dan target yang dijaga.
    def test_hitman_brains_use_certain_hostage_results(self):
        import importlib

        names = ["hitman", "spy", "stalker", "civilian", "civilian2", "civilian3"]
        game = Match(names, [], now=0, rng=random.Random(1))
        for name, player in game.players.items():
            player.role = name.rstrip("23")
        game.phase = "night"
        game.act("hitman", "hostage", "civilian")
        game.act("spy", "guard", "civilian")
        game.resolve_night()
        game.round, game.phase = 2, "night"
        game.actions.clear()
        game.act("hitman", "hostage", "civilian2")
        game.resolve_night()
        game.round, game.phase = 3, "day"
        M = importlib.import_module("app.module.npc_brain.generated.otak_fuzzy")
        ingatan = M.Ingatan("hitman")
        view = ingatan.sinkron_snapshot(game.snapshot("hitman"), time.time())
        tahu = M.pengetahuan_peran(ingatan, view)
        self.assertEqual(tahu["korban_saya"], {"civilian2"})
        self.assertEqual(tahu["dijaga"], {"civilian": 1})
        # Tanpa catatan server tidak ada kesimpulan dari pengumuman roster.
        snapshot = game.snapshot("hitman")
        snapshot["me"]["syndicate_hostages"] = []
        ingatan = M.Ingatan("hitman")
        tahu = M.pengetahuan_peran(ingatan, ingatan.sinkron_snapshot(snapshot, time.time()))
        self.assertEqual((tahu["korban_saya"], tahu["dijaga"]), (set(), {}))


class ExportFreshnessTests(unittest.TestCase):
    def test_generated_modules_match_notebooks_when_available(self):
        from pathlib import Path

        from scripts.ekspor_otak_npc import DEFAULT_NOTEBOOK_DIR, TUJUAN, sidik_notebook

        tercatat = {
            b["modul"]: b["sidik"] for b in json.loads((TUJUAN / "SUMBER.json").read_text())
        }
        self.assertEqual(set(tercatat), {"otak_fuzzy", "nlg"})
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

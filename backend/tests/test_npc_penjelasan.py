"""Penjelasan keputusan bot untuk panel checker: isi penalaran fuzzy, toleransi data rusak, batas ukuran,
penyimpanan di trace, jejak lama metode yang sudah diarsipkan, dan akses hanya lewat panel admin.

Otak memakai modul hasil ekspor notebook dengan NLU pengganti (tanpa IndoBERT), sama seperti
tests/test_npc_brain.py.
"""

import json
import random
import time
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pandas as pd
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.services.checker_service import CheckerService, checker_service
from app.module.match_engine import Match
from app.module.npc_brain.penjelasan import (
    BATAS_BYTE,
    _sistem_fuzzy,
    batasi,
    jelaskan,
    lengkapi,
    ringkas,
    ukuran,
)
from app.module.npc_service import NPCService
from app.services.room_service import RoomService
from tests.test_npc_brain import AKSI_RAHASIA, runtime_siap


# Satu pertandingan bot singkat: kumpulkan penjelasan lengkap setiap langkah yang menghasilkan jejak.
def kumpulkan(runtime, seed=3, jumlah=6, ronde_maks=3):
    nama = ["NOX", "ECHO", "VEIL", "RAVEN", "ASH", "DUSK"][:jumlah]
    match = Match([], nama, rng=random.Random(seed), now=0.0)
    runtime.siapkan_pertandingan(match, f"PJ{seed}")
    hasil_langkah, t = [], 0.0
    while not match.winner and match.round <= ronde_maks:
        durasi = match.durations[match.phase]
        for k in range(1, 4):
            for bot in sorted(match.players):
                otak = runtime.otak_bot(match.id, bot)
                if not match.players[bot].alive or match.winner:
                    continue
                waktu = t + durasi * k / 4
                view, hasil, konteks = runtime.langkah(otak, match.snapshot(bot), waktu)
                npc, tulisan, penolakan = hasil["npc_decision"], None, None
                try:
                    if hasil["nlg"] is not None:
                        tulisan = runtime.tulis(otak, hasil["nlg"], konteks)
                        match.add_message(bot, tulisan["teks"], now=waktu)
                        runtime.catat_chat(otak, view, hasil["rencana_chat"], tulisan["teks"])
                    if npc["action"] == "vote":
                        match.vote(bot, npc["target"])
                        runtime.catat_vote(otak, view, hasil["rencana_vote"])
                    elif npc["action"] in AKSI_RAHASIA:
                        match.act(bot, npc["action"], npc["target"])
                except ValueError as error:
                    penolakan = str(error)
                if tulisan or npc["action"] != "wait" or penolakan:
                    lengkap = lengkapi(hasil["penjelasan"], npc, hasil["rencana_chat"], tulisan,
                                       penolakan)  # fmt: skip
                    hasil_langkah.append((otak, npc, tulisan, lengkap))
        t += durasi
        match.tick(t)
    return hasil_langkah


# Semua blok penalaran (chat, vote, aksi, kecurigaan) dari semua langkah.
def blok_penalaran(langkah):
    return [b for *_, p in langkah for b in (p.get("penalaran") or {}).values() if b]


class PenjelasanMetodeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.langkah = {}
        runtime = runtime_siap()
        cls.langkah["fuzzy"] = kumpulkan(runtime)
        runtime.tutup()

    def test_every_trace_is_small_serializable_and_matches_the_engine_decision(self):
        for metode, langkah in self.langkah.items():
            self.assertTrue(langkah, metode)
            for otak, npc, tulisan, p in langkah:
                json.dumps(p, ensure_ascii=False, allow_nan=False)
                self.assertLessEqual(ukuran(p), BATAS_BYTE)
                self.assertEqual(p["catatan"], [], f"{metode}: {p['catatan']}")
                self.assertEqual((p["bot"]["nama"], p["bot"]["metode"]), (otak.nama, metode))
                self.assertEqual(p["bot"]["role"], otak.peran)
                self.assertEqual(
                    (p["engine"]["action"], p["engine"]["target"]), (npc["action"], npc["target"])
                )
                self.assertEqual(p["nlg"]["status"] == "terkirim", tulisan is not None)
                if tulisan:
                    self.assertEqual(p["nlg"]["teks"], tulisan["teks"])
                    self.assertIn("penulis", p["nlg"])

    def test_fuzzy_shows_memberships_fired_rules_and_suspicion_hierarchy(self):
        blok = blok_penalaran(self.langkah["fuzzy"])
        sistem = [s for b in blok for s in b.get("sistem", [])]
        self.assertTrue(sistem)
        for s in sistem:
            for masukan in s["input"]:
                self.assertEqual(set(masukan["derajat"]), {"rendah", "sedang", "tinggi"})
            self.assertTrue(s["aturan"], s["nama"])
            jika, maka, kekuatan = s["aturan"][0]
            self.assertIn(" DAN ", jika)
            self.assertIn(maka, {"rendah", "sedang", "tinggi"})
            self.assertGreater(kekuatan, 0)
        self.assertIn("keyakinan_vote", {s["nama"] for s in sistem})
        self.assertTrue(any(b.get("hierarki") for b in blok))

    def test_role_specific_tables_for_hitman_and_spy(self):
        semua = [p for langkah in self.langkah.values() for *_, p in langkah]
        hitman = [p for p in semua if p["bot"]["role"] == "hitman" and p.get("khusus_peran")]
        spy = [p for p in semua if p["bot"]["role"] == "spy" and p.get("khusus_peran")]
        self.assertTrue(hitman and spy)
        self.assertIn("ancaman", hitman[0]["khusus_peran"]["kolom"])
        self.assertIn("terancam", spy[0]["khusus_peran"]["kolom"])
        self.assertTrue(all(p["tersangka"]["judul"].startswith("Citra publik") for p in hitman))

    def test_summary_for_trace_list(self):
        # Langkah vote dari metode mana pun: di pertandingan pendek ini warga Fuzzy bisa abstain semua.
        otak, npc, tulisan, p = next(
            x for langkah in self.langkah.values() for x in langkah if x[1]["action"] == "vote"
        )
        r = ringkas(p)
        self.assertEqual(r["bot"]["nama"], otak.nama)
        self.assertIn(f"vote → {npc['target']}", r["keputusan"])
        self.assertIsNone(ringkas(None))

    # Hostage dan Guard tidak punya sistem fuzzy, tetapi tetap tampil di daftar jejak dan membawa nilainya.
    def test_hostage_and_guard_show_a_plain_value_without_fuzzy_system(self):
        for aksi in ("hostage", "guard"):
            with self.subTest(aksi=aksi):
                semua = [x for langkah in self.langkah.values() for x in langkah]
                _, npc, _, p = next(x for x in semua if x[1]["action"] == aksi)
                blok = p["penalaran"]["aksi"]
                self.assertEqual(blok["sistem"], [])
                self.assertIn(f"{aksi} → {npc['target']} (nilai ", blok["hasil"])
                self.assertIn("Tanpa sistem fuzzy", blok["catatan"])
                self.assertIn("prioritas", blok["kandidat"]["kolom"])
                self.assertIn(f"{aksi} → {npc['target']}", ringkas(p)["keputusan"])


class PenjelasanToleransiTests(unittest.TestCase):
    def test_only_gag_peek_and_chat_actions_map_to_a_fuzzy_system(self):
        semua = dict.fromkeys(("gag", "intip", "tuduh", "h_tuduh", "bela_orang"))
        modul = SimpleNamespace(SEMUA_SISTEM=semua)
        for aksi, peran, sistem in (("gag", "hitman", "gag"), ("peek", "stalker", "intip"),
                                    ("tuduh", "hitman", "h_tuduh"), ("tuduh", "spy", "tuduh"),
                                    ("bela_orang", "hitman", "bela_orang"), ("hostage", "hitman", None),
                                    ("guard", "spy", None), ("bela_diri", "hitman", None),
                                    ("jawab", "civilian", None)):  # fmt: skip
            with self.subTest(aksi=aksi, peran=peran):
                self.assertEqual(_sistem_fuzzy(modul, aksi, peran), sistem)

    # Gali tersangka tanpa nilai, walau kandidat lain dengan target sama dinilai sistem: panel menjelaskannya sebagai cadangan.
    def test_gali_tersangka_is_explained_as_a_fallback_without_a_system(self):
        bot = SimpleNamespace(
            nama="NOX", metode="fuzzy", persona="santai", peran="civilian", langkah=1
        )
        view = {"ronde": 2, "fase": "day", "saya": {"nama": "NOX", "role": "civilian"}}
        hasil = {
            "jejak_chat": pd.DataFrame([
                {"aksi": "tanya_info", "jenis": "pemain_diam", "sistem": "ajak_bicara", "target": "ASH",
                 "prioritas": 15.0, "input": {"diam": 1.0, "kecurigaan": 0.15}},
                {"aksi": "tanya_info", "jenis": "gali_tersangka", "sistem": None, "target": "ASH",
                 "prioritas": None, "input": {}},
            ]),  # fmt: skip
            "rencana_chat": {"kirim": True, "aksi": "tanya_info", "jenis": "gali_tersangka",
                             "target": "ASH", "skor": None, "alasan": ["ASH aneh."]},  # fmt: skip
        }
        modul = SimpleNamespace(SEMUA_SISTEM={"ajak_bicara": {"input": ("diam", "kecurigaan")}})
        p = jelaskan(bot, modul, view, hasil)
        blok = p["penalaran"]["chat"]
        self.assertEqual(p["keputusan"]["chat"]["jenis"], "gali_tersangka")
        self.assertEqual(blok["sistem"], [])
        self.assertEqual(blok["hasil"], "tanya_info → ASH")
        self.assertIn("Tanpa nilai", blok["catatan"])
        self.assertIn("jenis", blok["kandidat"]["kolom"])

    def test_missing_columns_and_empty_traces_do_not_raise(self):
        bot = SimpleNamespace(
            nama="NOX", metode="fuzzy", persona="santai", peran="civilian", langkah=1
        )
        view = {"ronde": 1, "fase": "day", "saya": {"nama": "NOX", "role": "civilian"}}
        hasil = {
            "tabel": pd.DataFrame([{"pemain": "ECHO", "kecurigaan": float("nan")}]),
            "jejak_chat": pd.DataFrame(
                [{"aksi": "tuduh", "target": "ECHO"}]
            ),  # tanpa prioritas/input
            "jejak_vote": pd.DataFrame(),
            "rencana_chat": {"kirim": True, "aksi": "tuduh", "target": "ECHO", "alasan": ["x"]},
        }
        modul = SimpleNamespace(SEMUA_SISTEM={})
        p = jelaskan(bot, modul, view, hasil)
        self.assertEqual(p["catatan"], [])
        self.assertIsNone(p["tersangka"]["baris"][0][1])  # NaN → None
        self.assertEqual(p["penalaran"]["chat"]["hasil"], "tuduh → ECHO")
        self.assertEqual(jelaskan(None, None, None, None)["versi"], 1)

    def test_broken_section_becomes_a_note_and_other_sections_remain(self):
        class TabelRusak:
            columns, empty = ["pemain"], False

            def to_dict(self, *_):
                raise RuntimeError("rusak")

        bot = SimpleNamespace(nama="NOX", metode="fuzzy", persona="kalem", peran="spy", langkah=2)
        p = jelaskan(bot, None, {"saya": {"nama": "NOX", "role": "spy"}}, {"tabel": TabelRusak()})
        self.assertIsNone(p["tersangka"])
        self.assertTrue(any("tersangka" in c for c in p["catatan"]))
        self.assertIn("keputusan", p)

        class ViewRusak:
            def get(self, *_):
                raise KeyError("rusak")

        self.assertIn("Identitas bot", jelaskan(bot, None, ViewRusak(), {})["catatan"][0])
        self.assertIsNone(lengkapi(None, {}, {}, None, None))

    # Chat yang ditunda lantai bicara tetap memperlihatkan rencana, templat, dan prompt LLM-nya.
    def test_deferred_chat_keeps_the_nlg_input(self):
        rencana = {"kirim": True, "aksi": "tuduh", "intent": "offend", "target": "ASH",
                   "alasan": ["ASH vote aneh."]}  # fmt: skip
        payload = {"pembicara": "NOX", "aksi": "tuduh", "intent": "offend", "target": "ASH",
                   "bukti": ["ASH vote aneh."], "gaya": "santai", "batasan": [],
                   "cadangan": "Aku makin curiga sama ASH."}  # fmt: skip
        p = lengkapi({"bot": {"nama": "NOX"}, "catatan": []}, {"action": "wait", "target": None},
                     rencana, None, None, ditunda=True,
                     masukan={"rencana": payload, "prompt": "p" * 3000})  # fmt: skip
        nlg = p["nlg"]
        self.assertEqual(nlg["status"], "ditunda")
        self.assertEqual(nlg["masukan"]["target"], "ASH")
        self.assertEqual(nlg["masukan"]["cadangan"], "Aku makin curiga sama ASH.")
        self.assertEqual(len(nlg["masukan"]["prompt"]), 2500)
        self.assertEqual(ringkas(p)["usulan"], "Aku makin curiga sama ASH.")

    def test_oversized_explanations_are_trimmed_below_the_limit(self):
        besar = {"kolom": ["pemain", "catatan"], "baris": [[f"P{i}", "x" * 200] for i in range(80)]}
        p = {"versi": 1, "bot": {"nama": "NOX"}, "catatan": [], "tersangka": besar,
             "penalaran": {"chat": {"judul": "Chat", "jenis": "fuzzy", "hasil": "tuduh",
                                    "kandidat": {"kolom": ["aksi", "target", "prioritas"],
                                                 "baris": [["n" * 150, "ECHO", 50]] * 80}}}}  # fmt: skip
        hasil = batasi(p)
        self.assertLessEqual(ukuran(hasil), BATAS_BYTE)
        self.assertTrue(hasil["catatan"])
        self.assertEqual(hasil["bot"]["nama"], "NOX")


class CheckerPenjelasanTests(unittest.TestCase):
    def test_player_facing_listing_strips_explanations(self):
        checker = CheckerService()
        trace = checker.begin("ROOMX", "NOX", "halo")
        trace.update(penjelasan={"bot": {"role": "hitman"}}, ringkas={"bot": {"nama": "NOX"}})
        self.assertNotIn("penjelasan", checker.list("ROOMX")[0])
        self.assertIn("ringkas", checker.list("ROOMX")[0])
        self.assertEqual(
            checker.list("ROOMX", penjelasan=True)[0]["penjelasan"]["bot"]["role"], "hitman"
        )

    def test_room_summary_uses_live_match_then_traces_then_archive(self):
        runtime = runtime_siap()
        rooms = RoomService()
        room = rooms.create("human")
        rooms.set_bot(room.code, "human", True)
        rooms.start(room.code, "human")
        runtime.siapkan_pertandingan(room.match, room.code)
        with (
            patch("app.services.room_service.room_service", rooms),
            patch("app.module.npc_brain.runtime.brain_runtime", runtime),
        ):
            live = CheckerService().ringkasan_room(room.code)
            # Jejak lama boleh memuat metode yang sudah diarsipkan.
            jejak = [{"sender": "NOX", "provider": "otak:bt", "model": "persona:gaul"},
                     {"ringkas": {"bot": {"nama": "ECHO", "role": "spy", "metode": "fuzzy",
                                          "persona": "kalem"}}}]  # fmt: skip
            with patch("app.services.checker_service._bot_arsip", return_value=[]) as arsip:
                dari_jejak = CheckerService().ringkasan_room("ARSIP1", jejak)
                kosong = CheckerService().ringkasan_room("ARSIP2", [])
        runtime.tutup()
        self.assertEqual(live["status"], "live")
        self.assertEqual(sum(live["komposisi"].values()), len(room.match.players))
        self.assertEqual({b["metode"] for b in live["bot"]}, {"fuzzy"})
        self.assertTrue(all(b["persona"] and b["status"] == "aktif" for b in live["bot"]))
        self.assertEqual(dari_jejak["sumber_bot"], "jejak")
        self.assertEqual(
            [(b["nama"], b["metode"], b["role"]) for b in dari_jejak["bot"]],
            [("ECHO", "fuzzy", "spy"), ("NOX", "bt", None)],
        )
        arsip.assert_called_once_with("ARSIP2")
        self.assertEqual((kosong["status"], kosong["bot"]), ("arsip", []))


class NPCServicePenjelasanTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.runtime = runtime_siap()
        self.rooms = RoomService()
        self.room = self.rooms.create("human")
        self.rooms.set_bot(self.room.code, "human", True)
        self.rooms.start(self.room.code, "human")
        self.match = self.room.match
        self.service = NPCService(Mock(emit=AsyncMock()), runtime=self.runtime)
        self.enterContext(patch("app.module.npc_service.room_service", self.rooms))
        self.persistence = self.enterContext(
            patch("app.module.npc_service.PersistenceService")
        ).return_value
        self.enterContext(patch("app.module.npc_service.survey_service"))

    async def asyncTearDown(self):
        await self.service.close()
        self.runtime.tutup()

    async def test_brain_turn_stores_explanation_with_nlg_and_a_list_summary(self):
        await self.service.prepare(self.room.code, self.match)
        self.match.begin()
        otak = self.runtime.otak_bot(self.match.id, "NOX")
        with self.rooms.lock:
            self.match.add_message("human", "Aku curiga NOX, dia Hitman. Ayo vote NOX!")
        self.match.deadline = time.time() + 60
        with patch("app.module.npc_service.asyncio.sleep", AsyncMock()):
            otak.sibuk = True
            await self.service.brain_turn(self.room.code, self.match, otak)
        trace = checker_service.list(self.room.code, penjelasan=True)[0]
        p = trace["penjelasan"]
        self.assertEqual((p["bot"]["nama"], p["bot"]["metode"]), ("NOX", "fuzzy"))
        self.assertEqual(p["nlg"]["status"], "terkirim")
        self.assertEqual(p["nlg"]["teks"], self.match.messages[-1]["message"])
        self.assertEqual(p["keputusan"]["chat"]["aksi"], "bela_diri")
        self.assertIsNone(p["keputusan"]["chat"]["skor"])
        self.assertEqual(p["penalaran"]["chat"]["hasil"], "bela_diri → NOX")
        self.assertIn("Tanpa nilai", p["penalaran"]["chat"]["catatan"])
        self.assertNotIn("ambang", p["penalaran"]["chat"])
        self.assertIn("chat bela_diri → NOX", trace["ringkas"]["keputusan"])
        stored = self.persistence.record_trace.call_args.args[0]
        self.assertLessEqual(len(json.dumps(stored["penjelasan"]).encode()), BATAS_BYTE)
        self.assertNotIn("penjelasan", checker_service.list(self.room.code)[0])


class PanelCheckerEndpointTests(unittest.TestCase):
    def setUp(self):
        from app.controllers.panel import require_panel, router

        self.app = FastAPI()
        self.app.include_router(router)
        self.client = TestClient(self.app)
        self.require_panel = require_panel
        self.code = f"PJ{random.randrange(10**6):06d}"
        self.trace = checker_service.begin(self.code, "NOX", "vote")
        # Metode "bt": jejak lama dari sebelum Behavior Tree diarsipkan harus tetap bisa dibuka.
        self.trace.update(penjelasan={"bot": {"nama": "NOX", "role": "hitman", "metode": "bt"},
                                      "penalaran": {"chat": {"jenis": "bt", "cabang": "tuduh"}}},
                          ringkas={"bot": {"nama": "NOX", "role": "hitman", "metode": "bt"}})  # fmt: skip

    def test_checker_requires_panel_session(self):
        for path in (
            f"/api/panel/checker/{self.code}",
            f"/api/panel/checker/{self.code}/jejak/{self.trace['id']}",
        ):
            self.assertEqual(self.client.get(path).status_code, 401)

    def test_list_has_room_summary_without_explanations_and_detail_has_them(self):
        self.app.dependency_overrides[self.require_panel] = lambda: "fixture-token"
        with patch("app.services.panel_service.transaction", return_value=[]):
            data = self.client.get(f"/api/panel/checker/{self.code}").json()
        self.assertNotIn("penjelasan", data["traces"][0])
        self.assertEqual(data["room"]["bot"][0]["nama"], "NOX")
        self.assertEqual(data["room"]["sumber_bot"], "jejak")
        detail = self.client.get(f"/api/panel/checker/{self.code}/jejak/{self.trace['id']}").json()
        self.assertEqual(detail["penjelasan"]["bot"]["role"], "hitman")
        self.assertEqual(data["room"]["bot"][0]["metode"], "bt")
        self.assertEqual(detail["penjelasan"]["penalaran"]["chat"]["cabang"], "tuduh")
        stored = json.dumps({"id": "a" * 32, "penjelasan": {"bot": {"nama": "ECHO"}}})
        with patch("app.services.panel_service.transaction", return_value=stored):
            arsip = self.client.get(f"/api/panel/checker/{self.code}/jejak/{'a' * 32}")
        self.assertEqual(arsip.json()["penjelasan"]["bot"]["nama"], "ECHO")
        with patch("app.services.panel_service.transaction", return_value=None):
            self.assertEqual(
                self.client.get(f"/api/panel/checker/{self.code}/jejak/{'b' * 32}").status_code, 404
            )
        self.assertEqual(
            self.client.get(f"/api/panel/checker/{self.code}/jejak/bukan-id").status_code, 422
        )

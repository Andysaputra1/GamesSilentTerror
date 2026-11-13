"""Rantai penulis kalimat NPC: urutan prioritas dari panel, jalur tanpa key, status tanpa rahasia, dan API panel.

Tidak ada panggilan jaringan: cek jalur diganti mock dan jalur rantai memakai kelas tiruan.
"""

import json
import random
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.config.settings import Settings
from app.controllers.panel import require_panel
from app.game.match_engine import Match
from app.bot import fuzzy_controller
from app.bot import ingatan as ingatan_bot
from app.bot.bot_controller import BrainRuntime, OtakBot
from app.bot.nlu import NLUBersama
from tests.palsu.nlu_palsu import NLUPalsu
from app.bot.nlg.aturan import klaim_diri, periksa_aturan
from app.bot.nlg.pengaturan import PenulisNPC
from app.bot.nlg.penulis import JALUR_PENULIS, PenulisBerantai, PenulisDasar, PenulisOpenRouter, PenulisTautan
from app.bot.nlg.prompt import MAKSUD_AKSI, buat_prompt
from app.bot.nlg.templat import PERSONA, TEMPLAT_TIM, VARIASI, kalimat_templat
from app.bot.nlg_controller import tulis_pesan

RAHASIA = {
    "openrouter": "sk-or-rahasia-uji",
    "token": "tok-rahasia",
}


# Otak dimuat tanpa IndoBERT dan tanpa penulis; tiap test mengatur rantainya sendiri.
def runtime_siap():
    runtime = BrainRuntime()
    runtime.penulis_npc.konfigurasi.penulis = "templat"
    runtime.muat_sekarang(nlu=NLUBersama(NLUPalsu(), "cadangan"))
    return runtime


# Cek rantai berjalan di thread latar; tunggu sebentar sampai mock-nya terpanggil.
def tunggu(kondisi, batas=2.0):
    akhir = time.monotonic() + batas
    while not kondisi() and time.monotonic() < akhir:
        time.sleep(0.01)
    return kondisi()


def konfigurasi_ai(link="https://llm-uji.example"):
    return SimpleNamespace(
        openrouter_api_key_value=RAHASIA["openrouter"],
        openrouter_model="qwen/qwen3-14b",
        ollama_base_url=link,
        ollama_model="qwen3:14b",
        ollama_tunnel_token=SecretStr(RAHASIA["token"]),
    )


class PenulisTiruan:
    """Penulis tanpa jaringan: mengembalikan jawaban yang disiapkan dan mencatat prompt yang diterima."""

    aktif, jalur, model = True, "tiruan", "tiruan"

    def __init__(self, jawaban):
        self.jawaban, self.pesan = list(jawaban), []

    def tulis(self, sistem, pesan):
        self.pesan.append(pesan)
        return (self.jawaban.pop(0), "ok") if self.jawaban else (None, "habis")

    def tutup(self):
        pass


class WriterChainTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runtime = runtime_siap()

    @classmethod
    def tearDownClass(cls):
        cls.runtime.tutup()

    def setUp(self):
        k = self.runtime.penulis_npc.konfigurasi
        self.awal = (k.penulis, list(k.urutan_penulis), k.model_openrouter, k.model_tautan)
        # Tanpa jaringan: cek jalur (endpoint OpenRouter/link) diganti mock.
        self.cek = self.enterContext(patch.object(PenulisNPC, "_cek"))
        self.enterContext(patch("app.bot.nlg.pengaturan.ai_runtime.current", konfigurasi_ai))

    def tearDown(self):
        penulis, urutan, model, model_tautan = self.awal
        with patch.object(type(self.runtime), "segarkan_penulis"):
            self.runtime.atur(
                penulis=penulis,
                urutan_penulis=urutan,
                model_openrouter=model,
                model_tautan=model_tautan,
            )
        self.runtime.penulis_npc.rantai = None

    # Game hanya memakai sebagian jalur notebook: OpenRouter dan link LLM sendiri.
    def test_game_paths_are_notebook_paths(self):
        self.assertEqual(JALUR_PENULIS, ("openrouter", "tautan"))

    def test_chain_follows_panel_order_and_skips_missing_keys(self):
        status = self.runtime.atur(
            penulis="otomatis",
            urutan_penulis=["tautan", "openrouter"],
            model_openrouter="qwen/qwen3-32b",
        )
        self.assertTrue(tunggu(lambda: self.cek.called))  # rantai berubah → cek di latar
        penulis = self.runtime.penulis_npc.rantai
        self.assertEqual([p.jalur for p in penulis.daftar], ["tautan", "openrouter"])
        self.assertEqual(penulis.daftar[1].model, "qwen/qwen3-32b")
        self.assertEqual(penulis.daftar[0].url, "https://llm-uji.example")
        baris = {b["jalur"]: b for b in status["rantai_penulis"]}
        self.assertEqual([b["jalur"] for b in status["rantai_penulis"]], ["tautan", "openrouter"])
        self.assertEqual(baris["tautan"]["keadaan"], "dipakai")
        self.assertEqual((status["penulis"], status["penulis_aktif"]), ("tautan", True))

    # Model link dipilih di panel; kosong = model Konfigurasi AI (OLLAMA_MODEL).
    def test_link_model_follows_panel_choice(self):
        self.runtime.atur(penulis="otomatis", urutan_penulis=["tautan"], model_tautan="")
        self.assertEqual(self.runtime.penulis_npc.rantai.daftar[0].model, "qwen3:14b")
        status = self.runtime.atur(model_tautan="qwen3:4b-instruct")
        self.assertEqual(self.runtime.penulis_npc.rantai.daftar[0].model, "qwen3:4b-instruct")
        self.assertEqual(
            (status["model_tautan"], status["model_tautan_bawaan"]),
            ("qwen3:4b-instruct", "qwen3:14b"),
        )

    # Model OpenRouter kosong = model Konfigurasi AI (qwen/qwen3-14b), bukan bawaan notebook.
    def test_openrouter_model_defaults_to_qwen(self):
        self.runtime.atur(penulis="otomatis", urutan_penulis=["openrouter"], model_openrouter="")
        self.assertEqual(self.runtime.penulis_npc.rantai.daftar[0].model, "qwen/qwen3-14b")

    def test_status_never_contains_secret_values(self):
        status = self.runtime.atur(penulis="otomatis", urutan_penulis=list(JALUR_PENULIS))
        teks = json.dumps(status, ensure_ascii=False)
        for rahasia in RAHASIA.values():
            self.assertNotIn(rahasia, teks)

    def test_invalid_writer_config_is_rejected_without_partial_changes(self):
        penulis = self.runtime.penulis_npc.konfigurasi.penulis
        for salah in (
            {"urutan_penulis": ["gpt"]},
            {"urutan_penulis": ["openrouter", "openrouter"]},
            {"model_openrouter": "claude opus"},
            {"model_tautan": "qwen3 14b"},
        ):
            with self.assertRaises(ValueError):
                self.runtime.atur(penulis="templat", **salah)
            self.assertEqual(self.runtime.penulis_npc.konfigurasi.penulis, penulis)

    def test_template_mode_disables_every_path(self):
        status = self.runtime.atur(penulis="templat")
        self.assertIsNone(self.runtime.penulis_npc.rantai)
        self.assertEqual({b["keadaan"] for b in status["rantai_penulis"]}, {"nonaktif"})
        self.assertEqual((status["penulis"], status["penulis_aktif"]), ("templat", False))

    def test_rejected_path_falls_through_to_next_writer_in_game(self):

        class Jalur(PenulisDasar):
            def __init__(self, jalur, kode=None):
                super().__init__(jalur, f"model-{jalur}")
                self.kode = kode

            def _cek(self):
                return "ok" if self.kode is None else self.gagal_dari(self.kode)[1]

            def _tulis(self, sistem, pesan):
                return self.berhasil("Aku curiga sama ECHO, dia diam terus dari tadi.")

        self.runtime.atur(penulis="otomatis", urutan_penulis=["tautan", "openrouter"])
        tautan, openrouter = Jalur("tautan", 401), Jalur("openrouter")
        self.runtime.penulis_npc.rantai = PenulisBerantai([tautan, openrouter])
        self.runtime.penulis_npc.rantai.cek()
        bot = OtakBot("NOX", "fuzzy", "santai", "civilian", None)
        payload = {"pembicara": "NOX", "aksi": "tuduh", "intent": "offend", "target": "ECHO",
                   "bukti": []}  # fmt: skip
        konteks = {"roster": ["NOX", "ECHO", "VEIL"], "chat_terbaru": []}
        tulisan = self.runtime.tulis(bot, payload, konteks)
        self.assertEqual((tulisan["sumber"], tulisan["penulis"]), ("llm", "openrouter"))
        self.assertEqual(tautan.panggilan, 0)
        baris = {b["jalur"]: b for b in self.runtime.ringkasan()["rantai_penulis"]}
        self.assertEqual(baris["tautan"]["keadaan"], "ditolak")
        self.assertEqual(baris["tautan"]["status"], "key ditolak (401)")
        self.assertEqual(baris["openrouter"]["keadaan"], "dipakai")
        # Jalur sehat yang sedang istirahat tidak disebut "dipakai": kalimat berikutnya dari templat.
        openrouter.gagal("timeout")
        status = self.runtime.ringkasan()
        self.assertEqual((status["penulis"], status["penulis_aktif"]), ("templat", False))
        self.assertEqual(status["rantai_penulis"][1]["keadaan"], "istirahat")


ENAM = {"NOX": "hitman", "ECHO": "spy", "VEIL": "stalker", "RAVEN": "civilian", "ASH": "civilian", "DUSK": "civilian"}


# Tribunal ronde 3 dengan role tetap. Dua pemain sudah vote `bot`, jadi bot terdesak dan membela diri dengan membuka role.
def bot_terdesak(bot):
    game = Match([], list(ENAM), rng=random.Random(1), now=0.0)
    for nama, pemain in game.players.items():
        pemain.role = ENAM[nama]
    game.round, game.phase = 3, "tribunal"
    game.deadline = float(game.durations["tribunal"])
    ingatan = ingatan_bot.Ingatan(bot)
    for nama in [n for n in ENAM if n != bot][:2]:
        game.vote(nama, bot)
        game.add_message(nama, f"{bot} aneh dari tadi.", now=1.0)
    view = ingatan.sinkron_snapshot(game.snapshot(bot), 20.0)
    for chat in ingatan.chat:
        chat.update(intent="offend", conf_intent=0.95, target=[{"pemain": bot, "relasi": "offend"}])
    return ingatan, view


class PublicPromptRoleTests(unittest.TestCase):
    """Prompt chat publik tidak pernah memuat role asli. Role hanya tampil lewat role_diakui, yang adalah isi rencana."""

    KONTEKS = {"roster": list(ENAM), "chat_terbaru": []}

    # Rencana yang sama memberi payload dan prompt yang sama untuk keempat role.
    def test_prompt_is_identical_for_every_true_role(self):
        rencana = fuzzy_controller.rencana_chat({"aksi": "tuduh", "jenis": "alasan_curiga", "target": "DUSK",
                                           "alasan": ["Ucapan dan vote DUSK tidak konsisten."]})  # fmt: skip
        hasil = set()
        for bot in ("NOX", "ECHO", "VEIL", "RAVEN"):
            _, view = bot_terdesak(bot)
            payload = {**fuzzy_controller.siapkan_nlg(rencana, view), "pembicara": "RAVEN"}
            hasil.add(buat_prompt(payload, self.KONTEKS, "santai"))
        self.assertEqual(len(hasil), 1)

    # Rencana nyata tiap role: payload tanpa kunci role, dan Hitman tidak pernah mengaku Hitman.
    def test_real_plans_never_carry_the_true_role(self):
        for bot in ("NOX", "ECHO", "VEIL", "RAVEN"):
            with self.subTest(bot=bot):
                ingatan, view = bot_terdesak(bot)
                payload = fuzzy_controller.putuskan(ingatan, view)["nlg"]
                self.assertIsNotNone(payload)
                self.assertFalse({"peran", "role", "tim", "klaim"} & set(payload))
                self.assertNotEqual(payload["role_diakui"], "hitman")
                sistem, pesan = buat_prompt(payload, self.KONTEKS, "santai")
                self.assertNotIn("mengaku Hitman", sistem + pesan)
                self.assertEqual("Rencana ini memang mengaku" in sistem, bool(payload["role_diakui"]))


class OpenedRoleTests(unittest.TestCase):
    """Rencana membuka role: kalimat game memakai role yang sama dengan templat simulasi, dan pemeriksa mengikuti role_diakui."""

    def setUp(self):
        self.runtime = runtime_siap()
        self.addCleanup(self.runtime.tutup)
        self.runtime.penulis_npc.konfigurasi.penulis = "otomatis"

    def tulis(self, payload, *jawaban):
        self.runtime.penulis_npc.rantai = PenulisTiruan(jawaban)
        bot = OtakBot(payload["pembicara"], "fuzzy", "santai", "civilian", None)
        return self.runtime.tulis(bot, payload, {"roster": list(ENAM), "chat_terbaru": []})

    def rencana_spy(self):
        ingatan, view = bot_terdesak("ECHO")
        view["saya"]["last_guard"] = "ASH"
        return fuzzy_controller.putuskan(ingatan, view)["nlg"]

    # Rencana D29 di uji model: dulu klaim Spy selalu ditolak pemeriksa, jadi semua model jatuh ke templat.
    def test_spy_opening_role_with_guard_evidence_passes_end_to_end(self):
        payload = self.rencana_spy()
        self.assertEqual(payload["jenis"], "role_bukti_aksi")
        self.assertEqual((payload["role_diakui"], payload["bukti_klaim"]), ("spy", "semalam jaga ASH"))
        kalimat = "Jangan vote aku, aku Spy, semalam aku jaga ASH."
        tulisan = self.tulis(payload, kalimat)
        self.assertEqual((tulisan["sumber"], tulisan["teks"]), ("llm", kalimat))
        # Tanpa LLM, templat tetap membuka role dan aksi yang sama.
        tulisan = self.tulis(payload)
        self.assertEqual(tulisan["sumber"], "templat")
        self.assertRegex(tulisan["teks"], f"(?i){ingatan_bot.POLA_KLAIM['spy']}")
        self.assertIn("ASH", tulisan["teks"])

    def test_writer_rejects_claims_outside_the_plan(self):
        payload = self.rencana_spy()
        for kalimat, aturan in (
            ("Jangan vote aku, aku Stalker.", "klaim_salah"),
            ("Jangan vote aku, aku Spy, semalam aku sandera ASH.", "aksi_sendiri"),
            ("Jangan vote aku, aku Spy, semalam aku jaga DUSK.", "nama_lain"),
        ):
            with self.subTest(kalimat=kalimat):
                self.assertIn(aturan, periksa_aturan(kalimat, payload, list(ENAM)))

    # Bot lain membaca role lewat POLA_KLAIM, jadi semua templat buka role harus terbaca sebagai role itu di ketiga persona.
    def test_templates_are_read_as_the_claimed_role(self):
        dasar = {"pembicara": "RAVEN", "aksi": "bela_diri", "intent": "defend", "target": "RAVEN", "bukti": []}
        rencana = [
            {**dasar, "jenis": "buka_role", "role_diakui": "spy"},
            {**dasar, "jenis": "buka_role", "role_diakui": "stalker"},
            {**dasar, "jenis": "buka_role", "role_diakui": "civilian"},
            {**dasar, "jenis": "role_bukti_aksi", "role_diakui": "spy", "bukti_klaim": "semalam jaga ASH"},
            {**dasar, "jenis": "role_bukti_aksi", "role_diakui": "stalker", "bukti_klaim": "kemarin peek ASH, dia bukan Hitman",
             "relasi_tambahan": [{"pemain": "ASH", "relasi": "defend"}]},
            {**dasar, "jenis": "role_bukti_aksi", "role_diakui": "stalker", "bukti_klaim": "semalam peek ASH, dia Hitman",
             "relasi_tambahan": [{"pemain": "ASH", "relasi": "offend"}]},
        ]  # fmt: skip
        for p in rencana:
            for persona in PERSONA:
                for teks in kalimat_templat(p, persona):
                    with self.subTest(teks=teks):
                        self.assertRegex(teks, f"(?i){ingatan_bot.POLA_KLAIM[p['role_diakui']]}")
                        self.assertEqual(periksa_aturan(teks, p, list(ENAM)), [])
                        self.assertEqual(klaim_diri(teks.casefold()), {p["role_diakui"]})


class TemplateCoverageTests(unittest.TestCase):
    # Semua jenis di otak punya templat dan maksud. pelintir_bukti memakai kalimat alasan_curiga.
    def test_every_plan_kind_has_templates_and_intent(self):
        self.assertEqual(set(MAKSUD_AKSI), set(VARIASI))
        jenis = {k.split("/")[1] for k in VARIASI}
        self.assertEqual(set(fuzzy_controller.INTENT_JENIS) - jenis, {"pelintir_bukti"})
        self.assertTrue(all(len(v) >= 3 for v in VARIASI.values()))
        self.assertTrue(all(len(v) >= 5 for isi in TEMPLAT_TIM.values() for v in isi.values()))

    # Varian yang baru terdengar tetap dicoba bila semua varian baru gugur aturan.
    def test_heard_variant_is_tried_when_new_variants_fail(self):
        p = {"pembicara": "NOX", "aksi": "tuduh", "jenis": "alasan_curiga", "intent": "offend", "target": "ECHO",
             "bukti": ["ECHO " + "aneh sekali dari tadi " * 12]}  # fmt: skip
        sudah = ["Aku curiga sama ECHO.", "Menurutku ECHO patut dicurigai."]
        tulisan = tulis_pesan(p, {"roster": ["NOX", "ECHO"], "chat_terbaru": []}, None, "santai", hindari=sudah)
        self.assertEqual(tulisan["sumber"], "templat")
        self.assertIn(tulisan["teks"], sudah)


class WriterSentenceRuleTests(unittest.TestCase):
    """Kalimat LLM langsung dikirim bila lolos aturan; IndoBERT tidak membaca ulang sebelum kirim."""

    PAYLOAD = {"pembicara": "NOX", "aksi": "tuduh", "intent": "offend", "target": "ECHO",
               "bukti": []}  # fmt: skip
    KONTEKS = {"roster": ["NOX", "ECHO", "VEIL"], "chat_terbaru": []}

    def setUp(self):
        self.runtime = runtime_siap()
        self.addCleanup(self.runtime.tutup)
        self.runtime.penulis_npc.konfigurasi.penulis = "otomatis"
        self.bot = OtakBot("NOX", "fuzzy", "santai", "civilian", None)

    def tulis(self, *jawaban):
        penulis = PenulisTiruan(jawaban)
        self.runtime.penulis_npc.rantai = penulis
        return self.runtime.tulis(self.bot, self.PAYLOAD, self.KONTEKS), penulis

    def test_kalimat_lolos_aturan_terkirim_tanpa_dibaca_nlu(self):
        self.runtime.nlu = Mock()
        tulisan, penulis = self.tulis("Aku curiga sama ECHO, dia diam terus dari tadi.")
        self.assertEqual(tulisan["sumber"], "llm")
        self.assertTrue(tulisan["lolos_aturan"])
        self.assertEqual(len(penulis.pesan), 1)
        self.assertEqual(self.runtime.nlu.mock_calls, [])
        self.assertNotIn("lolos_nlu", tulisan)
        self.assertNotIn("nlu", tulisan)

    def test_pelanggaran_aturan_ditulis_ulang_dengan_alasannya(self):
        tulisan, penulis = self.tulis(
            "Sebagai AI, aku curiga sama ECHO.", "Aku curiga sama ECHO dari tadi."
        )
        self.assertEqual(tulisan["sumber"], "llm")
        self.assertEqual(tulisan["teks"], "Aku curiga sama ECHO dari tadi.")
        self.assertIn("ditolak karena: menyebut_ai", penulis.pesan[1])

    def test_kedua_percobaan_melanggar_aturan_jatuh_ke_templat(self):
        tulisan, penulis = self.tulis("Aku bot.", "Aku bot.")
        self.assertEqual(len(penulis.pesan), 2)
        self.assertEqual((tulisan["sumber"], tulisan["penulis"]), ("templat", None))
        self.assertIn("ECHO", tulisan["teks"])
        self.assertEqual(tulisan["pelanggaran"], [])

    # Salinan fakta panjang ditulis ulang sekali; bila percobaan ulang gagal, salinan itu tetap dipakai, bukan templat.
    def test_salinan_fakta_ditulis_ulang_sekali(self):
        fakta = (
            "ECHO ikut mendorong eksekusi VEIL (ronde 2), padahal jumlah Hitman tidak berkurang"
            " jadi VEIL bukan Hitman."
        )
        salinan = (
            "Aku curiga ECHO, dia ikut mendorong eksekusi VEIL padahal jumlah Hitman gak berkurang,"
            " jadi VEIL bukan Hitman."
        )
        penulis = PenulisTiruan([salinan, "Aku bot."])
        self.runtime.penulis_npc.rantai = penulis
        tulisan = self.runtime.tulis(self.bot, {**self.PAYLOAD, "bukti": [fakta]}, self.KONTEKS)
        self.assertIn("ditolak karena: salin_fakta", penulis.pesan[1])
        self.assertEqual((tulisan["sumber"], tulisan["teks"]), ("llm", salinan))

    # Nama tahap ini dipakai kotak nlg_cek di flowchart simulasi panel.
    def test_tahap_yang_dilaporkan_ke_flowchart(self):
        tahap = []
        self.runtime.penulis_npc.rantai = PenulisTiruan(["Aku curiga sama ECHO, dia diam terus dari tadi."])
        self.runtime.tulis(self.bot, self.PAYLOAD, self.KONTEKS, lapor=tahap.append)
        self.assertEqual(tahap, ["nlg", "llm", "aturan"])


class AnswerPlanTests(unittest.TestCase):
    """Rencana jawab F18 dari uji model 6 November: VEIL ditanya ONYX, tersangkanya SAGE, dan ronde ini VEIL vote DUSK."""

    ROSTER = ["NOX", "ECHO", "VEIL", "RAVEN", "ASH", "DUSK", "IRIS", "SAGE", "ONYX", "LARK"]
    ALASAN = ["SAGE menuduh atau vote aku, padahal aku tahu aku bukan Hitman."]
    PAYLOAD = {
        "pembicara": "VEIL", "aksi": "jawab", "jenis": None, "intent": "offend", "target": "SAGE", "role_diakui": None,
        "bukti_klaim": None, "relasi_tambahan": [], "bukti": ALASAN, "penanya": "ONYX",
        "paket": {"pertanyaan": "VEIL, gimana penjelasanmu?", "penanya": "ONYX", "kondisi": "agak yakin",
                  "tersangka": {"nama": "SAGE", "alasan": ALASAN}, "pendapat_pemain": {},
                  "tindakan_sebelumnya": [
                      {"tindakan": "bela", "ronde": 7, "target": "ONYX", "alasan": ["Tuduhan ke ONYX masih pendapat, ada yang membela juga."]},
                      {"tindakan": "vote", "ronde": 7, "target": "DUSK", "alasan": ["ECHO mengaku peek DUSK sebagai Hitman."]}],
                  "jawaban_role": "aku orang baik", "chat_saya_ronde_ini": 1},
    }  # fmt: skip
    KONTEKS = {"roster": ROSTER, "chat_terbaru": [
        {"pengirim": "ONYX", "teks": "VEIL, gimana penjelasanmu?", "intent": "neutral", "target": [{"pemain": "VEIL", "relasi": "neutral"}]}]}  # fmt: skip

    def setUp(self):
        self.runtime = runtime_siap()
        self.addCleanup(self.runtime.tutup)
        self.runtime.penulis_npc.konfigurasi.penulis = "otomatis"
        self.bot = OtakBot("VEIL", "fuzzy", "kalem", "civilian", None)

    def tulis(self, *jawaban):
        penulis = PenulisTiruan(jawaban)
        self.runtime.penulis_npc.rantai = penulis
        return self.runtime.tulis(self.bot, self.PAYLOAD, self.KONTEKS), penulis

    # Dulu "saya yakin DUSK bukan Hitman" lolos karena semua nama di paket boleh dipakai. Target vote boleh dijelaskan, tidak dibela.
    def test_answer_cannot_defend_its_own_vote_target(self):
        tulisan, penulis = self.tulis(
            "Saya tidak menuduh siapa pun, tapi saya yakin DUSK bukan Hitman.",
            "Saya vote DUSK karena ECHO mengaku sudah peek dia.",
        )
        self.assertIn("ditolak karena: bela_lain", penulis.pesan[1])
        self.assertEqual(tulisan["sumber"], "llm")
        self.assertEqual(tulisan["teks"], "Saya vote DUSK karena ECHO mengaku sudah peek dia.")

    # Permintaan penjelasan dulu jatuh ke data tersangka; sekarang tindakan sebelumnya yang dikirim ke penulis.
    def test_explanation_request_sends_previous_actions(self):
        pesan = buat_prompt(self.PAYLOAD, self.KONTEKS, "kalem")[1]
        self.assertIn("Di ronde 7 saya vote DUSK. ECHO mengaku peek DUSK sebagai Hitman.", pesan)
        self.assertNotIn("Tersangka saya", pesan)


class TeamChatIntentTests(unittest.TestCase):
    """Chat tim Spy dari uji model 6 November: Spy menjaga, jadi prompt tidak memakai target_saya dan kata serangan ditolak."""

    PAKET = {"pembicara": "Nara", "aksi": "chat_tim", "tim": "spy", "pemicu": "pilih_target", "target_saya": "Andi",
             "pilihan_rekan": None, "alasan": ["Andi menuduh atau vote aku."], "chat_tim": []}  # fmt: skip

    def test_spy_attack_words_are_rewritten(self):
        runtime = runtime_siap()
        self.addCleanup(runtime.tutup)
        runtime.penulis_npc.konfigurasi.penulis = "otomatis"
        penulis = PenulisTiruan(["Gw incer Andi malem ini.", "Gw jaga Andi malem ini."])
        runtime.penulis_npc.rantai = penulis
        bot = OtakBot("Nara", "fuzzy", "gaul", "spy", None)
        tulisan = runtime.tulis_tim(bot, self.PAKET, ["Nara", "Andi", "Budi"])
        self.assertEqual((tulisan["sumber"], tulisan["teks"]), ("llm", "Gw jaga Andi malem ini."))
        self.assertIn("dijaga_malam_ini: Andi", penulis.pesan[0])
        self.assertIn("ditolak karena: kata_dilarang", penulis.pesan[1])


class WriterCheckTests(unittest.TestCase):
    """Cek rantai sungguhan (jalur asli, `_cek` tiruan): flag antre, status, log, dan alamat link."""

    def setUp(self):
        self.runtime = runtime_siap()
        self.addCleanup(self.runtime.tutup)
        self.runtime.penulis_npc.konfigurasi.penulis = "otomatis"
        self.enterContext(patch("app.bot.nlg.pengaturan.ai_runtime.current", konfigurasi_ai))
        self.enterContext(
            patch("app.bot.nlg.pengaturan.ai_runtime.diatur_panel", return_value=True)
        )
        # Tanpa jaringan: cek tiap jalur menunggu aba-aba lalu melapor sesuai kelasnya.
        self.lepas = threading.Event()

        def cek_tiruan(hasil):
            def _cek(jalur):
                self.lepas.wait(2)
                return "ok" if hasil == "ok" else jalur.gagal_dari(hasil)[1]

            return _cek

        for kelas, hasil in ((PenulisOpenRouter, "ok"), (PenulisTautan, "tidak terhubung")):
            self.enterContext(patch.object(kelas, "_cek", cek_tiruan(hasil)))

    def test_flag_stays_on_until_the_last_queued_check_finishes(self):
        self.runtime.segarkan_penulis()
        self.runtime.segarkan_penulis()  # antre di belakang cek pertama
        self.assertTrue(self.runtime.ringkasan()["sedang_cek_penulis"])
        self.lepas.set()
        self.assertTrue(tunggu(lambda: not self.runtime.ringkasan()["sedang_cek_penulis"]))
        self.assertEqual(self.runtime.penulis_npc._cek_tertunda, 0)

    def test_synchronous_check_reports_each_path_without_secret_values(self):
        self.lepas.set()
        with self.assertLogs("shadow_heist.npc_brain", "INFO") as log:
            status = self.runtime.segarkan_penulis(latar=False)
        baris = {b["jalur"]: b for b in status["rantai_penulis"]}
        self.assertFalse(status["sedang_cek_penulis"])
        self.assertEqual(baris["openrouter"]["keadaan"], "dipakai")
        self.assertEqual(baris["openrouter"]["hasil_cek"]["keadaan"], "berhasil")
        self.assertGreater(baris["openrouter"]["hasil_cek"]["waktu"], 0)
        self.assertGreaterEqual(baris["openrouter"]["hasil_cek"]["durasi_ms"], 0)
        self.assertEqual(baris["tautan"]["keadaan"], "istirahat")
        self.assertEqual(baris["tautan"]["hasil_cek"]["keadaan"], "gagal")
        self.assertEqual(baris["tautan"]["alamat"], {"host": "llm-uji.example", "sumber": "panel"})
        teks = "\n".join(log.output) + json.dumps(status, ensure_ascii=False)
        for rahasia in RAHASIA.values():
            self.assertNotIn(rahasia, teks)

    def test_link_check_requires_an_actual_reply(self):
        self.lepas.set()
        with (
            patch.object(PenulisTautan, "_cek", return_value="ok"),
            patch.object(PenulisTautan, "tulis", return_value=("", "ok")) as hit,
        ):
            status = self.runtime.segarkan_penulis(latar=False)
        hit.assert_called_once_with("Jawab singkat.", "Balas: ok")
        link = next(b for b in status["rantai_penulis"] if b["jalur"] == "tautan")
        self.assertEqual(link["hasil_cek"]["keadaan"], "gagal")
        self.assertEqual(link["hasil_cek"]["detail"], "jawaban pengujian kosong")


class NpcConfigStoreTests(unittest.TestCase):
    """Baris konfigurasi NPC di DB: baris lama/tidak valid aman, simpan gagal dikembalikan utuh."""

    def test_old_and_invalid_rows_keep_env_values(self):
        from app.services import npc_config_service as layanan

        with (
            patch.object(layanan, "brain_runtime") as runtime,
            patch.object(layanan, "jalankan_transaksi") as baca,
        ):
            # Baris produksi lama masih memuat kunci metode dan validasi; keduanya diabaikan.
            baca.return_value = {"metode": "fuzzy", "penulis": "otomatis", "validasi": True}
            layanan.muat_konfigurasi_npc()
            runtime.atur.assert_called_once_with(
                penulis="otomatis",
                urutan_penulis=None, model_openrouter=None, model_tautan=None,
            )  # fmt: skip
            runtime.atur.side_effect = ValueError("jalur tidak dikenal")
            baca.return_value = {"urutan_penulis": ["gpt"]}
            with self.assertLogs("shadow_heist.npc_config", "WARNING"):
                layanan.muat_konfigurasi_npc()  # tidak melempar error saat startup

    def test_failed_save_restores_every_field(self):
        from app.services import npc_config_service as layanan
        from app.services.persistence_service import PersistenceError

        sebelum = {"penulis_diminta": "otomatis",
                   "urutan_penulis": ["openrouter", "tautan"], "model_openrouter": "",
                   "model_tautan": ""}  # fmt: skip
        with (
            patch.object(layanan, "brain_runtime") as runtime,
            patch.object(layanan, "jalankan_transaksi", side_effect=PersistenceError("db")),
        ):
            runtime.ringkasan.return_value = sebelum
            runtime.atur.return_value = {**sebelum, "urutan_penulis": ["tautan"]}
            with self.assertRaises(PersistenceError):
                layanan.save_npc_configuration("otomatis", ["tautan"], "")
        runtime.atur.assert_called_with(
            penulis="otomatis",
            urutan_penulis=["openrouter", "tautan"], model_openrouter="", model_tautan="",
        )  # fmt: skip


class WriterSettingsTests(unittest.TestCase):
    def test_env_order_and_model_are_validated(self):
        self.assertEqual(
            Settings(npc_writer_order=" openrouter , tautan ").npc_writer_order, "openrouter,tautan"
        )
        for salah in (
            {"npc_writer_order": "openrouter,gpt"},
            {"npc_openrouter_model": "opus"},
            {"npc_openrouter_model": "anthropic/../key"},
        ):
            with self.assertRaises(ValueError):
                Settings(**salah)


class PanelWriterApiTests(unittest.TestCase):
    def setUp(self):
        from app.controllers import panel, panel_npc
        from app.services import panel_service

        self.app = FastAPI()
        self.app.include_router(panel_npc.router)
        self.app.include_router(panel.router)
        self.app.dependency_overrides[require_panel] = lambda: "fixture-token"
        self.client = TestClient(self.app)
        self.panel = panel_service

    def test_save_sends_order_and_model_to_runtime(self):
        ringkasan = {"penulis_diminta": "otomatis",
                     "urutan_penulis": ["openrouter", "tautan"], "model_openrouter": "",
                     "model_tautan": "qwen3:4b-instruct"}  # fmt: skip
        with (
            patch("app.services.npc_config_service.brain_runtime") as runtime,
            patch("app.services.npc_config_service.jalankan_transaksi") as simpan,
        ):
            runtime.atur.return_value = ringkasan
            # Klien lama (skrip kirim-link versi lama) masih boleh mengirim kunci validasi; kuncinya diabaikan.
            response = self.client.put(
                "/api/panel/npc",
                json={"penulis": "otomatis", "validasi": True,
                      "urutan_penulis": ["openrouter", "tautan"], "model_openrouter": "",
                      "model_tautan": "qwen3:4b-instruct"},
            )  # fmt: skip
        self.assertEqual(response.status_code, 200)
        runtime.atur.assert_called_once_with(
            penulis="otomatis",
            urutan_penulis=["openrouter", "tautan"], model_openrouter="",
            model_tautan="qwen3:4b-instruct",
        )  # fmt: skip
        simpan.assert_called_once()
        bad = self.client.put(
            "/api/panel/npc",
            json={"penulis": "otomatis", "urutan_penulis": ["gpt"]},
        )
        self.assertEqual(bad.status_code, 422)

    # Panel tidak lagi menawarkan metode yang sudah diarsipkan; hanya nilai tersimpan lama yang dibaca fuzzy.
    def test_method_choice_is_gone_and_simulation_bot_count_is_limited(self):
        data = self.client.get("/api/panel/npc").json()
        self.assertNotIn("metode", data["pilihan"])
        self.assertNotIn("metode", data["status"])
        for jumlah in (2, 10):
            simulasi = self.client.post("/api/panel/simulasi", json={"jumlah_bot": jumlah})
            self.assertEqual(simulasi.status_code, 422)

    def test_check_endpoint_rebuilds_and_checks_in_background(self):
        with patch("app.services.panel_service.brain_runtime") as runtime:
            runtime.segarkan_penulis.return_value = {"penulis": "openrouter"}
            response = self.client.post("/api/panel/npc/cek-penulis")
        self.assertEqual(response.status_code, 200)
        runtime.segarkan_penulis.assert_called_once_with(latar=True)
        self.assertIn("jalur_penulis", response.json()["pilihan"])

    def test_saving_ai_link_refreshes_writer_chain(self):
        with (
            patch.object(self.panel, "simpan_konfigurasi_ai"),
            patch.object(self.panel, "validate_endpoint", side_effect=lambda e: e),
            patch.object(self.panel, "brain_runtime") as runtime,
        ):
            response = self.client.put(
                "/api/panel/config",
                json={"provider": "docker", "endpoint": "https://llm-uji.example"},
            )
        self.assertEqual(response.status_code, 200)
        runtime.segarkan_penulis.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()

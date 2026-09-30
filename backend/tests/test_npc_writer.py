"""Rantai penulis kalimat NPC: urutan prioritas dari panel, jalur tanpa key, status tanpa rahasia, dan API panel.

Tidak ada panggilan jaringan: cek jalur diganti mock dan jalur rantai memakai kelas tiruan.
"""

import json
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from config.settings import Settings
from controller.api.panel import require_panel
from services.npc_brain.runtime import (
    JALUR_PENULIS, BrainRuntime, NLUBersama, NLUCadangan, OtakBot,
)  # fmt: skip

RAHASIA = {
    "amazon": "kunci-bedrock-rahasia-uji",
    "openrouter": "sk-or-rahasia-uji",
    "token": "tok-rahasia",
}


# Otak dimuat tanpa IndoBERT dan tanpa penulis; tiap test mengatur rantainya sendiri.
def runtime_siap():
    runtime = BrainRuntime()
    runtime.konfigurasi.penulis = "templat"
    runtime.muat_sekarang(nlu=NLUBersama(NLUCadangan(None), "cadangan"))
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
        ollama_base_url=link,
        ollama_model="qwen3:14b",
        ollama_tunnel_token=SecretStr(RAHASIA["token"]),
    )


class WriterChainTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runtime = runtime_siap()
        cls.nlg = cls.runtime.nlg

    @classmethod
    def tearDownClass(cls):
        cls.runtime.tutup()

    def setUp(self):
        k = self.runtime.konfigurasi
        self.awal = (k.penulis, list(k.urutan_penulis), k.model_openrouter)
        # Tanpa jaringan: cek jalur (Claude 8 token, endpoint OpenRouter/link) diganti mock.
        self.cek = self.enterContext(patch.object(type(self.runtime), "_cek_penulis"))
        self.enterContext(patch("services.npc_brain.runtime.ai_runtime.current", konfigurasi_ai))
        settings = self.enterContext(patch("services.npc_brain.runtime.settings"))
        settings.amazon_api_key = SecretStr(RAHASIA["amazon"])
        settings.anthropic_api_key = None
        settings.npc_bedrock_region = "us-east-1"

    def tearDown(self):
        penulis, urutan, model = self.awal
        with patch.object(type(self.runtime), "segarkan_penulis"):
            self.runtime.atur(penulis=penulis, urutan_penulis=urutan, model_openrouter=model)
        self.runtime.penulis = None

    def test_runtime_and_notebook_share_writer_paths(self):
        self.assertEqual(tuple(self.nlg.JALUR_PENULIS), JALUR_PENULIS)

    def test_chain_follows_panel_order_and_skips_missing_keys(self):
        status = self.runtime.atur(
            penulis="otomatis",
            urutan_penulis=["openrouter", "claude_api", "tautan"],
            model_openrouter="anthropic/claude-sonnet-5.5",
        )
        self.assertTrue(tunggu(lambda: self.cek.called))  # rantai berubah → cek di latar
        penulis = self.runtime.penulis
        self.assertEqual([p.jalur for p in penulis.daftar], ["openrouter", "tautan"])
        self.assertEqual(penulis.daftar[0].model, "anthropic/claude-sonnet-5.5")
        self.assertEqual(penulis.daftar[1].url, "https://llm-uji.example")
        baris = {b["jalur"]: b for b in status["rantai_penulis"]}
        self.assertEqual(
            [b["jalur"] for b in status["rantai_penulis"]],
            ["openrouter", "claude_api", "tautan", "claude_bedrock"],
        )
        self.assertEqual(baris["openrouter"]["keadaan"], "dipakai")
        self.assertEqual(baris["claude_api"]["status"], "key belum diisi")
        self.assertEqual(baris["claude_bedrock"]["keadaan"], "nonaktif")
        self.assertEqual((status["penulis"], status["penulis_aktif"]), ("openrouter", True))

    def test_status_never_contains_secret_values(self):
        status = self.runtime.atur(penulis="otomatis", urutan_penulis=list(JALUR_PENULIS))
        teks = json.dumps(status, ensure_ascii=False)
        for rahasia in RAHASIA.values():
            self.assertNotIn(rahasia, teks)

    def test_invalid_writer_config_is_rejected_without_partial_changes(self):
        metode = self.runtime.konfigurasi.metode
        for salah in (
            {"urutan_penulis": ["gpt"]},
            {"urutan_penulis": ["openrouter", "openrouter"]},
            {"model_openrouter": "claude opus"},
        ):
            with self.assertRaises(ValueError):
                self.runtime.atur(metode="bt", **salah)
            self.assertEqual(self.runtime.konfigurasi.metode, metode)
        # Nilai lama "claude" diterima sebagai rantai otomatis.
        self.assertEqual(self.runtime.atur(penulis="claude")["penulis_diminta"], "otomatis")

    def test_template_mode_disables_every_path(self):
        status = self.runtime.atur(penulis="templat")
        self.assertIsNone(self.runtime.penulis)
        self.assertEqual({b["keadaan"] for b in status["rantai_penulis"]}, {"nonaktif"})
        self.assertEqual((status["penulis"], status["penulis_aktif"]), ("templat", False))

    def test_rejected_path_falls_through_to_next_writer_in_game(self):
        nlg = self.nlg

        class Jalur(nlg.PenulisDasar):
            def __init__(self, jalur, kode=None):
                super().__init__(jalur, f"model-{jalur}")
                self.kode = kode

            def _cek(self):
                return "ok" if self.kode is None else self.gagal_dari(self.kode)[1]

            def _tulis(self, sistem, pesan):
                return self.berhasil("Aku curiga sama ECHO, dia diam terus dari tadi.")

        self.runtime.atur(penulis="otomatis", urutan_penulis=["claude_bedrock", "openrouter"])
        bedrock, openrouter = Jalur("claude_bedrock", 401), Jalur("openrouter")
        self.runtime.penulis = nlg.PenulisBerantai([bedrock, openrouter])
        self.runtime.penulis.cek()
        self.runtime.konfigurasi.validasi = False
        try:
            bot = OtakBot("NOX", "fuzzy", "santai", "civilian", None)
            payload = {"pembicara": "NOX", "aksi": "tuduh", "intent": "offend", "target": "ECHO",
                       "klaim": False, "bukti": []}  # fmt: skip
            konteks = {"roster": ["NOX", "ECHO", "VEIL"], "chat_terbaru": []}
            tulisan = self.runtime.tulis(bot, payload, konteks)
        finally:
            self.runtime.konfigurasi.validasi = True
        self.assertEqual((tulisan["sumber"], tulisan["penulis"]), ("llm", "openrouter"))
        self.assertEqual(bedrock.panggilan, 0)
        baris = {b["jalur"]: b for b in self.runtime.ringkasan()["rantai_penulis"]}
        self.assertEqual(baris["claude_bedrock"]["keadaan"], "ditolak")
        self.assertEqual(baris["claude_bedrock"]["status"], "key ditolak (401)")
        self.assertEqual(baris["openrouter"]["keadaan"], "dipakai")
        # Jalur sehat yang sedang istirahat tidak disebut "dipakai": kalimat berikutnya dari templat.
        openrouter.gagal("timeout")
        status = self.runtime.ringkasan()
        self.assertEqual((status["penulis"], status["penulis_aktif"]), ("templat", False))
        self.assertEqual(status["rantai_penulis"][1]["keadaan"], "istirahat")


class WriterCheckTests(unittest.TestCase):
    """Cek rantai sungguhan (jalur asli, `_cek` tiruan): flag antre, status, log, dan alamat link."""

    def setUp(self):
        self.runtime = runtime_siap()
        self.addCleanup(self.runtime.tutup)
        self.runtime.konfigurasi.penulis = "otomatis"
        self.enterContext(patch("services.npc_brain.runtime.ai_runtime.current", konfigurasi_ai))
        self.enterContext(
            patch("services.npc_brain.runtime.ai_runtime.diatur_panel", return_value=True)
        )
        settings = self.enterContext(patch("services.npc_brain.runtime.settings"))
        settings.amazon_api_key = SecretStr(RAHASIA["amazon"])
        settings.anthropic_api_key = None
        settings.npc_bedrock_region = "us-east-1"
        # Tanpa jaringan: cek tiap jalur menunggu aba-aba lalu melapor sesuai kelasnya.
        self.lepas = threading.Event()
        nlg = self.runtime.nlg

        def cek_tiruan(hasil):
            def _cek(jalur):
                self.lepas.wait(2)
                return "ok" if hasil == "ok" else jalur.gagal_dari(hasil)[1]

            return _cek

        for kelas, hasil in ((nlg.PenulisClaude, 401), (nlg.PenulisOpenRouter, "ok"),
                             (nlg.PenulisTautan, "tidak terhubung")):  # fmt: skip
            self.enterContext(patch.object(kelas, "_cek", cek_tiruan(hasil)))

    def test_flag_stays_on_until_the_last_queued_check_finishes(self):
        self.runtime.segarkan_penulis()
        self.runtime.segarkan_penulis()  # antre di belakang cek pertama
        self.assertTrue(self.runtime.ringkasan()["sedang_cek_penulis"])
        self.lepas.set()
        self.assertTrue(tunggu(lambda: not self.runtime.ringkasan()["sedang_cek_penulis"]))
        self.assertEqual(self.runtime._cek_tertunda, 0)

    def test_synchronous_check_reports_each_path_without_secret_values(self):
        self.lepas.set()
        with self.assertLogs("shadow_heist.npc_brain", "INFO") as log:
            status = self.runtime.segarkan_penulis(latar=False)
        baris = {b["jalur"]: b for b in status["rantai_penulis"]}
        self.assertFalse(status["sedang_cek_penulis"])
        self.assertEqual((baris["claude_bedrock"]["keadaan"], baris["claude_bedrock"]["status"]),
                         ("ditolak", "key ditolak (401)"))  # fmt: skip
        self.assertEqual(baris["openrouter"]["keadaan"], "dipakai")
        self.assertEqual(baris["tautan"]["keadaan"], "istirahat")
        self.assertEqual(baris["tautan"]["alamat"], {"host": "llm-uji.example", "sumber": "panel"})
        self.assertEqual(baris["claude_api"]["status"], "key belum diisi")
        teks = "\n".join(log.output) + json.dumps(status, ensure_ascii=False)
        for rahasia in RAHASIA.values():
            self.assertNotIn(rahasia, teks)


class NpcConfigStoreTests(unittest.TestCase):
    """Baris konfigurasi NPC di DB: baris lama/tidak valid aman, simpan gagal dikembalikan utuh."""

    def test_old_and_invalid_rows_keep_env_values(self):
        from services import npc_config_service as layanan

        with (
            patch.object(layanan, "brain_runtime") as runtime,
            patch.object(layanan.PersistenceService, "_run") as baca,
        ):
            baca.return_value = {"metode": "bt", "penulis": "claude", "validasi": True}
            layanan.load_npc_configuration()
            runtime.atur.assert_called_once_with(
                metode="bt", penulis="claude", validasi=True,
                urutan_penulis=None, model_openrouter=None,
            )  # fmt: skip
            runtime.atur.side_effect = ValueError("jalur tidak dikenal")
            baca.return_value = {"metode": "bt", "urutan_penulis": ["gpt"]}
            with self.assertLogs("shadow_heist.npc_config", "WARNING"):
                layanan.load_npc_configuration()  # tidak melempar error saat startup

    def test_failed_save_restores_every_field(self):
        from services import npc_config_service as layanan
        from services.persistence_service import PersistenceError

        sebelum = {"metode": "campuran", "penulis_diminta": "otomatis", "validasi": True,
                   "urutan_penulis": ["claude_bedrock", "openrouter"], "model_openrouter": ""}  # fmt: skip
        with (
            patch.object(layanan, "brain_runtime") as runtime,
            patch.object(layanan.PersistenceService, "_run", side_effect=PersistenceError("db")),
        ):
            runtime.ringkasan.return_value = sebelum
            runtime.atur.return_value = {**sebelum, "metode": "bt", "urutan_penulis": ["tautan"]}
            with self.assertRaises(PersistenceError):
                layanan.save_npc_configuration("bt", "otomatis", True, ["tautan"], "")
        runtime.atur.assert_called_with(
            metode="campuran", penulis="otomatis", validasi=True,
            urutan_penulis=["claude_bedrock", "openrouter"], model_openrouter="",
        )  # fmt: skip


class WriterSettingsTests(unittest.TestCase):
    def test_env_order_model_and_region_are_validated(self):
        self.assertEqual(
            Settings(npc_writer_order=" openrouter , tautan ").npc_writer_order, "openrouter,tautan"
        )
        for salah in (
            {"npc_writer_order": "openrouter,gpt"},
            {"npc_openrouter_model": "opus"},
            {"npc_openrouter_model": "anthropic/../key"},
            {"npc_bedrock_region": "x.evil.com/#"},
        ):
            with self.assertRaises(ValueError):
                Settings(**salah)
        self.assertEqual(Settings(npc_bedrock_region="ap-southeast-1").npc_bedrock_region,
                         "ap-southeast-1")  # fmt: skip


class PanelWriterApiTests(unittest.TestCase):
    def setUp(self):
        from controller.api import panel, panel_npc

        self.app = FastAPI()
        self.app.include_router(panel_npc.router)
        self.app.include_router(panel.router)
        self.app.dependency_overrides[require_panel] = lambda: "fixture-token"
        self.client = TestClient(self.app)
        self.panel = panel

    def test_save_sends_order_and_model_to_runtime(self):
        ringkasan = {"metode": "bt", "penulis_diminta": "otomatis", "validasi": True,
                     "urutan_penulis": ["openrouter", "tautan"], "model_openrouter": ""}  # fmt: skip
        with (
            patch("services.npc_config_service.brain_runtime") as runtime,
            patch("services.npc_config_service.PersistenceService._run") as simpan,
        ):
            runtime.atur.return_value = ringkasan
            response = self.client.put(
                "/api/panel/npc",
                json={"metode": "bt", "penulis": "otomatis", "validasi": True,
                      "urutan_penulis": ["openrouter", "tautan"], "model_openrouter": ""},
            )  # fmt: skip
        self.assertEqual(response.status_code, 200)
        runtime.atur.assert_called_once_with(
            metode="bt", penulis="otomatis", validasi=True,
            urutan_penulis=["openrouter", "tautan"], model_openrouter="",
        )  # fmt: skip
        simpan.assert_called_once()
        bad = self.client.put(
            "/api/panel/npc",
            json={"metode": "bt", "penulis": "otomatis", "urutan_penulis": ["gpt"]},
        )
        self.assertEqual(bad.status_code, 422)

    def test_check_endpoint_rebuilds_and_checks_synchronously(self):
        with patch("controller.api.panel_npc.brain_runtime") as runtime:
            runtime.segarkan_penulis.return_value = {"penulis": "openrouter"}
            response = self.client.post("/api/panel/npc/cek-penulis")
        self.assertEqual(response.status_code, 200)
        runtime.segarkan_penulis.assert_called_once_with(latar=False)
        self.assertIn("jalur_penulis", response.json()["pilihan"])

    def test_saving_ai_link_refreshes_writer_chain(self):
        with (
            patch.object(self.panel, "save_panel_configuration"),
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

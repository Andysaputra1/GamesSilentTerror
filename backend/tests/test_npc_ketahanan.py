"""Ketahanan NPCService dan runtime otak (temuan review R5).

- penulis LLM yang lambat tidak menghilangkan kalimat bot: kalimat dikirim dari templat;
- langkah otak yang gagal sebelum pernah memutuskan tidak memblokir aksi cadangan engine;
- jejak otak tetap tersimpan (thread latar) setelah langkah selesai;
- pemuatan otak yang gagal dicoba ulang setelah jeda; path model yang salah dicatat.
"""

import asyncio
import threading
import time
import unittest
from unittest.mock import AsyncMock, Mock, patch

from app.bot import bot_controller as runtime_modul
from app.bot.bot_controller import BrainRuntime
from app.bot.nlu import NLUBersama, folder_model
from tests.palsu.arsip_palsu import arsip_bot_palsu
from tests.palsu.nlu_palsu import NLUPalsu
from app.bot.bot_controller import NPCService
from app.bot.nlg.pengaturan import tanpa_lapor
from app.services.checker_service import checker_service
from app.services.room_service import RoomService
from tests.palsu.bot_lobby import isi_kursi_bot


def runtime_siap():
    runtime = BrainRuntime()
    runtime.penulis_npc.konfigurasi.penulis = "templat"
    runtime.muat_sekarang(nlu=NLUBersama(NLUPalsu(r"curiga|vote"), "cadangan"))
    return runtime


class BrainTurnKetahananTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.runtime = runtime_siap()
        self.rooms = RoomService()
        self.room = self.rooms.create("human")
        isi_kursi_bot(self.rooms, self.room.code, "human")
        self.rooms.start(self.room.code, "human")
        self.match = self.room.match
        self.service = NPCService(Mock(emit=AsyncMock()), runtime=self.runtime)
        self.enterContext(patch("app.bot.bot_controller.room_service", self.rooms))
        self.persistence = self.enterContext(arsip_bot_palsu()).return_value
        self.enterContext(patch("app.bot.bot_controller.survey_service"))
        await self.service.prepare(self.room.code, self.match)
        self.match.begin()
        self.match.deadline = time.time() + 60
        self.otak = self.runtime.otak_bot(self.match.id, "NOX")

    async def asyncTearDown(self):
        await self.service.close()
        self.runtime.tutup()

    async def langkah(self):
        with patch("app.bot.bot_controller.asyncio.sleep", AsyncMock()):
            self.otak.sibuk = True
            await self.service.brain_turn(self.room.code, self.match, self.otak)

    async def test_slow_llm_writer_still_sends_a_template_sentence(self):
        with self.rooms.lock:
            self.match.add_message("human", "Aku curiga NOX, dia Hitman. Ayo vote NOX!")
        tulis_asli = self.runtime.tulis

        def tulis(bot, payload, konteks, pakai_llm=True, lapor=tanpa_lapor):
            if pakai_llm:
                time.sleep(1.0)  # penulis LLM menggantung melewati batas
            return tulis_asli(bot, payload, konteks, pakai_llm, lapor)

        with (
            patch.object(self.runtime, "tulis", tulis),
            patch("app.bot.bot_controller.BATAS_TULIS_DETIK", 0.2),
        ):
            await self.langkah()
        self.assertEqual(self.match.messages[-1]["sender"], "NOX")
        trace = self.persistence.record_trace.call_args.args[0]
        nlg = trace["penjelasan"]["nlg"]
        self.assertEqual(nlg["teks"], self.match.messages[-1]["message"])
        self.assertIn("melewati batas 0.2 detik", nlg["percobaan_llm"][0])
        self.assertIn(nlg["sumber"], ("templat", "templat_cadangan"))

    async def test_failed_decision_leaves_the_phase_to_engine_fallback(self):
        penanda = (self.match.round, self.match.phase, "NOX")
        with patch.object(self.runtime, "langkah", side_effect=RuntimeError("otak rusak")):
            await self.langkah()
        self.assertNotIn(penanda, self.match.npc_decisions)
        self.persistence.record_trace.assert_not_called()
        # Setelah keputusan berhasil, otak memegang fase (tunggu/abstain dihormati engine).
        await self.langkah()
        self.assertIn(penanda, self.match.npc_decisions)

    async def test_trace_is_stored_after_the_turn_without_blocking_the_loop(self):
        with self.rooms.lock:
            self.match.add_message("human", "Aku curiga NOX, dia Hitman. Ayo vote NOX!")
        await self.langkah()
        trace = self.persistence.record_trace.call_args.args[0]
        self.assertEqual(trace["match_id"], self.match.id)
        self.assertIn("penjelasan", trace)

    # Error langkah: jenis, pesan singkat tanpa path lokal atau key, tahap gagal, dan lamanya; alur live ditutup.
    async def test_failed_step_records_error_type_message_and_stage_for_the_panel(self):
        pesan = r"otak rusak di C:\Users\andy\rahasia\otak.py key=sk-or-v1-abcdef123456 /app/app/bot/x.py"
        with patch.object(self.runtime, "langkah", side_effect=RuntimeError(pesan)):
            await self.langkah()
        jejak = checker_service.list(self.room.code)[0]
        self.assertEqual(
            (jejak["stage"], jejak["error"], jejak["error_tahap"]),
            ("npc_brain_error", "RuntimeError", "berpikir"),
        )
        self.assertIn("otak rusak", jejak["error_pesan"])
        for rahasia in ("Users", "andy", "sk-or", "abcdef", "/app/app"):
            self.assertNotIn(rahasia, jejak["error_pesan"])
        self.assertLessEqual(len(jejak["error_pesan"]), 200)
        self.assertEqual((jejak["provider"], jejak["langkah"]), ("otak:fuzzy", self.otak.langkah))
        self.assertIsInstance(jejak["duration_ms"], float)
        self.assertEqual(jejak["tahap_live"], "antre")  # langkah tiruan tidak melapor tahap
        self.assertEqual(checker_service.proses_berjalan(self.room.code)["bot"], [])
        self.assertEqual(
            checker_service.hasil_langkah(self.room.code)["NOX"]["error"], "RuntimeError"
        )

    # Batas waktu keputusan: TimeoutError dicatat bersama batasnya dan tahap live saat gagal.
    async def test_decision_timeout_records_the_limit(self):
        def lambat(*_, **__):
            time.sleep(0.3)

        with patch.object(self.runtime, "langkah", side_effect=lambat), \
                patch("app.bot.bot_controller.BATAS_LANGKAH_DETIK", 0.05):  # fmt: skip
            await self.langkah()
        jejak = checker_service.list(self.room.code)[0]
        self.assertEqual(
            (jejak["error"], jejak["error_tahap"], jejak["batas_detik"]),
            ("TimeoutError", "berpikir", 0.05),
        )
        self.assertEqual(jejak["error_pesan"], "")
        self.assertGreaterEqual(jejak["duration_ms"], 50)

    # Alur live: selama LLM menulis, langkah bot tampil di tahap llm dan antrean penulis; sesudahnya jejak memuat lama
    # antre dan jeda, dan alur live kosong lagi. Intip menunggu penulis benar-benar mulai (tidak bergantung pada lama
    # berpikir di mesin uji).
    async def test_live_stage_queue_and_wait_timings_follow_the_step(self):
        with self.rooms.lock:
            self.match.add_message("human", "Aku curiga NOX, dia Hitman. Ayo vote NOX!")
        tulis_asli, terlihat, penulis_mulai = self.runtime.tulis, {}, threading.Event()

        def tulis(bot, payload, konteks, pakai_llm=True, lapor=tanpa_lapor):
            lapor("llm")
            penulis_mulai.set()
            time.sleep(0.5)
            return tulis_asli(bot, payload, konteks, pakai_llm, lapor)

        async def intip():
            self.assertTrue(await asyncio.to_thread(penulis_mulai.wait, 10))
            terlihat.update(checker_service.proses_berjalan(self.room.code))

        with patch.object(self.runtime, "tulis", tulis):
            await asyncio.gather(self.langkah(), intip())
        self.assertEqual([(b["nama"], b["tahap"]) for b in terlihat["bot"]], [("NOX", "llm")])
        penulis = terlihat["antrean"]["penulis"]
        self.assertEqual(penulis["thread"], 3)
        self.assertIn(
            ("NOX", "menulis kalimat (templat)", "dikerjakan"),
            [(t["siapa"], t["kerja"], t["status"]) for t in penulis["tugas"]],
        )
        jejak = self.persistence.record_trace.call_args.args[0]
        self.assertTrue(
            {
                "antre_otak_ms",
                "engine_ms",
                "antre_nlg_ms",
                "ketik_ms",
                "simpan_ms",
                "llm_ms",
                "nlu_ms",
            }
            <= set(jejak["timings"])
        )
        self.assertEqual(checker_service.proses_berjalan(self.room.code)["bot"], [])
        self.assertEqual(checker_service.hasil_langkah(self.room.code)["NOX"]["hasil"], "bertindak")

    # Kolom kondisi Checker: status dan hak di engine, jadwal langkah berikutnya, dan hasil langkah terakhir.
    async def test_bot_condition_for_the_panel(self):
        await self.langkah()
        self.match.players["ECHO"].hostage = True
        kondisi = {k["nama"]: k for k in self.service.kondisi_bot(self.room.code)}
        self.assertEqual(set(kondisi), {p.name for p in self.match.players.values() if p.bot})
        self.assertEqual(kondisi["ECHO"]["status"], "disandera")
        self.assertFalse(kondisi["ECHO"]["hak"]["chat"])
        nox = kondisi["NOX"]
        self.assertEqual((nox["status"], nox["fase"], nox["sibuk"]), ("aktif", "day", False))
        self.assertTrue(nox["hak"]["chat"])
        self.assertEqual(nox["terakhir"]["langkah"], self.otak.langkah)
        self.assertIsInstance(nox["berikutnya_detik"], float)
        self.assertEqual(nox["lantai"]["maks"], runtime_modul.LANTAI_MAKS)
        self.assertFalse(nox["menutup"])
        self.assertEqual(self.service.kondisi_bot("TIDAKADA"), [])

        # Sibuk dan hasil langkah ini lebih baru daripada akhir langkah sebelumnya: sedang menutup langkah (siaran,
        # arsip). Sibuk dengan hasil milik langkah yang sudah ditutup: langkah baru belum mulai.
        def kondisi_nox():
            return {k["nama"]: k for k in self.service.kondisi_bot(self.room.code)}["NOX"]

        akhir = self.otak.langkah_terakhir
        self.otak.sibuk, self.otak.langkah_terakhir = True, akhir - 60
        self.assertTrue(kondisi_nox()["menutup"])
        self.otak.langkah_terakhir = akhir
        self.assertFalse(kondisi_nox()["menutup"])
        self.assertIsNone(kondisi_nox()["berikutnya_detik"])  # sibuk: tidak ada hitung mundur
        self.otak.sibuk = False

    # _jadwal_langkah hanya memindahkan rumus: hasil _sudah_waktunya_melangkah sama dengan rumus lamanya.
    def test_schedule_refactor_keeps_the_same_decisions(self):
        def lama(otak, match, lama_fase, sekarang, urutan):
            waktu_mulai = min(2.0, match.durations[match.phase] / 6) + (urutan % 4) * 0.7
            if lama_fase < waktu_mulai or match.deadline - sekarang < 1.0:
                return False
            jeda = (
                runtime_modul.JEDA_SEGERA_DETIK
                if otak.segera
                else runtime_modul.settings.npc_step_seconds
            )
            return sekarang - otak.langkah_terakhir >= jeda

        sekarang = self.match.deadline - 30
        for segera in (False, True):
            self.otak.segera = segera
            for urutan in range(6):
                for lama_fase in (0.0, 0.5, 1.9, 2.0, 2.7, 5.0):
                    for jarak in (0.0, 0.9, 1.0, 2.99, 3.0, 10.0):
                        self.otak.langkah_terakhir = sekarang - jarak
                        argumen = (self.otak, self.match, lama_fase, sekarang, urutan)
                        self.assertEqual(
                            self.service._sudah_waktunya_melangkah(*argumen), lama(*argumen)
                        )


class PemuatanOtakTests(unittest.TestCase):
    def test_failed_load_is_retried_after_the_delay(self):
        runtime = BrainRuntime()
        self.addCleanup(runtime.tutup)
        with patch.object(runtime_modul.importlib, "import_module", side_effect=ImportError("x")):
            runtime.mulai_memuat()
            runtime._thread.join(5)
        self.assertTrue(runtime.ringkasan()["gagal"])
        gagal = runtime._thread
        runtime.mulai_memuat()  # masih dalam jeda: tidak memuat ulang
        self.assertIs(runtime._thread, gagal)
        runtime._gagal_pada = time.monotonic() - runtime_modul.JEDA_MUAT_ULANG_DETIK - 1
        with patch.object(runtime, "_muat") as muat:
            runtime.mulai_memuat()
            runtime._thread.join(5)
        muat.assert_called_once()
        self.assertIsNot(runtime._thread, gagal)
        self.assertFalse(runtime.ringkasan()["gagal"])

    def test_explicit_model_folder_that_does_not_exist_is_logged(self):
        with self.assertLogs("shadow_heist.npc_brain", "WARNING") as log:
            folder_model("C:/tidak/ada/model-intent", "intent")
        self.assertIn("tidak ditemukan", log.output[0])


if __name__ == "__main__":
    unittest.main()

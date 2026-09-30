"""Ketahanan NPCService dan runtime otak (temuan review R5).

- penulis LLM yang lambat tidak menghilangkan kalimat bot: kalimat dikirim dari templat;
- langkah otak yang gagal sebelum pernah memutuskan tidak memblokir aksi cadangan engine;
- jejak otak tetap tersimpan (thread latar) setelah langkah selesai;
- pemuatan otak yang gagal dicoba ulang setelah jeda; path model yang salah dicatat.
"""

import re
import time
import unittest
from unittest.mock import AsyncMock, Mock, patch

from services.npc_brain import runtime as runtime_modul
from services.npc_brain.runtime import BrainRuntime, NLUBersama, NLUCadangan, folder_model
from services.npc_service import NPCService
from services.room_service import RoomService


class KataKunci:
    """Pengganti SVM: kalimat berisi 'curiga' terbaca menuduh agar bot yang dituduh membela diri."""

    def predict_intent(self, teks):
        return "accusing" if re.search(r"curiga|vote", teks.casefold()) else "neutral"


def runtime_siap(metode="bt"):
    runtime = BrainRuntime()
    runtime.konfigurasi.metode = metode
    runtime.konfigurasi.penulis = "templat"
    runtime.muat_sekarang(nlu=NLUBersama(NLUCadangan(KataKunci()), "cadangan"))
    return runtime


class BrainTurnKetahananTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.runtime = runtime_siap("bt")
        self.rooms = RoomService()
        self.room = self.rooms.create("human")
        self.rooms.set_bot(self.room.code, "human", True)
        self.rooms.start(self.room.code, "human")
        self.match = self.room.match
        self.service = NPCService(Mock(emit=AsyncMock()), runtime=self.runtime)
        self.enterContext(patch("services.npc_service.room_service", self.rooms))
        self.persistence = self.enterContext(
            patch("services.npc_service.PersistenceService")
        ).return_value
        self.enterContext(patch("services.npc_service.survey_service"))
        await self.service.prepare(self.room.code, self.match)
        self.match.begin()
        self.match.deadline = time.time() + 60
        self.otak = self.runtime.otak_bot(self.match.id, "NOX")

    async def asyncTearDown(self):
        await self.service.close()
        self.runtime.tutup()

    async def langkah(self):
        with patch("services.npc_service.asyncio.sleep", AsyncMock()):
            self.otak.sibuk = True
            await self.service.brain_turn(self.room.code, self.match, self.otak)

    async def test_slow_llm_writer_still_sends_a_template_sentence(self):
        with self.rooms.lock:
            self.match.add_message("human", "Aku curiga NOX, dia Hitman. Ayo vote NOX!")
        tulis_asli = self.runtime.tulis

        def tulis(bot, payload, konteks, pakai_llm=True):
            if pakai_llm:
                time.sleep(1.0)  # penulis LLM menggantung melewati batas
            return tulis_asli(bot, payload, konteks, pakai_llm)

        with (
            patch.object(self.runtime, "tulis", tulis),
            patch("services.npc_service.BATAS_TULIS_DETIK", 0.2),
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

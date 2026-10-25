"""Simulasi panel: engine, otak, dan NLU yang sama dengan room asli, tanpa room atau database."""

import asyncio
import unittest
from unittest.mock import patch

from app.services import simulasi_service as modul
from tests.test_npc_brain import runtime_siap


class SimulasiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runtime = runtime_siap()

    @classmethod
    def tearDownClass(cls):
        cls.runtime.tutup()

    def setUp(self):
        patcher = patch.object(modul, "brain_runtime", self.runtime)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.layanan = modul.SimulasiService()
        self.awal = self.layanan.mulai("Andy Saputra", ["fuzzy", "utility", "bt"])

    def test_chat_admin_dibaca_nlu_lalu_setiap_bot_melangkah_dengan_waktu_tiap_tahap(self):
        bots = [p for p in self.awal["pemain"] if not p["manusia"]]
        self.assertEqual([(p["nama"], p["metode"]) for p in bots],
                         [("NOX", "fuzzy"), ("ECHO", "utility"), ("VEIL", "bt")])  # fmt: skip
        teks = "aku curiga NOX itu hitman"
        hasil = asyncio.run(self.layanan.jalankan(self.awal["id"], "kirim", teks, 3))
        chat = hasil["jejak"][0]
        self.assertEqual((chat["sender"], chat["message"]), ("Andy Saputra", teks))
        self.assertEqual(chat["nlu"]["intent"], "offend")
        self.assertIn("NOX", [t["pemain"] for t in chat["nlu"]["target"]])
        langkah = [j for j in hasil["jejak"] if j.get("ringkas")]
        self.assertEqual([j["sender"] for j in langkah], ["ECHO", "NOX", "VEIL"])
        for jejak in langkah:
            self.assertTrue({"nlu_ms", "logika_ms", "penjelasan_ms"} <= set(jejak["timings"]))
            self.assertIn("keputusan", jejak["penjelasan"])
        # Bot pertama membaca chat admin dengan IndoBERT (di sini NLU cadangan) di langkahnya sendiri.
        dibaca = langkah[0]["penjelasan"]["nlu_dibaca"]
        self.assertEqual([(c["teks"], c["intent"]) for c in dibaca], [(teks, "offend")])
        self.assertEqual(hasil["detik"], 5.0)  # mulai detik 2, lalu satu putaran 3 detik
        # Flowchart live: setelah selesai semua pemain berada di tahap "selesai".
        progres = self.layanan.progres(self.awal["id"])
        self.assertFalse(progres["berjalan"])
        self.assertEqual(set(progres["progres"]), {"Andy Saputra", "NOX", "ECHO", "VEIL"})
        self.assertEqual({p["tahap"] for p in progres["progres"].values()}, {"selesai"})

    def test_fase_berikutnya_diselesaikan_engine_lalu_bot_melangkah_di_fase_baru(self):
        hasil = asyncio.run(self.layanan.jalankan(self.awal["id"], "fase"))
        self.assertEqual(hasil["fase"], "night")
        self.assertFalse(hasil["bisa_chat"])
        self.assertIn("Malam tiba", " ".join(j["message"] for j in hasil["jejak"]))
        with self.assertRaises(ValueError):  # malam: chat terkunci seperti di room asli
            asyncio.run(self.layanan.jalankan(self.awal["id"], "kirim", "halo", 3))

    def test_simulasi_terlama_dibuang(self):
        for _ in range(modul.MAKS_SIMULASI):
            self.layanan.mulai("A", ["bt", "bt", "bt"])
        with self.assertRaises(KeyError):
            asyncio.run(self.layanan.jalankan(self.awal["id"], "jalan"))


if __name__ == "__main__":
    unittest.main()

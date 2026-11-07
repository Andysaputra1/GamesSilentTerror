"""Kode asli flowchart: setiap kotak menunjuk kode yang ada dan setiap penanda baris inti ditemukan.

Gagal di sini biasanya berarti notebook diekspor ulang dan nama fungsi atau baris intinya berubah.
"""

import re
import unittest
from pathlib import Path

from app.controllers.panel_npc import KODE_ALUR, kode_node


class KodeAlurTests(unittest.TestCase):
    def test_kotak_flowchart_panel_sama_dengan_daftar_kode(self):
        panel = (Path(__file__).parents[1] / "public/panel/panel.js").read_text(encoding="utf-8")
        blok = panel[panel.index("const ALUR_AI = {") : panel.index("const BARIS_ALUR")]
        self.assertEqual(set(re.findall(r"^  (\w+): \{$", blok, re.M)), set(KODE_ALUR))

    def test_metode_arsip_tidak_punya_kotak_atau_kode(self):
        for node in ("ua", "ua_1", "ua_2", "ua_3", "ua_4", "bt", "bt_1", "bt_2", "bt_3", "bt_4"):
            with self.subTest(node=node), self.assertRaises(KeyError):
                kode_node(node)
        modul = {m for daftar in KODE_ALUR.values() for m, _, _ in daftar}
        self.assertFalse({m for m in modul if m.endswith(("otak_bt", "otak_utility"))})

    def test_setiap_potongan_ditemukan_dan_penandanya_cocok(self):
        for node in KODE_ALUR:
            for potongan in kode_node(node):
                with self.subTest(node=node, kode=potongan["nama"]):
                    self.assertEqual(potongan["hilang"], [])
                    self.assertTrue(potongan["baris"])
                    self.assertTrue(potongan["berkas"].startswith("backend/"))

    def test_parameter_output_dan_baris_inti_ditandai(self):
        langkah = kode_node("sinkron")[0]
        self.assertEqual(langkah["nama"], "bot_controller.BrainRuntime.langkah")
        self.assertEqual([p["nama"] for p in langkah["parameter"]],
                         ["bot", "snapshot", "sekarang", "selalu_jelaskan", "lapor"])  # fmt: skip
        self.assertEqual(langkah["parameter"][3]["bawaan"], "False")
        self.assertEqual(langkah["baris"][0]["jenis"], "param")
        jenis = {b["teks"].strip(): b["jenis"] for b in langkah["baris"]}
        self.assertEqual(jenis["return view, keputusan, konteks"], "output")
        self.assertEqual(jenis["keputusan = modul.putuskan(bot.ingatan, view)"], "inti")
        # Fungsi ber-lru_cache dan konstanta modul juga terbaca dari sumber aslinya.
        nama = {p["nama"]: p for p in kode_node("fl_3")}
        self.assertIn(
            "simulasi.compute()",
            " ".join(b["teks"] for b in nama["fuzzy._fuzzy_tersimpan"]["baris"]),
        )
        self.assertTrue(nama["fuzzy.HIERARKI"]["konstanta"])
        with self.assertRaises(KeyError):
            kode_node("os.system")


if __name__ == "__main__":
    unittest.main()

"""Kode asli flowchart: setiap kotak menunjuk kode yang ada dan setiap penanda baris inti ditemukan.

Gagal di sini biasanya berarti notebook diekspor ulang dan nama fungsi atau baris intinya berubah.
"""

import re
import unittest
from pathlib import Path

from app.controller.api.panel_npc import KODE_ALUR, kode_node


class KodeAlurTests(unittest.TestCase):
    def test_kotak_flowchart_panel_sama_dengan_daftar_kode(self):
        panel = (Path(__file__).parents[1] / "public/panel/panel.js").read_text(encoding="utf-8")
        blok = panel[panel.index("const ALUR_AI = {") : panel.index("const BARIS_ALUR")]
        self.assertEqual(set(re.findall(r"^  (\w+): \{$", blok, re.M)), set(KODE_ALUR))

    def test_setiap_potongan_ditemukan_dan_penandanya_cocok(self):
        for node in KODE_ALUR:
            for potongan in kode_node(node):
                with self.subTest(node=node, kode=potongan["nama"]):
                    self.assertEqual(potongan["hilang"], [])
                    self.assertTrue(potongan["baris"])
                    self.assertTrue(potongan["berkas"].startswith("backend/"))

    def test_parameter_output_dan_baris_inti_ditandai(self):
        skor = kode_node("ua_3")[0]
        self.assertEqual(skor["nama"], "otak_utility.skor_iaus")
        self.assertEqual([p["nama"] for p in skor["parameter"]], ["nilai", "bobot"])
        self.assertEqual(skor["parameter"][1]["bawaan"], "1.0")
        jenis = {b["teks"].strip(): b["jenis"] for b in skor["baris"]}
        self.assertEqual(jenis["def skor_iaus(nilai, bobot=1.0):"], "param")
        self.assertEqual(jenis["return bobot * skor"], "output")
        self.assertEqual(jenis["modifikasi = 1 - 1 / len(nilai)"], "inti")
        # Fungsi ber-lru_cache dan konstanta modul juga terbaca dari sumber aslinya.
        nama = {p["nama"]: p for p in kode_node("fl_3")}
        self.assertIn(
            "simulasi.compute()",
            " ".join(b["teks"] for b in nama["otak_fuzzy._fuzzy_tersimpan"]["baris"]),
        )
        self.assertTrue(nama["otak_fuzzy.HIERARKI"]["konstanta"])
        with self.assertRaises(KeyError):
            kode_node("os.system")


if __name__ == "__main__":
    unittest.main()

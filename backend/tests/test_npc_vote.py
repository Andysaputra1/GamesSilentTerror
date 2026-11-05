"""Vote dan ajak vote otak NPC (Fase 6): kalimat ajak vote, vote paksa, vote Hitman, dan pindah suara saat waktu tambahan."""

import unittest

from app.module.npc_brain.generated import nlg


class AjakVoteTests(unittest.TestCase):
    # Kalimat khusus ajak vote baru ada di Fase 8, jadi sampai itu templat tuduh harus tetap lolos pemeriksa aturan.
    def test_vote_invitation_plans_pass_the_rule_checker(self):
        for jenis in ("ajak_pindah", "ajak_menyatukan", "jelaskan_vote"):
            with self.subTest(jenis=jenis):
                rencana = {"pembicara": "NOX", "aksi": "tuduh", "jenis": jenis, "intent": "offend",
                           "target": "ECHO", "klaim": False, "bukti": ["ECHO aneh dari tadi."]}  # fmt: skip
                konteks = {"roster": ["NOX", "ECHO", "VEIL"], "chat_terbaru": []}
                hasil = nlg.tulis_pesan(rencana, konteks, None, "santai")
                self.assertEqual(hasil["pelanggaran"], [])
                self.assertIn("ECHO", hasil["teks"])


if __name__ == "__main__":
    unittest.main()

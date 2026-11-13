import threading
import time
import unittest

from app.services.checker_service import (
    MAKS_ANTREAN,
    MAKS_ROOM_LIVE,
    PRATINJAU_MAKS,
    AntreanThread,
    CheckerService,
    EksekutorTercatat,
    antrean_thread,
    label_antrean,
)


class CheckerTests(unittest.TestCase):
    # TES CHECKER: periksa batas 100 trace, pemisahan ruangan, dan snapshot yang tidak mengubah data internal.
    def test_history_is_bounded_scoped_and_copied(self):
        checker = CheckerService()
        for index in range(105):
            checker.begin("ABC123", "alice", str(index))
        self.assertEqual(len(checker.list("ABC123")), 100)
        self.assertEqual(checker.list("ABC123")[0]["message"], "104")
        self.assertEqual(checker.list("FFFFFF"), [])
        snapshot = checker.list("ABC123")
        snapshot[0]["message"] = "changed"
        self.assertEqual(checker.list("ABC123")[0]["message"], "104")

    # Jumlah room di memori juga dibatasi: room yang paling lama tidak aktif dilepas lebih dulu.
    def test_live_rooms_are_bounded_and_active_room_is_kept(self):
        checker = CheckerService()
        checker.begin("AKTIF0", "alice", "awal")
        for index in range(MAKS_ROOM_LIVE):
            checker.begin(f"R{index:05d}", "bob", "x")
            checker.begin("AKTIF0", "alice", str(index))  # room yang terus dipakai tidak dilepas
        self.assertEqual(len(checker.rooms), MAKS_ROOM_LIVE)
        self.assertEqual(checker.list("R00000"), [])
        self.assertEqual(len(checker.list("AKTIF0")), MAKS_ROOM_LIVE + 1)


class LangkahLiveTests(unittest.TestCase):
    # Tahap langkah bot tercatat berurutan; laporan NLG yang tertinggal sesudah bot mengetik tidak memundurkan tahap.
    def test_stages_are_timed_and_late_writer_reports_are_ignored(self):
        checker = CheckerService()
        langkah = checker.mulai_langkah("ABC123", "m1", "NOX", 4)
        for tahap in (
            "nlu",
            "logika",
            "penjelasan",
            "engine",
            "antre_nlg",
            "llm",
            "aturan",
            "ketik",
        ):
            langkah.lapor(tahap)
        langkah.lapor("llm")  # thread LLM yang tertinggal sesudah batas waktu
        lihat = checker.proses_berjalan("ABC123")["bot"][0]
        self.assertEqual((lihat["nama"], lihat["langkah"], lihat["tahap"]), ("NOX", 4, "ketik"))
        self.assertEqual(
            set(lihat["lama"]),
            {"antre", "nlu", "logika", "penjelasan", "engine", "antre_nlg", "llm", "aturan"},
        )
        self.assertEqual(
            set(langkah.waktu_tunggu()), {"antre_otak_ms", "engine_ms", "antre_nlg_ms", "ketik_ms"}
        )
        checker.selesai_langkah(langkah, "bertindak")
        langkah.lapor("simpan")  # sesudah selesai: diabaikan
        self.assertEqual(langkah.lihat()["tahap"], "ketik")
        self.assertEqual(checker.proses_berjalan("ABC123")["bot"], [])
        hasil = checker.hasil_langkah("ABC123")["NOX"]
        self.assertEqual(
            (hasil["hasil"], hasil["langkah"], hasil["match_id"]), ("bertindak", 4, "m1")
        )
        checker.selesai_langkah(langkah, "bertindak")  # aman dipanggil dua kali

    # Chat manusia yang belum selesai (tanpa duration_ms) ikut sebagai data live beserta lama berjalannya.
    def test_unfinished_human_chats_are_live(self):
        checker = CheckerService()
        selesai = checker.begin("ABC123", "alice", "sudah")
        selesai.update(stage="delivered", duration_ms=40.0)
        ditolak = checker.begin("ABC123", "alice", "ditolak")
        ditolak.update(stage="discarded_state_changed")
        berjalan = checker.begin("ABC123", "alice", "masih diproses")
        berjalan.update(stage="delivered", timings={"persistence_ms": 12.0})
        chat = checker.proses_berjalan("ABC123")["chat"]
        self.assertEqual([c["message"] for c in chat], ["masih diproses"])
        self.assertGreaterEqual(chat[0]["berjalan_ms"], 0)


class AntreanThreadTests(unittest.TestCase):
    # Eksekutor mencatat antrean (urutan FIFO, label, pratinjau pendek) tanpa mengubah hasil; entri selesai dibuang.
    def test_executor_records_queue_order_labels_and_removes_finished_work(self):
        eksekutor = EksekutorTercatat("uji-otak", 1, thread_name_prefix="uji")
        self.addCleanup(eksekutor.shutdown, wait=True, cancel_futures=True)
        lepas = threading.Event()
        with label_antrean("ROOM01", "NOX", "berpikir (NLU + Fuzzy)"):
            pertama = eksekutor.submit(lambda: lepas.wait(5) and "selesai")
        with label_antrean("LAIN99", "Kimberly", "IndoBERT membaca chat", "aku curiga " + "x" * 80):
            kedua = eksekutor.submit(lambda: 2)
        tanpa_label = eksekutor.submit(lambda: 3)
        for _ in range(100):
            tugas = antrean_thread.lihat()["uji-otak"]["tugas"]
            if tugas and tugas[0]["status"] == "dikerjakan":
                break
            time.sleep(0.01)
        self.assertEqual(antrean_thread.lihat()["uji-otak"]["thread"], 1)
        self.assertEqual(
            [(t["urutan"], t["siapa"], t["status"]) for t in tugas],
            [(1, "NOX", "dikerjakan"), (2, "Kimberly", "menunggu"), (3, None, "menunggu")],
        )
        self.assertEqual(tugas[1]["room"], "LAIN99")
        self.assertEqual(len(tugas[1]["teks"]), PRATINJAU_MAKS + 1)  # dipotong + "…"
        self.assertEqual(tugas[2]["kerja"], "pekerjaan tanpa label")
        lepas.set()
        self.assertEqual(
            (pertama.result(5), kedua.result(5), tanpa_label.result(5)), ("selesai", 2, 3)
        )
        for _ in range(100):
            if not antrean_thread.lihat()["uji-otak"]["tugas"]:
                break
            time.sleep(0.01)
        self.assertEqual(antrean_thread.lihat()["uji-otak"]["tugas"], [])

    # Pekerjaan yang dibatalkan sebelum mulai juga keluar dari antrean; registri dibatasi MAKS_ANTREAN.
    def test_cancelled_work_leaves_and_registry_is_bounded(self):
        eksekutor = EksekutorTercatat("uji-batal", 1)
        lepas = threading.Event()
        eksekutor.submit(lepas.wait, 5)
        menunggu = eksekutor.submit(lambda: 1)
        self.assertTrue(menunggu.cancel())
        self.assertEqual(len(antrean_thread.lihat()["uji-batal"]["tugas"]), 1)
        lepas.set()
        eksekutor.shutdown(wait=True)
        registri = AntreanThread()
        for _ in range(MAKS_ANTREAN + 5):
            registri.masuk("x", None)
        self.assertEqual(len(registri.tugas), MAKS_ANTREAN)

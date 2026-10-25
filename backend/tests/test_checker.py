import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.controller.api.rooms import router
from app.services.checker_service import MAKS_ROOM_LIVE, CheckerService


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

    def test_old_public_checker_is_retired(self):
        app = FastAPI()
        app.include_router(router)
        with TestClient(app) as client:
            self.assertEqual(client.get("/api/rooms/ABC123/checker").status_code, 410)

import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient
from controller.api.rooms import router
from services.checker_service import CheckerService


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

    def test_old_public_checker_is_retired(self):
        app = FastAPI()
        app.include_router(router)
        with TestClient(app) as client:
            self.assertEqual(client.get("/api/rooms/ABC123/checker").status_code, 410)

"""Survei akhir: pertanyaan dan skala dari database, validasi jawaban, dan satu kali kirim per pertandingan."""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import FastAPI, Header
from fastapi.testclient import TestClient

from controller.api.survey import router
from controller.middleware.auth import require_authenticated_user
from services.room_service import RoomService
from services.survey_service import (
    SurveyAlreadySubmitted,
    SurveyService,
    validate_answers,
    validate_question,
)


def question(id_, kind="stars", required=True, **extra):
    return {"id": id_, "code": f"q{id_}", "prompt": f"Pertanyaan {id_}", "kind": kind,
            "scale_min": 1, "scale_max": 6, "label_min": "Buruk", "label_max": "Sangat baik",
            "options": [], "required": required, "active": True, "position": id_, **extra}  # fmt: skip


class FakeQueries:
    """Pengganti models.survey_queries: menyimpan pertanyaan dan jawaban di memori."""

    def __init__(self):
        self.questions = [question(1), question(2, "scale", scale_min=0, scale_max=10),
                          question(3, "choice", options=["Fuzzy", "Utility"]),
                          question(4, "text", required=False)]  # fmt: skip
        self.answers = []
        self.bots = []

    def list_questions(self, db, active_only=True):
        return [dict(q) for q in self.questions if q["active"] or not active_only]

    def count_answers(self, db, match_id, username):
        return sum(a["match_id"] == match_id and a["username"] == username for a in self.answers)

    def insert_answer(self, db, row):
        self.answers.append(row)

    def insert_question(self, db, data):
        self.questions.append({"id": len(self.questions) + 1, **data})
        return len(self.questions)

    def update_question(self, db, question_id, data):
        for q in self.questions:
            if q["id"] == question_id:
                q.update(data)

    def record_match_bot(self, db, row):
        self.bots.append(row)


class ValidationTests(unittest.TestCase):
    def test_question_rules(self):
        ok = validate_question({"code": "Keseruan", "prompt": "  Seberapa   seru? ", "kind": "stars",
                                "scale_min": 1, "scale_max": 6, "label_min": "Bosan",
                                "label_max": "Seru"})  # fmt: skip
        self.assertEqual((ok["code"], ok["prompt"]), ("keseruan", "Seberapa seru?"))
        bad = [
            {"code": "x", "prompt": "Valid?", "kind": "stars"},
            {"code": "ok_code", "prompt": "Valid?", "kind": "stars", "scale_min": 0},
            {
                "code": "ok_code",
                "prompt": "Valid?",
                "kind": "scale",
                "scale_min": 5,
                "scale_max": 5,
            },
            {"code": "ok_code", "prompt": "Valid?", "kind": "scale", "scale_max": 11},
            {"code": "ok_code", "prompt": "Valid?", "kind": "choice", "options": ["satu"]},
            {"code": "ok_code", "prompt": "Valid?", "kind": "choice", "options": ["a", "a"]},
            {"code": "ok_code", "prompt": "Valid?", "kind": "emoji"},
        ]
        for data in bad:
            with self.assertRaises(ValueError, msg=data):
                validate_question(data)

    def test_answers_follow_each_question_scale_and_kind(self):
        questions = {q["id"]: q for q in FakeQueries().questions}
        rows = validate_answers(questions, [
            {"question_id": 1, "value": 6}, {"question_id": 2, "value": 0},
            {"question_id": 3, "text": "Utility"},
        ])  # fmt: skip
        self.assertEqual([(q["id"], v, t) for q, v, t in rows],
                         [(1, 6, None), (2, 0, None), (3, None, "Utility")])  # fmt: skip
        invalid = [
            [{"question_id": 1, "value": 7}, {"question_id": 2, "value": 0}, {"question_id": 3, "text": "Fuzzy"}],
            [{"question_id": 1, "value": 0}, {"question_id": 2, "value": 0}, {"question_id": 3, "text": "Fuzzy"}],
            [{"question_id": 1, "value": 3}, {"question_id": 3, "text": "Fuzzy"}],
            [{"question_id": 1, "value": 3}, {"question_id": 2, "value": 1}, {"question_id": 3, "text": "BT"}],
            [{"question_id": 99, "value": 3}],
            [{"question_id": 1, "value": 3}, {"question_id": 1, "value": 4}],
            [{"question_id": 1, "value": True}, {"question_id": 2, "value": 1}, {"question_id": 3, "text": "Fuzzy"}],
        ]  # fmt: skip
        for answers in invalid:
            with self.assertRaises(ValueError, msg=answers):
                validate_answers(questions, answers)


class SurveyServiceTests(unittest.TestCase):
    def setUp(self):
        self.rooms = RoomService()
        self.room = self.rooms.create("alice")
        self.rooms.join(self.room.code, "bob")
        self.rooms.set_bot(self.room.code, "alice", True)
        self.rooms.start(self.room.code, "alice")
        self.match = self.room.match
        self.match.begin()
        self.fake = FakeQueries()
        self.enterContext(patch("services.survey_service.room_service", self.rooms))
        self.enterContext(patch("services.survey_service.queries", self.fake))
        self.enterContext(patch("services.survey_service.PersistenceService._run",
                                side_effect=lambda operation: operation(None)))  # fmt: skip
        self.service = SurveyService()
        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[require_authenticated_user] = lambda x_user=Header(
            "alice"
        ): SimpleNamespace(username=x_user)
        self.client = self.enterContext(TestClient(app))

    def answers(self):
        return [{"question_id": 1, "value": 5}, {"question_id": 2, "value": 7},
                {"question_id": 3, "text": "Fuzzy"}, {"question_id": 4, "text": "Seru!"}]  # fmt: skip

    def finish(self):
        hitman = next(p for p in self.match.players.values() if p.role == "hitman")
        hitman.alive = False
        self.match.check_winner()

    def test_survey_only_after_match_finished_and_only_for_humans(self):
        with self.assertRaises(ValueError):
            self.service.status(self.room.code, "alice")
        self.finish()
        status = self.service.status(self.room.code, "alice")
        self.assertFalse(status["submitted"])
        self.assertEqual(
            [q["kind"] for q in status["questions"]], ["stars", "scale", "choice", "text"]
        )
        self.assertNotIn("active", status["questions"][0])  # pemain hanya menerima kolom publik
        bot = next(p.name for p in self.match.players.values() if p.bot)
        self.rooms.rooms[self.room.code].members.append(bot)  # bot tidak pernah bisa mengisi
        with self.assertRaises(ValueError):
            self.service.status(self.room.code, bot)

    def test_submit_once_with_question_snapshot_and_result_context(self):
        self.finish()
        result = self.service.submit(self.room.code, "alice", self.match.id, self.answers())
        self.assertEqual(result, {"submitted": True, "answers": 4})
        saved = self.fake.answers[0]
        self.assertEqual(saved["question_snapshot"]["label_max"], "Sangat baik")
        # Hitman dieksekusi: warga menang, jadi hasil alice bergantung pada role acaknya.
        alice_hitman = self.match.players["alice"].role == "hitman"
        self.assertEqual(saved["outcome"], "lost" if alice_hitman else "won")
        self.assertEqual(saved["team"], "hitman" if alice_hitman else "civilians")
        with self.assertRaises(SurveyAlreadySubmitted):
            self.service.submit(self.room.code, "alice", self.match.id, self.answers())
        with self.assertRaises(ValueError):
            self.service.submit(self.room.code, "bob", "stale-match", self.answers())

    def test_http_endpoints_map_errors(self):
        endpoint = f"/api/rooms/{self.room.code}/survey"
        self.assertEqual(self.client.get(endpoint).status_code, 400)  # belum selesai
        self.finish()
        self.assertEqual(self.client.get(endpoint).json()["submitted"], False)
        body = {"match_id": self.match.id, "answers": self.answers()}
        self.assertEqual(self.client.post(endpoint, json=body).status_code, 200)
        self.assertEqual(self.client.post(endpoint, json=body).status_code, 409)
        bad = {"match_id": self.match.id, "answers": [{"question_id": 1, "value": 99}]}
        self.assertEqual(
            self.client.post(endpoint, json=bad, headers={"x-user": "bob"}).status_code, 422
        )

    def test_panel_question_management_keeps_codes_unique(self):
        created = self.service.create_question(
            {"code": "strategi", "prompt": "Strategi bot masuk akal?", "kind": "scale",
             "scale_min": 1, "scale_max": 5, "label_min": "Tidak", "label_max": "Sangat"}
        )  # fmt: skip
        self.assertEqual(created["scale_max"], 5)
        with self.assertRaises(ValueError):
            self.service.create_question(
                {"code": "strategi", "prompt": "Duplikat?", "kind": "text"}
            )
        with self.assertRaises(LookupError):
            self.service.update_question(
                999, {"code": "baru", "prompt": "Tidak ada?", "kind": "text"}
            )
        self.service.update_question(1, {**question(1), "code": "q1", "active": False})
        self.assertNotIn(1, [q["id"] for q in self.fake.list_questions(None)])

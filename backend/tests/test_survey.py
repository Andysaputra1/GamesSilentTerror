"""Survei akhir: pertanyaan dan skala dari database, validasi jawaban, dan satu kali kirim per pertandingan."""

import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import FastAPI, Header
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from controller.api.panel import require_panel
from controller.api.survey import router
from controller.middleware.auth import require_authenticated_user
from models import survey_queries
from services.persistence_service import PersistenceError
from services.room_service import RoomService
from services.survey_service import (
    BERLAKU_SELESAI_DETIK,
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

    # Pemain yang keluar room setelah pertandingan selesai tetap bisa mengirim survei (registri memori).
    def test_player_who_left_the_room_can_still_submit_until_the_window_ends(self):
        self.finish()
        self.enterContext(patch("services.survey_service.survey_service", self.service))
        self.rooms.leave(self.room.code, "alice")
        self.rooms.leave(self.room.code, "bob")
        self.assertNotIn(self.room.code, self.rooms.rooms)  # room sudah dibersihkan
        status = self.service.status(self.room.code, "alice")
        self.assertEqual((status["match_id"], status["submitted"]), (self.match.id, False))
        result = self.service.submit(self.room.code, "alice", self.match.id, self.answers())
        self.assertEqual(result["answers"], 4)
        self.assertEqual(self.fake.answers[0]["role"], self.match.players["alice"].role)
        with self.assertRaises(ValueError):
            self.service.status(self.room.code, "mallory")  # bukan peserta
        with self.assertRaises(ValueError):
            self.service.submit(self.room.code, "bob", "match-lain", self.answers())
        nanti = time.monotonic() + BERLAKU_SELESAI_DETIK + 1
        with patch("services.survey_service.time.monotonic", return_value=nanti):
            with self.assertRaises(ValueError):
                self.service.status(self.room.code, "bob")

    # Dua kiriman bersamaan: yang kedua melanggar UNIQUE → "sudah dikirim" (409), bukan 503.
    def test_concurrent_duplicate_submit_is_reported_as_already_submitted(self):
        self.finish()

        def gagal(kode):
            raise PersistenceError("fixture") from IntegrityError(
                "INSERT", {}, Exception(kode, "fixture")
            )

        with patch("services.survey_service.PersistenceService._run",
                   side_effect=lambda operation: gagal(1062)):  # fmt: skip
            with self.assertRaises(SurveyAlreadySubmitted):
                self.service.submit(self.room.code, "alice", self.match.id, self.answers())
            body = {"match_id": self.match.id, "answers": self.answers()}
            response = self.client.post(f"/api/rooms/{self.room.code}/survey", json=body)
            self.assertEqual(response.status_code, 409)
        with patch("services.survey_service.PersistenceService._run",
                   side_effect=lambda operation: gagal(1452)):  # fmt: skip
            with self.assertRaises(PersistenceError):  # pelanggaran lain tetap error database
                self.service.submit(self.room.code, "alice", self.match.id, self.answers())

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


class SurveyExportTests(unittest.TestCase):
    def setUp(self):
        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[require_panel] = lambda: "fixture-token"
        self.client = TestClient(app)

    # CSV: UTF-8 dengan BOM, kolom tetap, dan nilai persis (tanpa escape) seperti CSV riwayat chat.
    def test_csv_has_bom_fixed_columns_and_exact_values(self):
        rows = [{"created_at": "2026-09-30 10:00:00", "match_id": "m1", "room_code": "ABC123",
                 "username": "alice", "role": "spy", "team": "civilians", "outcome": "won",
                 "code": "saran", "question_snapshot": '{"prompt": "Saran untuk game?"}',
                 "value_number": None, "value_text": "=1+1 seru banget 👍",
                 "bots": "NOX:fuzzy:santai"}]  # fmt: skip
        with patch("controller.api.survey.survey_service.export_rows", return_value=rows):
            response = self.client.get("/api/panel/survey/responses.csv")
        self.assertEqual(response.status_code, 200)
        body = response.content.decode("utf-8")
        self.assertTrue(body.startswith("﻿"))
        header, line = body.lstrip("﻿").splitlines()[:2]
        self.assertEqual(header, "created_at,match_id,room_code,username,role,team,outcome,code,"
                                 "prompt,value_number,value_text,bots")  # fmt: skip
        self.assertIn(",Saran untuk game?,,=1+1 seru banget 👍,NOX:fuzzy:santai", line)


class SurveySummarySqlTests(unittest.TestCase):
    """SQL ringkasan dijalankan sungguhan (SQLite) agar semantik per metode teruji."""

    def test_each_answer_counts_once_by_match_method_or_mixed(self):
        engine = create_engine("sqlite://")
        with Session(engine) as database:
            database.execute(text("CREATE TABLE match_bots (match_id TEXT, method TEXT)"))
            database.execute(text(
                "CREATE TABLE survey_responses (match_id TEXT, question_id INT, value_number INT, "
                "value_text TEXT)"
            ))  # fmt: skip
            bots = [
                ("tunggal", "fuzzy"),
                ("tunggal", "fuzzy"),
                ("campur", "fuzzy"),
                ("campur", "bt"),
            ]
            for match_id, method in bots:
                database.execute(text("INSERT INTO match_bots VALUES (:m, :method)"),
                                 {"m": match_id, "method": method})  # fmt: skip
            for match_id, nilai in [("tunggal", 5), ("campur", 3), ("tanpa_bot", 1)]:
                database.execute(text("INSERT INTO survey_responses VALUES (:m, 1, :v, NULL)"),
                                 {"m": match_id, "v": nilai})  # fmt: skip
            hasil = survey_queries.summary(database)
        per_metode = {row["method"]: (row["n"], row["rata"]) for row in hasil["per_method"]}
        self.assertEqual(per_metode, {"fuzzy": (1, 5.0), "campuran": (1, 3.0)})

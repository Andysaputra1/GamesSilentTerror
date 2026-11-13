"""Survei akhir: pertanyaan dan skala dari database, validasi jawaban, dan satu kali kirim per pertandingan."""

import csv
import io
import time
import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import FastAPI, Header
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.controllers.panel import require_panel
from app.controllers.survey import router
from app.middleware.auth import require_authenticated_user
from app.models import survey_queries
from app.services.persistence_service import PersistenceError
from app.services.room_service import RoomService
from app.services.survey_service import (
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
        self.participants = []

    # Sama dengan SQL asli: ORDER BY position, id.
    def list_questions(self, db, active_only=True):
        urut = sorted(self.questions, key=lambda q: (q["position"], q["id"]))
        return [dict(q) for q in urut if q["active"] or not active_only]

    def update_positions(self, db, rows):
        posisi = {row["id"]: row["position"] for row in rows}
        for q in self.questions:
            q["position"] = posisi.get(q["id"], q["position"])

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

    def clear_responses(self, db):
        deleted = len(self.answers)
        self.answers, self.participants = [], []
        return deleted

    def count_question_answers(self, db, question_id):
        return sum(a["question_id"] == question_id for a in self.answers)

    def delete_question(self, db, question_id):
        self.questions = [q for q in self.questions if q["id"] != question_id]

    # Tabel match_participants tiruan (arsip peserta pertandingan selesai).
    def record_participants(self, db, rows):
        for row in rows:
            if not any((p["match_id"], p["username"]) == (row["match_id"], row["username"])
                       for p in self.participants):  # fmt: skip
                self.participants.append({**row, "finished_at": datetime(2026, 10, 20, 7, 0)})

    def participant(self, db, room_code, username, match_id):
        cocok = [p for p in self.participants if (p["room_code"], p["username"]) == (room_code, username)
                 and match_id in (None, p["match_id"])]  # fmt: skip
        return (
            {k: cocok[-1][k] for k in ("match_id", "room_code", "role", "team", "outcome")}
            if cocok
            else None
        )

    def pending_surveys(self, db, username, limit=20):
        return [p for p in self.participants if p["username"] == username
                and not self.count_answers(db, p["match_id"], username)][:limit]  # fmt: skip


class ValidationTests(unittest.TestCase):
    def test_question_rules(self):
        ok = validate_question({"code": "Keseruan", "prompt": "  Seberapa   seru? ", "kind": "stars",
                                "scale_min": 1, "scale_max": 6, "label_min": "Bosan",
                                "label_max": "Seru"})  # fmt: skip
        self.assertEqual((ok["code"], ok["prompt"]), ("keseruan", "Seberapa seru?"))
        # Posisi tidak pernah diambil dari isian panel: server yang menentukannya.
        self.assertNotIn("position", validate_question({**ok, "position": 999}))
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

    def test_other_choice_requires_details_and_respects_text_limit(self):
        q = question(1, "choice", required=False,
                     options=["Lebih cepat", "Lebih berempati", "Lainnya"])  # fmt: skip
        self.assertEqual(validate_answers({1: q}, []), [])
        for answer, expected in (
            ("Lebih cepat", "Lebih cepat"),
            ("Lebih berempati", "Lebih berempati"),
            ("Lainnya:  Lebih   pintar", "Lainnya: Lebih pintar"),
            ("Lainnya: " + "a" * 991, "Lainnya: " + "a" * 991),
        ):
            with self.subTest(answer=answer):
                rows = validate_answers({1: q}, [{"question_id": 1, "text": answer}])
                self.assertEqual(rows, [(q, None, expected)])
        for answer in ("Lainnya", "Lainnya:  ", "Lainnya: " + "a" * 992, "Lebih pintar"):
            with self.subTest(answer=answer), self.assertRaises(ValueError):
                validate_answers({1: q}, [{"question_id": 1, "text": answer}])

        # Isian bebas tidak boleh meloloskan jawaban di pertanyaan pilihan biasa.
        q["options"] = ["Lebih cepat", "Lebih berempati"]
        with self.assertRaises(ValueError):
            validate_answers({1: q}, [{"question_id": 1, "text": "Lainnya: Lebih pintar"}])


class SurveyServiceTests(unittest.TestCase):
    def setUp(self):
        # Profil akun tidak terkait survei; hindari ketergantungan pada database nyata.
        self.enterContext(
            patch("app.services.room_service.auth_queries.account_profiles", return_value=[])
        )
        self.rooms = RoomService()
        self.room = self.rooms.create("alice")
        self.rooms.join(self.room.code, "bob")
        self.rooms.set_bot(self.room.code, "alice", True)
        self.rooms.start(self.room.code, "alice")
        self.match = self.room.match
        self.match.begin()
        self.fake = FakeQueries()
        self.enterContext(patch("app.services.survey_service.room_service", self.rooms))
        self.enterContext(patch("app.services.survey_service.queries", self.fake))
        self.enterContext(patch("app.services.survey_service.jalankan_transaksi",
                                side_effect=lambda operation: operation(None)))  # fmt: skip
        self.service = SurveyService()
        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[require_authenticated_user] = lambda x_user=Header(
            "alice"
        ): SimpleNamespace(username=x_user)
        app.dependency_overrides[require_panel] = lambda: "fixture-token"
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

    def test_other_choice_is_saved_with_the_question_snapshot(self):
        self.fake.questions[2]["options"] = ["Lebih cepat", "Lebih berempati", "Lainnya"]
        self.finish()
        answers = self.answers()
        answers[2]["text"] = "Lainnya: Lebih pintar membaca situasi"
        response = self.client.post(
            f"/api/rooms/{self.room.code}/survey",
            json={"match_id": self.match.id, "answers": answers},
        )
        self.assertEqual(response.status_code, 200)
        saved = next(row for row in self.fake.answers if row["question_id"] == 3)
        self.assertEqual(saved["value_text"], answers[2]["text"])
        self.assertIn("Lainnya", saved["question_snapshot"]["options"])

    # Pemain yang keluar room setelah pertandingan selesai tetap bisa mengirim survei: registri memori selama
    # jendelanya, lalu arsip peserta (dicatat saat pemain terakhir keluar dan room dibersihkan).
    def test_player_who_left_the_room_can_still_submit_after_the_room_is_gone(self):
        self.finish()
        self.enterContext(patch("app.services.survey_service.survey_service", self.service))
        langsung = lambda target, args, daemon: SimpleNamespace(
            start=lambda: target(*args)
        )  # noqa: E731
        self.enterContext(patch("app.services.room_service.threading.Thread", side_effect=langsung))
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
        self.assertEqual({row["username"] for row in self.fake.participants}, {"alice", "bob"})
        nanti = time.monotonic() + BERLAKU_SELESAI_DETIK + 1
        with patch("app.services.survey_service.time.monotonic", return_value=nanti):
            self.assertEqual(self.service.status(self.room.code, "bob")["match_id"], self.match.id)
            with self.assertRaises(ValueError):
                self.service.status(self.room.code, "mallory")

    # Pertandingan selesai: peserta manusia dicatat sekali ke arsip, survei tetap bisa diisi setelah server
    # dinyalakan ulang, dan pengingat Main hilang begitu survei terkirim.
    def test_finished_match_is_archived_for_later_surveys_and_reminders(self):
        self.enterContext(patch("app.services.survey_service.survey_service", self.service))
        langsung = lambda target, args, daemon: SimpleNamespace(
            start=lambda: target(*args)
        )  # noqa: E731
        self.enterContext(patch("app.services.room_service.threading.Thread", side_effect=langsung))
        self.rooms.perbarui_fase_semua_room()
        self.assertEqual(self.fake.participants, [])  # belum selesai: belum dicatat
        self.finish()
        self.rooms.perbarui_fase_semua_room()
        self.rooms.perbarui_fase_semua_room()  # dicatat sekali saja
        self.assertEqual(sorted(p["username"] for p in self.fake.participants), ["alice", "bob"])
        # "Restart": room di memori hilang dan registri kosong; konteks diambil dari arsip.
        self.enterContext(patch("app.services.survey_service.room_service", RoomService()))
        baru = SurveyService()
        self.assertEqual(baru.status(self.room.code, "alice")["match_id"], self.match.id)
        self.assertEqual([s["room_code"] for s in baru.pending("alice")], [self.room.code])
        self.assertEqual(baru.pending("alice")[0]["finished_at"], "2026-10-20T07:00:00")
        baru.submit(self.room.code, "alice", self.match.id, self.answers())
        self.assertEqual(baru.pending("alice"), [])
        self.assertEqual(len(baru.pending("bob")), 1)
        for q in self.fake.questions:
            q["active"] = False
        self.assertEqual(baru.pending("bob"), [])  # tanpa pertanyaan aktif tidak ada pengingat
        with self.assertRaises(ValueError):
            baru.status(self.room.code, "mallory")
        self.assertEqual(self.client.get("/api/survey/pending").json(), {"surveys": []})

    # Dua kiriman bersamaan: yang kedua melanggar UNIQUE → "sudah dikirim" (409), bukan 503.
    def test_concurrent_duplicate_submit_is_reported_as_already_submitted(self):
        self.finish()

        def gagal(kode):
            raise PersistenceError("fixture") from IntegrityError(
                "INSERT", {}, Exception(kode, "fixture")
            )

        with patch("app.services.survey_service.jalankan_transaksi",
                   side_effect=lambda operation: gagal(1062)):  # fmt: skip
            with self.assertRaises(SurveyAlreadySubmitted):
                self.service.submit(self.room.code, "alice", self.match.id, self.answers())
            body = {"match_id": self.match.id, "answers": self.answers()}
            response = self.client.post(f"/api/rooms/{self.room.code}/survey", json=body)
            self.assertEqual(response.status_code, 409)
        with patch("app.services.survey_service.jalankan_transaksi",
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

    # Pertanyaan baru selalu masuk paling bawah walau panel lama masih mengirim position; edit tidak
    # menggeser posisinya.
    def test_new_question_goes_last_and_edit_keeps_its_position(self):
        created = self.service.create_question(
            {"code": "strategi", "prompt": "Strategi bot masuk akal?", "kind": "text"}
        )
        self.assertEqual(created["position"], 14)  # posisi terbesar (4) + 10
        response = self.client.post(
            "/api/panel/survey/questions",
            json={"code": "kedua", "prompt": "Pertanyaan kedua?", "kind": "text", "position": -500},
        )
        self.assertEqual((response.status_code, response.json()["position"]), (201, 24))
        self.assertEqual(
            [q["code"] for q in self.fake.list_questions(None)][-2:], ["strategi", "kedua"]
        )
        response = self.client.put(
            "/api/panel/survey/questions/1",
            json={**question(1), "prompt": "Sudah diubah?", "position": 999},
        )
        self.assertEqual((response.status_code, response.json()["position"]), (200, 1))
        self.assertEqual(
            [(q["prompt"], q["position"]) for q in self.fake.questions if q["id"] == 1],
            [("Sudah diubah?", 1)],
        )

    # Urutan baru memuat semua pertanyaan, termasuk yang nonaktif. Form pemain langsung mengikutinya
    # dan pertanyaan baru sesudahnya tetap masuk paling bawah.
    def test_reorder_rewrites_positions_and_the_player_form_follows(self):
        self.fake.questions[1]["active"] = False
        response = self.client.put("/api/panel/survey/questions/order", json={"ids": [4, 2, 1, 3]})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["questions"],
            [{"id": 4, "position": 10}, {"id": 2, "position": 20},
             {"id": 1, "position": 30}, {"id": 3, "position": 40}],
        )  # fmt: skip
        self.finish()
        status = self.service.status(self.room.code, "alice")
        self.assertEqual([q["id"] for q in status["questions"]], [4, 1, 3])
        created = self.service.create_question(
            {"code": "baru", "prompt": "Pertanyaan baru?", "kind": "text"}
        )
        self.assertEqual(created["position"], 50)

    # Daftar yang kurang, dobel, atau berisi id asing ditolak tanpa mengubah posisi; perlu login.
    def test_reorder_rejects_incomplete_duplicate_or_unknown_ids(self):
        sebelum = [(q["id"], q["position"]) for q in self.fake.questions]
        endpoint = "/api/panel/survey/questions/order"
        for ids, pesan in (
            ([1, 2, 3], "semua pertanyaan"),
            ([1, 2, 3, 4, 4], "lebih dari sekali"),
            ([1, 2, 3, 4, 99], "tidak ada"),
            ([1, 2, 3, 99], "tidak ada"),
        ):
            with self.subTest(ids=ids):
                response = self.client.put(endpoint, json={"ids": ids})
                self.assertEqual(response.status_code, 400)
                self.assertIn(pesan, response.json()["detail"])
        for body in ({"ids": []}, {}, {"ids": ["satu"]}):
            with self.subTest(body=body):
                self.assertEqual(self.client.put(endpoint, json=body).status_code, 422)
        self.assertEqual([(q["id"], q["position"]) for q in self.fake.questions], sebelum)
        tanpa_login = FastAPI()
        tanpa_login.include_router(router)
        self.assertEqual(
            TestClient(tanpa_login).put(endpoint, json={"ids": [1, 2, 3, 4]}).status_code, 401
        )

    # Membersihkan jawaban juga menghapus arsip peserta, supaya pertandingan lama tidak diminta diisi lagi.
    def test_panel_clears_answers_and_reminders_before_a_question_can_be_deleted(self):
        self.fake.answers = [{"match_id": "lama", "username": "alice", "question_id": 1}]
        self.fake.participants = [{"match_id": "lama", "username": "alice", "room_code": "ABC123"}]
        with self.assertRaises(ValueError):
            self.service.delete_question(1)
        self.assertIn(1, [q["id"] for q in self.fake.list_questions(None)])
        self.assertEqual(self.service.clear_responses(), {"deleted": 1})
        self.assertEqual(self.fake.pending_surveys(None, "alice"), [])
        self.service.delete_question(1)
        self.assertNotIn(1, [q["id"] for q in self.fake.list_questions(None)])
        with self.assertRaises(LookupError):
            self.service.delete_question(1)


class SurveyExportTests(unittest.TestCase):
    def setUp(self):
        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[require_panel] = lambda: "fixture-token"
        self.client = TestClient(app)

    # CSV: UTF-8 dengan BOM, kolom tetap, dan teks yang diawali karakter formula diberi awalan ' (injeksi CSV).
    def test_csv_has_bom_fixed_columns_and_safe_formula_text(self):
        rows = [{"created_at": "2026-09-30 10:00:00", "match_id": "m1", "room_code": "ABC123",
                 "username": "alice", "role": "spy", "team": "civilians", "outcome": "won",
                 "code": "saran", "question_snapshot": '{"prompt": "Saran untuk game?"}',
                 "value_number": None, "value_text": "=1+1 seru banget 👍",
                 "bots": "NOX:fuzzy:santai"}]  # fmt: skip
        with patch("app.controllers.survey.survey_service.export_rows", return_value=rows):
            response = self.client.get("/api/panel/survey/responses.csv")
        self.assertEqual(response.status_code, 200)
        body = response.content.decode("utf-8")
        self.assertTrue(body.startswith("﻿"))
        header, line = body.lstrip("﻿").splitlines()[:2]
        self.assertEqual(header, "created_at,match_id,room_code,username,role,team,outcome,code,"
                                 "prompt,value_number,value_text,bots")  # fmt: skip
        self.assertIn(",Saran untuk game?,,'=1+1 seru banget 👍,NOX:fuzzy:santai", line)

    # Semua awalan formula diamankan; teks biasa, angka, dan kosong tetap persis.
    def test_csv_escapes_every_formula_prefix_only(self):
        dasar = {"created_at": "2026-09-30 10:00:00", "match_id": "m1", "room_code": "ABC123",
                 "username": "alice", "role": "spy", "team": "civilians", "outcome": "won",
                 "code": "saran", "question_snapshot": '{"prompt": "Saran?"}', "bots": ""}  # fmt: skip
        teks = ["=SUM(A1)", "+1", "-2+3", "@cmd", "\tx", "biasa", "", None]
        rows = [{**dasar, "value_number": 3 if t is None else None, "value_text": t} for t in teks]
        with patch("app.controllers.survey.survey_service.export_rows", return_value=rows):
            body = self.client.get("/api/panel/survey/responses.csv").content.decode("utf-8-sig")
        hasil = [r["value_text"] for r in csv.DictReader(io.StringIO(body))]
        self.assertEqual(hasil, ["'=SUM(A1)", "'+1", "'-2+3", "'@cmd", "'\tx", "biasa", "", ""])
        angka = [r["value_number"] for r in csv.DictReader(io.StringIO(body))]
        self.assertEqual(angka[-1], "3")

    def test_delete_endpoints_need_panel_login_and_map_errors(self):
        tanpa_login = FastAPI()
        tanpa_login.include_router(router)
        with patch("app.controllers.survey.survey_service") as service:
            for path in ("/api/panel/survey/responses", "/api/panel/survey/questions/1"):
                self.assertEqual(TestClient(tanpa_login).delete(path).status_code, 401)
            service.clear_responses.assert_not_called()
            service.delete_question.assert_not_called()
            service.clear_responses.return_value = {"deleted": 3}
            self.assertEqual(
                self.client.delete("/api/panel/survey/responses").json(), {"deleted": 3}
            )
            self.assertEqual(self.client.delete("/api/panel/survey/questions/1").status_code, 204)
            service.delete_question.side_effect = ValueError("masih punya jawaban")
            self.assertEqual(self.client.delete("/api/panel/survey/questions/1").status_code, 400)
            service.delete_question.side_effect = LookupError("tidak ada")
            self.assertEqual(self.client.delete("/api/panel/survey/questions/9").status_code, 404)


class SurveyCleanSqlTests(unittest.TestCase):
    """SQL pembersihan dijalankan sungguhan (SQLite)."""

    def test_clear_keeps_questions_and_delete_removes_only_one_question(self):
        engine = create_engine("sqlite://")
        with Session(engine) as database:
            for table in ("survey_questions (id INT)", "survey_responses (question_id INT)",
                          "match_participants (match_id TEXT)"):  # fmt: skip
                database.execute(text(f"CREATE TABLE {table}"))
            database.execute(text("INSERT INTO survey_questions VALUES (1), (2)"))
            database.execute(text("INSERT INTO survey_responses VALUES (1), (1), (2)"))
            database.execute(text("INSERT INTO match_participants VALUES ('m1')"))
            self.assertEqual(survey_queries.count_question_answers(database, 1), 2)
            self.assertEqual(survey_queries.clear_responses(database), 3)
            for table, expected in (("survey_responses", 0), ("match_participants", 0),
                                    ("survey_questions", 2)):  # fmt: skip
                count = database.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar_one()
                self.assertEqual(count, expected)
            survey_queries.delete_question(database, 1)
            ids = database.execute(text("SELECT id FROM survey_questions")).scalars().all()
            self.assertEqual(ids, [2])


class SurveyOrderSqlTests(unittest.TestCase):
    """SQL urutan dijalankan sungguhan (SQLite): posisi tersimpan, edit tidak menggesernya."""

    def test_positions_are_rewritten_and_edits_keep_them(self):
        engine = create_engine("sqlite://")
        with Session(engine) as database:
            database.execute(text(
                "CREATE TABLE survey_questions (id INTEGER PRIMARY KEY, code TEXT, prompt TEXT, "
                "kind TEXT, scale_min INT, scale_max INT, label_min TEXT, label_max TEXT, "
                "options TEXT, required BOOLEAN, active BOOLEAN, position INT)"
            ))  # fmt: skip
            for posisi, kode in ((10, "aa"), (20, "bb"), (30, "cc")):
                data = validate_question({"code": kode, "prompt": f"Soal {kode}?", "kind": "text"})
                survey_queries.insert_question(database, {**data, "position": posisi})

            def urutan():
                return [
                    (q["code"], q["position"])
                    for q in survey_queries.list_questions(database, active_only=False)
                ]

            survey_queries.update_positions(
                database,
                [{"id": 3, "position": 10}, {"id": 1, "position": 20}, {"id": 2, "position": 30}],
            )
            self.assertEqual(urutan(), [("cc", 10), ("aa", 20), ("bb", 30)])
            ubah = validate_question({"code": "aa", "prompt": "Soal aa diubah?", "kind": "text"})
            survey_queries.update_question(database, 1, {**ubah, "position": 999})
            self.assertEqual(urutan(), [("cc", 10), ("aa", 20), ("bb", 30)])
            # Posisi kembar tetap berurutan menurut id.
            survey_queries.update_positions(
                database, [{"id": id_, "position": 10} for id_ in (3, 2, 1)]
            )
            self.assertEqual([kode for kode, _ in urutan()], ["aa", "bb", "cc"])


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

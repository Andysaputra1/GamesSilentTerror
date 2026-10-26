import base64
import json
import unittest
from datetime import date, datetime
from unittest.mock import patch, AsyncMock
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import SecretStr
import httpx
from app.config.settings import Settings, settings
from app.controller.api.panel import router, require_panel, history_filter, validate_endpoint
from app.module.password_service import hash_password
from app.module.openrouter_client import generate_reply

# Bacaan NLU satu pesan seperti yang disimpan pencatat NLU (BrainRuntime.baca_chat), beserta konteksnya.
NLU_CONTOH = json.dumps(
    {
        "intent": "offend",
        "confidence": 0.91,
        "target": [{"pemain": "NOX", "relasi": "offend", "prob": 0.88, "sumber": ["indobert"]}],
        "konteks": [
            {"pengirim": "ECHO", "teks": "Halo semua.", "intent": "neutral", "target": []},
            # Konteks lama menyimpan target sebagai teks; ekspor tetap menghasilkan {pemain, relasi}.
            {
                "pengirim": "NOX",
                "teks": "Aku bukan Hitman.",
                "intent": "defend",
                "target": ["NOX: defend (0.77)"],
            },
        ],
        "daftar_pemain": ["sender", "NOX", "ECHO"],
    }
)


class PanelTests(unittest.TestCase):
    def setUp(self):
        app = FastAPI()
        app.include_router(router)
        self.app = app
        self.client = TestClient(app)

    def test_all_data_and_mutations_require_admin_session(self):
        for path in [
            "/api/panel/config",
            "/api/panel/rooms",
            "/api/panel/history",
            "/api/panel/history.csv",
            "/api/panel/checker/ABC123",
        ]:
            self.assertEqual(self.client.get(path).status_code, 401)
        self.assertEqual(
            self.client.put("/api/panel/config", json={"provider": "api"}).status_code, 401
        )
        self.assertEqual(self.client.post("/api/panel/check-ai").status_code, 401)

    def test_html_has_no_embedded_password_and_csp(self):
        page = self.client.get("/panel")
        self.assertEqual(page.status_code, 200)
        self.assertIn("frame-ancestors", page.headers["content-security-policy"])
        self.assertIn("login-form", page.text)
        self.assertNotIn("Silent132", page.text)
        self.assertNotIn("Silent132", self.client.get("/panel/assets/panel.js").text)
        self.assertEqual(
            self.client.get("/admin", follow_redirects=False).headers["location"], "/panel"
        )

    def test_documents_are_whitelisted_and_sandboxed(self):
        for nama, judul in [
            ("erd", "ERD Silent Terror"),
            ("proses-ai", "Proses AI Silent Terror"),
            ("arsitektur", "Arsitektur Sistem Silent Terror"),
        ]:
            page = self.client.get(f"/panel/dokumen/{nama}")
            self.assertEqual(page.status_code, 200)
            self.assertIn(judul, page.text)
            self.assertTrue(page.headers["content-type"].startswith("text/html"))
            self.assertTrue(
                page.headers["content-security-policy"].startswith("sandbox allow-scripts;")
            )
        self.assertEqual(self.client.get("/panel/dokumen/..%2Fpanel%2Fpanel.js").status_code, 404)
        self.assertEqual(self.client.get("/panel/dokumen/lain").status_code, 422)

    def test_wrong_password_does_not_access_database(self):
        hashed = base64.b64encode(hash_password("fixture-password").encode()).decode()
        with (
            patch.object(settings, "panel_password_hash", SecretStr(hashed)),
            patch("app.controller.api.panel.transaction") as db,
        ):
            self.assertEqual(
                self.client.post(
                    "/api/panel/login", json={"username": "administrator", "password": "wrong"}
                ).status_code,
                401,
            )
            db.assert_not_called()

    def test_date_filters_cover_full_wib_day(self):
        _, params = history_filter(None, date(2026, 9, 23), date(2026, 9, 23))
        self.assertEqual(params["start"], datetime(2026, 9, 22, 17))
        self.assertEqual(params["end"], datetime(2026, 9, 23, 17))
        with self.assertRaises(HTTPException):
            history_filter(None, date(2026, 9, 24), date(2026, 9, 23))

    def test_tunnel_rejects_credentials_private_addresses_and_http(self):
        for url in [
            "http://example.com",
            "https://name:pass@example.com",
            "https://example.com/?key=secret",
        ]:
            with self.assertRaises(HTTPException):
                validate_endpoint(url)
        with patch(
            "app.controller.api.panel.socket.getaddrinfo",
            return_value=[(2, 1, 6, "", ("169.254.169.254", 443))],
        ):
            with self.assertRaises(HTTPException):
                validate_endpoint("https://metadata.test")

    def test_check_ai_error_is_not_reported_active(self):
        self.app.dependency_overrides[require_panel] = lambda: "fixture-token"
        with patch(
            "app.controller.api.panel.api_reply",
            AsyncMock(side_effect=ValueError("secret must not leak")),
        ):
            result = self.client.post("/api/panel/check-ai")
            self.assertFalse(result.json()["active"])
            self.assertNotIn("secret must not leak", result.text)

    def test_check_ai_credit_failure_is_actionable_without_secrets(self):
        self.app.dependency_overrides[require_panel] = lambda: "fixture-token"
        response = httpx.Response(
            402, request=httpx.Request("POST", "https://openrouter.ai"), text="secret"
        )
        error = httpx.HTTPStatusError("secret", request=response.request, response=response)
        with patch("app.controller.api.panel.api_reply", AsyncMock(side_effect=error)):
            result = self.client.post("/api/panel/check-ai")
        self.assertFalse(result.json()["active"])
        self.assertIn("kredit", result.json()["message"])
        self.assertNotIn("secret", result.text)

    def test_empty_room_is_archived_and_db_failure_removes_live_room(self):
        from types import SimpleNamespace
        from app.controller.api.rooms import router as room_router
        from app.controller.middleware.auth import require_authenticated_user
        from app.module.room_service import RoomService
        from app.module.persistence_service import PersistenceError

        self.app.include_router(room_router)
        self.app.dependency_overrides[require_authenticated_user] = lambda: SimpleNamespace(
            username="alice"
        )
        rooms = RoomService()
        with (
            patch("app.controller.api.rooms.room_service", rooms),
            patch("app.controller.api.rooms.PersistenceService") as factory,
        ):
            factory.return_value.archive_new_room.return_value = True
            response = self.client.post("/api/rooms")
            self.assertEqual(response.status_code, 200)
            factory.return_value.archive_new_room.assert_called_once_with("alice")
            before = set(rooms.rooms)
            # Akun lain menguji kegagalan arsip tanpa melanggar satu room per akun.
            self.app.dependency_overrides[require_authenticated_user] = lambda: SimpleNamespace(
                username="bob"
            )
            factory.return_value.archive_new_room.side_effect = PersistenceError("fail")
            self.assertEqual(self.client.post("/api/rooms").status_code, 503)
            self.assertEqual(set(rooms.rooms), before)


class OpenRouterTests(unittest.IsolatedAsyncioTestCase):
    async def test_fixed_qwen_payload_and_no_secret_in_body(self):
        client = AsyncMock()
        client.post.return_value = httpx.Response(
            200,
            request=httpx.Request("POST", "https://openrouter.ai"),
            json={"choices": [{"message": {"content": "OK"}}]},
        )
        with patch("app.module.openrouter_client.httpx.AsyncClient") as factory:
            factory.return_value.__aenter__.return_value = client
            result = await generate_reply(
                "hello", config=Settings(_env_file=None, openrouter_api_key="fixture-key")
            )
        self.assertEqual(result, "OK")
        self.assertEqual(client.post.call_args.kwargs["json"]["model"], "qwen/qwen3-14b")
        self.assertEqual(
            client.post.call_args.kwargs["headers"]["Authorization"], "Bearer fixture-key"
        )


class HistoryFilterTests(unittest.TestCase):
    # SQLite terisolasi memeriksa SQL filter yang sama pada daftar dan CSV, tanpa data produksi.
    def setUp(self):
        from sqlalchemy import create_engine, text
        from sqlalchemy.pool import StaticPool

        self.engine = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
        with self.engine.begin() as db:
            db.execute(text("CREATE TABLE game_sessions (id INTEGER, room_code TEXT)"))
            db.execute(text("INSERT INTO game_sessions VALUES (1,'ABC123'),(2,'DEF456')"))
            db.execute(
                text(
                    "CREATE TABLE chat_messages (id INTEGER, game_session_id INTEGER, sender_name TEXT, sender_kind TEXT, message TEXT, created_at TEXT, match_id TEXT, round_number INTEGER, phase TEXT, nlu TEXT)"
                )
            )
            for i, room, kind, day in [
                (1, 1, "human", 23),
                (2, 1, "bot", 23),
                (3, 1, "legacy", 23),
                (4, 2, "bot", 23),
                (5, 1, "bot", 20),
            ]:
                db.execute(
                    text(
                        "INSERT INTO chat_messages VALUES (:id,:room,'sender',:kind,:message,:date,'match',1,'day',:nlu)"
                    ),
                    {
                        "id": i,
                        "room": room,
                        "kind": kind,
                        "message": f"message-{i}",
                        "date": f"2026-09-{day} 01:00:00",
                        "nlu": NLU_CONTOH if i == 1 else None,
                    },
                )
        self.app = FastAPI()
        self.app.include_router(router)
        self.app.dependency_overrides[require_panel] = lambda: "test-admin"
        self.client = TestClient(self.app)

        def transaction(operation):
            with self.engine.begin() as db:
                return operation(db)

        self.db_patch = patch("app.controller.api.panel.transaction", side_effect=transaction)
        self.db_patch.start()

    def tearDown(self):
        self.client.close()
        self.db_patch.stop()
        self.engine.dispose()

    def test_export_and_list_share_room_date_and_sender_filters(self):
        import csv
        import io

        for kind, expected in [("all", [1, 2, 3]), ("human", [1]), ("bot", [2]), ("legacy", [3])]:
            query = {
                "room_code": "ABC123",
                "date_from": "2026-09-23",
                "date_to": "2026-09-23",
                "sender_kind": kind,
            }
            response = self.client.get("/api/panel/history", params=query)
            self.assertEqual(response.status_code, 200)
            self.assertEqual([m["id"] for m in response.json()["messages"]], expected)
            exported = self.client.get("/api/panel/history.csv", params=query)
            self.assertEqual(exported.status_code, 200)
            rows = list(csv.reader(io.StringIO(exported.content.decode("utf-8-sig"))))
            kolom = rows[0]
            self.assertEqual(kolom[:7], ["pengirim", "teks_chat", "label_intent", "chat_sebelumnya",
                                         "daftar_pemain", "target", "session_id"])  # fmt: skip
            baris = [dict(zip(kolom, row)) for row in rows[1:]]
            self.assertEqual([int(b["chat_id"]) for b in baris], expected)
            if kind == "human":  # format dataset: konteks, roster, dan target sebagai JSON
                b = baris[0]
                self.assertEqual((b["pengirim"], b["teks_chat"], b["label_intent"]),
                                 ("sender", "message-1", "offend"))  # fmt: skip
                self.assertEqual(json.loads(b["target"]), [{"pemain": "NOX", "relasi": "offend"}])
                self.assertEqual(json.loads(b["daftar_pemain"]), ["sender", "NOX", "ECHO"])
                self.assertEqual(json.loads(b["chat_sebelumnya"]), [
                    {"pengirim": "ECHO", "teks_chat": "Halo semua.", "label_intent": "neutral", "target": []},
                    {"pengirim": "NOX", "teks_chat": "Aku bukan Hitman.", "label_intent": "defend",
                     "target": [{"pemain": "NOX", "relasi": "defend"}]},
                ])  # fmt: skip
                self.assertEqual((b["session_id"], b["room_code"]), ("match", "ABC123"))
            if kind == "legacy":  # arsip lama tanpa bacaan: kolom bacaan kosong
                self.assertEqual((baris[0]["label_intent"], baris[0]["chat_sebelumnya"]), ("", ""))
        # Urutan terbaru dulu, untuk tampilan (halaman lewat before_id) dan ekspor.
        query = {"room_code": "ABC123", "urut": "baru"}
        halaman = self.client.get("/api/panel/history", params=query).json()
        self.assertEqual([m["id"] for m in halaman["messages"]][:3], sorted(
            [m["id"] for m in halaman["messages"]], reverse=True)[:3])  # fmt: skip
        sebelum = self.client.get("/api/panel/history", params={**query, "before_id": 3}).json()
        self.assertTrue(all(m["id"] < 3 for m in sebelum["messages"]))
        ekspor = list(csv.reader(io.StringIO(
            self.client.get("/api/panel/history.csv", params=query).content.decode("utf-8-sig"))))  # fmt: skip
        ids = [int(dict(zip(ekspor[0], r))["chat_id"]) for r in ekspor[1:]]
        self.assertEqual(ids, sorted(ids, reverse=True))
        # Bacaan NLU saat game berjalan ikut tampil; pesan tanpa bacaan bernilai null.
        pesan = self.client.get("/api/panel/history", params={"room_code": "ABC123"}).json()
        self.assertEqual([m["nlu"] for m in pesan["messages"][:2]], [json.loads(NLU_CONTOH), None])
        self.assertEqual(self.client.get("/api/panel/history?sender_kind=bad").status_code, 422)
        self.assertEqual(self.client.get("/api/panel/history.csv?sender_kind=bad").status_code, 422)

"""Integrasi HTTP + RoomService + engine; akun dan penyimpanan arsip memakai fixture."""

from types import SimpleNamespace
import unittest
from unittest.mock import patch

from fastapi import FastAPI, Header
from fastapi.testclient import TestClient

from controller.api.rooms import router
from controller.middleware.auth import require_authenticated_user
from services.room_service import RoomService


class GameLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.rooms = RoomService()
        self.now = 1000.0
        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[require_authenticated_user] = lambda x_user=Header(
            "player0"
        ): SimpleNamespace(username=x_user)
        self.enterContext(patch("controller.api.rooms.room_service", self.rooms))
        self.enterContext(patch("controller.api.rooms.PersistenceService"))
        self.enterContext(patch("services.match_engine.time.time", side_effect=lambda: self.now))
        self.client = self.enterContext(TestClient(app))

    def create_match(self, count):
        response = self.client.post("/api/rooms", json={"capacity": count})
        self.assertEqual(response.status_code, 200)
        code = response.json()["code"]
        self.base = "/api/rooms/" + code
        for index in range(1, count):
            response = self.client.post(
                "/api/rooms/join", json={"code": code}, headers={"x-user": f"player{index}"}
            )
            self.assertEqual(response.status_code, 200)
        response = self.client.post(self.base + "/start", json={"quick": True})
        self.assertEqual(response.status_code, 200)
        self.match = self.rooms.rooms[code].match
        # Layar persiapan: tanpa bot AI langsung siap; ronde 1 mulai setelah semua manusia menekan Siap.
        self.assertEqual(self.state()["phase"], "preparing")
        for index in range(count):
            response = self.client.post(
                self.base + "/ready",
                json={"match_id": self.match.id},
                headers={"x-user": f"player{index}"},
            )
            self.assertEqual(response.status_code, 200)
        self.assertEqual(self.state()["phase"], "day")
        self.assertNotIn("max_rounds", self.state())

    def state(self, name="player0"):
        response = self.client.get(self.base + "/game", headers={"x-user": name})
        self.assertEqual(response.status_code, 200)
        return response.json()["game"]

    def play(self, name, target, ability=None):
        view = self.state(name)
        response = self.client.post(
            self.base + "/play",
            headers={"x-user": name},
            json={
                "match_id": view["id"],
                "round_number": view["round"],
                "phase": view["phase"],
                "target": target,
                "ability": ability,
            },
        )
        self.assertEqual(response.status_code, 200, response.text)

    def advance(self):
        self.now = self.match.deadline
        self.rooms.tick_all()
        return self.state()

    def check_result_and_leave(self, winner):
        for name, player in self.match.players.items():
            view = self.state(name)
            self.assertEqual((view["phase"], view["winner"]), ("finished", winner))
            self.assertTrue(all("role" in item for item in view["players"]))
            self.assertFalse(any(view["me"][key] for key in ("can_chat", "can_act", "can_vote")))
            team = "hitman" if player.role == "hitman" else "civilians"
            expected = "won" if team == winner else "lost"
            self.assertEqual(view["result"]["outcome"], expected)
            response = self.client.get("/api/rooms/active", headers={"x-user": name})
            self.assertIsNone(response.json()["active"])
        before = self.state()
        self.now += 10000
        self.rooms.tick_all()
        after = self.state()
        for key in ("round", "winner", "result", "players", "events"):
            self.assertEqual(before[key], after[key])
        for name in self.match.players:
            response = self.client.post(self.base + "/leave", headers={"x-user": name})
            self.assertEqual(response.status_code, 200)
        self.assertEqual(self.rooms.rooms, {})

    def hitmen(self):
        return [name for name, player in self.match.players.items() if player.role == "hitman"]

    # Dimulai saat Tribunal: setiap Tribunal mengeksekusi satu Hitman sampai semuanya tertangkap.
    def execute_every_hitman(self):
        hitmen = self.hitmen()
        for index, hitman in enumerate(hitmen):
            self.assertEqual(self.state()["phase"], "tribunal")
            for name, player in self.match.players.items():
                if player.alive and name != hitman:
                    self.play(name, hitman)
            view = self.advance()
            if index < len(hitmen) - 1:
                # Masih ada Hitman hidup: permainan berlanjut ke ronde berikutnya.
                self.assertIsNone(view["winner"])
                self.advance()
                self.advance()

    def test_all_room_sizes_continue_past_old_limits_until_a_team_wins(self):
        for count in range(4, 11):
            with self.subTest(count=count):
                self.create_match(count)
                for round_number in range(1, 26):
                    for phase in ("day", "night", "tribunal"):
                        view = self.state()
                        self.assertEqual((view["round"], view["phase"]), (round_number, phase))
                        self.assertIsNone(view["winner"])
                        self.advance()
                self.assertEqual((self.state()["round"], self.state()["phase"]), (26, "day"))
                self.advance()
                self.advance()
                self.execute_every_hitman()
                self.check_result_and_leave("civilians")

    def test_civilian_victory_after_every_hitman_is_executed(self):
        for count in range(4, 11):
            with self.subTest(count=count):
                self.create_match(count)
                # Persetujuan semua manusia memajukan fase melalui endpoint yang dipakai UI.
                for name in self.match.players:
                    view = self.state(name)
                    response = self.client.post(
                        self.base + "/skip-discussion",
                        headers={"x-user": name},
                        json={"match_id": view["id"], "round_number": 1, "phase": "day"},
                    )
                    self.assertEqual(response.status_code, 200)
                self.assertEqual(self.state()["phase"], "night")
                self.advance()
                self.execute_every_hitman()
                # Satu Hitman per Tribunal: jumlah ronde = jumlah Hitman.
                self.assertEqual(self.state()["round"], len(self.hitmen()))
                self.check_result_and_leave("civilians")

    def test_hitman_victory_finishes_at_night_when_free_citizens_match_hitmen(self):
        for count in range(4, 11):
            with self.subTest(count=count):
                self.create_match(count)
                hitmen = self.hitmen()
                targets = [name for name in self.match.players if name not in hitmen]
                # Syndicate menang saat warga bebas tinggal sebanyak Hitman yang hidup.
                nights = len(targets) - len(hitmen)
                for index, target in enumerate(targets[:nights]):
                    self.assertEqual(self.advance()["phase"], "night")
                    for hitman in hitmen:
                        self.play(hitman, target, "hostage")
                    view = self.advance()
                    if index == nights - 1:
                        self.assertEqual(view["phase"], "finished")
                    else:
                        self.assertEqual(view["phase"], "tribunal")
                        self.assertIsNone(view["winner"])
                        self.advance()
                self.assertEqual(self.state()["result"]["civilians_voters"], len(hitmen))
                self.assertEqual(self.state()["round"], nights)
                self.check_result_and_leave("hitman")

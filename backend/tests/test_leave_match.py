"""Keluar di tengah pertandingan = tereliminasi seperti dieksekusi, ditandai `left` (tanpa LLM/DB)."""

import random
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import FastAPI, Header
from fastapi.testclient import TestClient

from app.controller.api.rooms import router
from app.controller.middleware.auth import require_authenticated_user
from app.services.match_engine import Match, snapshot_berlabel
from app.services.npc_service import npc_context
from app.services.room_service import RoomService

RAHASIA = " Role tetap dirahasiakan sampai permainan selesai."
KUNCI_PUBLIK = {"name", "label", "alive", "skin_id"}


class LeaveEngineTests(unittest.TestCase):
    # FIXTURE: enam manusia, nama = role agar skenario mudah dibaca (sama dengan EngineTests).
    def setUp(self):
        self.game = Match(
            ["hitman", "spy", "stalker", "civilian", "civilian2", "civilian3"],
            [],
            now=0,
            rng=random.Random(7),
        )
        for name, player in self.game.players.items():
            player.role = name if name in {"hitman", "spy", "stalker"} else "civilian"

    def night(self):
        self.game.phase = "night"
        self.game.actions.clear()

    def entry(self, viewer, name):
        return next(p for p in self.game.snapshot(viewer)["players"] if p["name"] == name)

    def test_leave_during_day_eliminates_like_execution_and_hides_role(self):
        self.assertTrue(self.game.leave("civilian", now=5))
        player = self.game.players["civilian"]
        self.assertEqual((player.alive, player.left), (False, True))
        self.assertFalse(self.game.can_chat("civilian"))
        with self.assertRaises(ValueError):
            self.game.actor("civilian")
        self.assertEqual(self.game.events[-1], "civilian meninggalkan permainan." + RAHASIA)
        # Roster publik: hanya tanda keluar yang bertambah, role dan status lain tetap rahasia.
        self.assertEqual(
            self.entry("spy", "civilian"),
            {"name": "civilian", "label": "civilian", "alive": False, "skin_id": player.skin_id}
            | {"left": True},
        )
        others = [p for p in self.game.snapshot("spy")["players"] if p["name"] != "civilian"]
        self.assertTrue(all(set(p) == KUNCI_PUBLIK for p in others))
        self.assertEqual(self.game.snapshot("spy")["discussion_skip"]["required"], 5)
        self.assertEqual((self.game.phase, self.game.winner), ("day", None))
        # Tribunal berikutnya: yang keluar tidak bisa memilih maupun dipilih.
        self.game.phase = "tribunal"
        with self.assertRaises(ValueError):
            self.game.vote("civilian", "hitman")
        with self.assertRaises(ValueError):
            self.game.vote("spy", "civilian")

    def test_executed_player_is_not_marked_left_and_leave_changes_nothing(self):
        self.game.phase = "tribunal"
        self.game.vote("spy", "civilian")
        self.game.tick(self.game.deadline)
        events = list(self.game.events)
        self.assertFalse(self.game.leave("civilian"))
        self.assertFalse(self.game.players["civilian"].left)
        self.assertEqual(self.game.events, events)
        self.assertEqual(set(self.entry("spy", "civilian")), KUNCI_PUBLIK)

    def test_leave_completes_discussion_skip_when_everyone_else_agreed(self):
        for name in ["hitman", "spy", "stalker", "civilian", "civilian2"]:
            self.game.skip_discussion(name, now=1)
        self.assertEqual(self.game.phase, "day")
        self.game.leave("civilian3", now=2)
        self.assertEqual(self.game.phase, "night")
        self.assertIn("Semua pemain manusia menyetujui akhir diskusi.", self.game.events)

    def test_leave_during_night_drops_choices_on_the_leaver_and_lets_actors_rechoose(self):
        self.night()
        self.game.act("hitman", "hostage", "civilian")
        self.game.act("spy", "guard", "civilian")
        self.game.act("stalker", "peek", "civilian")
        self.game.leave("civilian")
        self.assertEqual(self.game.actions, {})
        me = self.game.snapshot("hitman")["me"]
        self.assertEqual((me["can_act"], me["action"]), (True, None))
        with self.assertRaises(ValueError):
            self.game.act("hitman", "hostage", "civilian")
        self.game.act("hitman", "hostage", "civilian2")
        self.game.tick(self.game.deadline)
        self.assertTrue(self.game.players["civilian2"].hostage)
        self.assertFalse(self.game.players["civilian"].hostage)
        # Peek ke pemain yang keluar dibuang: role-nya tidak bocor ke Stalker.
        self.assertEqual(self.game.players["stalker"].intel, [])
        self.assertEqual((self.game.phase, self.game.round), ("day", 2))

    def test_leaver_own_night_action_is_discarded(self):
        self.night()
        self.game.act("spy", "guard", "civilian2")
        self.game.act("hitman", "hostage", "civilian2")
        self.game.leave("spy")
        self.assertNotIn("spy", self.game.actions)
        self.game.tick(self.game.deadline)
        self.assertTrue(
            self.game.players["civilian2"].hostage
        )  # Guard milik yang keluar tidak berlaku

    def test_leave_during_tribunal_cleans_votes_and_tribunal_still_resolves(self):
        self.game.phase = "tribunal"
        self.game.vote("civilian", "hitman")  # suara milik yang keluar
        self.game.vote("spy", "civilian")  # suara ke yang keluar
        self.game.vote("stalker", "hitman")
        self.game.leave("civilian")
        self.assertEqual(self.game.votes, {"stalker": "hitman"})
        view = self.game.snapshot("spy")
        self.assertTrue(view["me"]["can_vote"])
        tally = {row["target"]: row["voters"] for row in view["tribunal_votes"]}
        self.assertEqual((tally["civilian"], tally["hitman"]), ([], ["stalker"]))
        self.game.vote("spy", "civilian2")
        self.game.tick(self.game.deadline)  # seri: tanpa eksekusi, lanjut ke malam
        self.assertEqual((self.game.round, self.game.phase, self.game.winner), (1, "night", None))

    def test_last_hitman_leaving_ends_the_game_for_the_civilians(self):
        self.game.leave("hitman")
        self.assertEqual(
            (self.game.winner, self.game.winner_reason, self.game.phase),
            ("civilians", "hitman_executed", "finished"),
        )
        # Hitman terakhir tersingkir: game selesai, jadi tidak ada catatan "role dirahasiakan".
        self.assertEqual(self.game.events[-2], "hitman meninggalkan permainan.")
        self.assertEqual(self.game.events[-1], "Kubu warga menang. Hitman keluar dari permainan.")
        self.assertEqual(self.game.result("hitman")["outcome"], "lost")
        self.assertEqual(self.game.result("spy")["outcome"], "won")
        hitman = self.entry("spy", "hitman")  # setelah selesai role semua pemain dibuka
        self.assertEqual((hitman["alive"], hitman["left"], hitman["role"]), (False, True, "hitman"))

    def test_civilian_leaving_can_give_the_syndicate_vote_control(self):
        for name in ["civilian", "civilian2", "civilian3"]:
            self.game.players[name].hostage = True
        self.game.leave("stalker")
        self.assertEqual((self.game.winner, self.game.winner_reason), ("hitman", "vote_control"))
        # Hasil yang keluar tetap mengikuti kubunya, sama seperti korban eksekusi.
        result = self.game.result("stalker")
        self.assertEqual((result["team"], result["outcome"]), ("civilians", "lost"))
        self.assertEqual(result["civilians_eliminated"], 1)

    def test_leave_is_idempotent_and_only_for_humans_in_the_match(self):
        self.assertTrue(self.game.leave("civilian"))
        events = list(self.game.events)
        self.assertFalse(self.game.leave("civilian"))
        self.assertEqual(self.game.events, events)
        with self.assertRaises(ValueError):
            self.game.leave("outsider")
        bots = Match(["alice"], ["NOX", "ECHO", "VEIL"], now=0)
        with self.assertRaises(ValueError):
            bots.leave("NOX")


class LeaveSyndicateTests(unittest.TestCase):
    # Room dua Hitman: jumlah Hitman tersisa ikut diumumkan saat keluar, seperti eksekusi.
    def setUp(self):
        names = [
            "hitman",
            "hitman2",
            "spy",
            "spy2",
            "stalker",
            "civilian",
            "civilian2",
            "civilian3",
        ]
        self.game = Match(names, [], now=0, rng=random.Random(3))
        for name, player in self.game.players.items():
            player.role = name.rstrip("23")

    def test_leaving_hitman_updates_the_public_count(self):
        self.game.leave("hitman2")
        self.assertEqual(
            self.game.events[-1], "hitman2 meninggalkan permainan. Hitman tersisa: 1." + RAHASIA
        )
        self.assertEqual(self.game.snapshot("spy")["hitman_remaining"], 1)
        self.assertIsNone(self.game.winner)

    def test_mixed_execution_and_leave_reports_hitmen_as_eliminated(self):
        self.game.leave("hitman2")
        self.game.phase = "tribunal"
        self.game.vote("spy", "hitman")
        self.game.tick(self.game.deadline)
        self.assertEqual(self.game.winner, "civilians")
        self.assertEqual(self.game.events[-1], "Kubu warga menang. Semua Hitman tersingkir.")


class LeavePreparationAndBotTests(unittest.TestCase):
    def test_leave_during_preparation_does_not_hold_round_one(self):
        match = Match(["alice", "bob"], ["NOX", "ECHO"], now=0.0, preparing=True)
        roles = {"NOX": "hitman", "ECHO": "spy", "alice": "stalker", "bob": "civilian"}
        for name, role in roles.items():
            match.players[name].role = role
        match.reveal_role("alice", now=1)
        match.mark_ai_ready(now=2)
        match.leave("bob", now=5)
        prep = match.snapshot("alice")["preparation"]
        self.assertEqual((prep["required"], prep["unrevealed"]), (1, 0))
        match.tick(10)  # waktu baca minimal lewat; tidak menunggu kartu bob
        self.assertEqual(match.phase, "day")

    def test_engine_bots_never_target_a_left_player(self):
        for seed in range(20):
            game = Match(
                ["alice", "bob"], ["NOX", "ECHO", "VEIL", "RAVEN"], now=0, rng=random.Random(seed)
            )
            roles = {"NOX": "hitman", "ECHO": "spy", "VEIL": "stalker"}
            for name, player in game.players.items():
                player.role = roles.get(name, "civilian")
            game.leave("bob")
            game.phase = "night"
            game.run_bots()
            self.assertTrue(all(a["target"] != "bob" for a in game.actions.values()))
            game.phase, game.votes = "tribunal", {}
            game.run_bots()
            self.assertNotIn("bob", game.votes.values())


class LeaveRoomTests(unittest.TestCase):
    # RoomService sungguhan; profil akun dibaca dari database tes (kosong → nama bawaan).
    def setUp(self):
        self.rooms = RoomService()
        self.room = self.rooms.create("alice")
        self.rooms.join(self.room.code, "bob")
        self.rooms.set_bot(self.room.code, "alice", True)
        self.rooms.start(self.room.code, "alice")
        self.match = self.room.match
        roles = {"NOX": "hitman", "ECHO": "spy", "VEIL": "stalker"}
        for name, player in self.match.players.items():
            player.role = roles.get(name, "civilian")
        self.match.begin(time.time())

    def test_mid_game_leave_eliminates_removes_membership_and_blocks_return(self):
        self.rooms.leave(self.room.code, "alice")
        alice = self.match.players["alice"]
        self.assertEqual((alice.alive, alice.left), (False, True))
        self.assertEqual(self.room.members, ["bob"])
        self.assertEqual(self.room.owner, "bob")
        self.assertIsNone(self.rooms.active("alice"))
        token = {"match_id": self.match.id, "round_number": 1, "phase": "day"}
        for operation in [
            lambda: self.rooms.state(self.room.code, "alice"),
            lambda: self.rooms.join(self.room.code, "alice"),
            lambda: self.rooms.play(self.room.code, "alice", target="NOX", ability="gag", **token),
        ]:
            with self.assertRaises(ValueError):
                operation()
        view = self.rooms.state(self.room.code, "bob")["game"]
        alice = next(p for p in view["players"] if p["name"] == "alice")
        self.assertEqual((alice["alive"], alice.get("left")), (False, True))
        self.assertIn("alice meninggalkan permainan." + RAHASIA, view["events"])

    def test_leaving_twice_is_idempotent_and_outsiders_are_rejected(self):
        self.rooms.leave(self.room.code, "alice")
        events = list(self.match.events)
        self.rooms.leave(self.room.code, "alice")
        self.assertEqual(self.match.events, events)
        self.assertEqual(self.room.members, ["bob"])
        with self.assertRaises(ValueError):
            self.rooms.leave(self.room.code, "outsider")

    def test_last_human_leaving_cleans_the_room(self):
        self.rooms.leave(self.room.code, "alice")
        self.rooms.leave(self.room.code, "bob")
        self.assertNotIn(self.room.code, self.rooms.rooms)

    def test_npc_views_show_the_left_player_as_not_alive(self):
        from app.services.npc_brain.generated import otak_bt, otak_fuzzy, otak_utility

        self.rooms.leave(self.room.code, "alice")
        context = npc_context(self.match, "NOX")
        self.assertIn({"name": "alice", "alive": False}, context["players"])
        self.assertNotIn("alice", context["legal_actions"]["gag"])
        snapshot = snapshot_berlabel(self.match.snapshot("NOX"), self.match.labels)
        alice = next(p for p in snapshot["players"] if p["name"] == "alice")
        self.assertEqual((alice["alive"], alice["left"]), (False, True))
        for modul in (otak_fuzzy, otak_utility, otak_bt):
            with self.subTest(modul=modul.__name__):
                view = modul.Ingatan("NOX").sinkron_snapshot(snapshot, time.time())
                self.assertIn({"nama": "alice", "hidup": False}, view["pemain"])

    def test_bot_memory_records_leaver_without_tribunal_blame(self):
        from app.services.npc_brain.generated import otak_bt, otak_fuzzy, otak_utility

        sebelum = snapshot_berlabel(self.match.snapshot("ECHO"), self.match.labels)
        self.rooms.leave(self.room.code, "alice")
        sesudah = snapshot_berlabel(self.match.snapshot("ECHO"), self.match.labels)
        for modul in (otak_fuzzy, otak_utility, otak_bt):
            with self.subTest(modul=modul.__name__):
                ingatan = modul.Ingatan("ECHO")
                ingatan.sinkron_snapshot(sebelum, time.time())
                view = ingatan.sinkron_snapshot(sesudah, time.time())
                # Keluar bukan eksekusi Tribunal: tidak ada bukti "mendorong eksekusi warga" untuk siapa pun.
                self.assertEqual(ingatan.eksekusi, [])
                self.assertEqual(ingatan.keluar, [{"ronde": 1, "pemain": "alice", "hitman": None}])
                tabel, _ = modul.hitung_bukti(ingatan, view)
                self.assertTrue((tabel["dorong_salah_eksekusi"] == 0).all())
                # Room 1 Hitman dan game berlanjut: yang keluar pasti bukan Hitman.
                self.assertIn("alice", modul.pengetahuan_peran(ingatan, view)["bersih"])

    def test_http_leave_returns_left_twice_and_rejects_outsiders(self):
        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[require_authenticated_user] = lambda x_user=Header(
            "alice"
        ): SimpleNamespace(username=x_user)
        base = f"/api/rooms/{self.room.code}"
        with patch("app.controller.api.rooms.room_service", self.rooms), TestClient(app) as client:
            for _ in range(2):
                response = client.post(base + "/leave", headers={"x-user": "alice"})
                self.assertEqual((response.status_code, response.json()), (200, {"left": True}))
            self.assertEqual(
                client.get(base + "/game", headers={"x-user": "alice"}).status_code, 400
            )
            outsider = client.post(base + "/leave", headers={"x-user": "outsider"})
            self.assertEqual(outsider.status_code, 400)
            players = client.get(base + "/game", headers={"x-user": "bob"}).json()["game"][
                "players"
            ]
            self.assertIn(
                {"left": True, "alive": False},
                [{k: p.get(k) for k in ("left", "alive")} for p in players if p["name"] == "alice"],
            )


if __name__ == "__main__":
    unittest.main()

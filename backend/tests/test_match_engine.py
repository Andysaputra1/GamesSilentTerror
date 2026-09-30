"""Aturan game diuji tanpa LLM/DB agar hasil deterministik dan cepat."""

import random
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from fastapi import FastAPI, Header
from fastapi.testclient import TestClient
from controller.api.rooms import router
from controller.middleware.auth import require_authenticated_user
from realtime.socket_handlers import SocketGameController
from services.match_engine import KOMPOSISI_PERAN, Match
from services.room_service import RoomService


class EngineTests(unittest.TestCase):
    # FIXTURE: nama sama dengan role supaya setiap skenario mudah dibaca.
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

    def test_idle_match_keeps_running_without_a_round_limit(self):
        for _ in range(60):
            self.game.tick(self.game.deadline)
        self.assertEqual((self.game.round, self.game.phase, self.game.winner), (21, "day", None))
        self.assertTrue(all("role" not in p for p in self.game.snapshot("spy")["players"]))
        self.assertTrue(self.game.can_chat("spy"))
        self.assertIsNone(self.game.snapshot("spy")["result"])

    def test_execution_wins_even_after_many_rounds(self):
        self.game.round = 25
        self.game.phase = "tribunal"
        self.game.vote("spy", "hitman")
        self.game.tick(self.game.deadline)
        self.assertEqual(self.game.winner, "civilians")

    def test_ai_grace_is_bounded_and_does_not_extend_night(self):
        self.game.reserve_ai_reply(now=115)
        self.assertEqual(self.game.deadline, 150)
        self.game.reserve_ai_reply(now=149)
        self.assertEqual(self.game.deadline, 150)
        self.game.tick(150)
        deadline = self.game.deadline
        self.game.reserve_ai_reply(now=179)
        self.assertEqual(self.game.deadline, deadline)

    def test_role_distribution_and_size(self):
        for count in range(4, 11):
            game = Match([str(i) for i in range(count)], [])
            roles = [p.role for p in game.players.values()]
            hitman, spy, stalker = KOMPOSISI_PERAN[count]
            self.assertEqual(
                (roles.count("hitman"), roles.count("spy"), roles.count("stalker")),
                (hitman, spy, stalker),
            )
            self.assertEqual(roles.count("civilian"), count - hitman - spy - stalker)
            self.assertGreaterEqual(roles.count("civilian"), 1)
            # Komposisi publik sama untuk semua viewer; siapa pemegang role tetap rahasia.
            for viewer in game.players:
                self.assertEqual(
                    game.snapshot(viewer)["composition"],
                    {role: roles.count(role) for role in ("hitman", "spy", "stalker", "civilian")},
                )
        # Jumlah Hitman, Spy, dan Stalker tidak pernah menyusut saat pemain bertambah.
        for count in range(4, 10):
            smaller, larger = KOMPOSISI_PERAN[count], KOMPOSISI_PERAN[count + 1]
            self.assertTrue(all(a <= b for a, b in zip(smaller, larger)), count)
        for humans in [[], ["a"] * 4, list("abcdefghijk")]:
            with self.assertRaises(ValueError):
                Match(humans, [])

    def test_four_player_mode_and_roster_based_timers(self):
        for count in range(4, 11):
            game = Match([str(i) for i in range(count)], [], now=0)
            self.assertEqual(game.durations["day"], count * 20)
            self.assertEqual(game.durations["night"], count * 5)
            self.assertEqual(game.deadline, count * 20)
            durations = dict(game.durations)
            next(iter(game.players.values())).hostage = True
            game.tick(game.deadline)
            self.assertEqual(game.durations, durations)
            self.assertEqual(game.deadline, count * 25)
            fast = Match(list(game.players), [], quick=True, now=0)
            self.assertTrue(all(fast.durations[p] < durations[p] for p in durations))
        rooms = RoomService()
        room = rooms.create("solo", capacity=4)
        rooms.set_bot(room.code, "solo", True)
        self.assertEqual(len(rooms.bot_names(room)), 3)
        preview = rooms.snapshot(room)["phase_durations"]["standard"]
        rooms.start(room.code, "solo")
        self.assertEqual(len(room.match.players), 4)
        self.assertEqual(room.match.durations, preview)

    def test_tied_votes_continue_into_next_round_without_a_winner(self):
        for round_number in range(1, 26):
            self.game.tick(self.game.deadline)
            self.game.tick(self.game.deadline)
            self.game.vote("spy", "hitman")
            self.game.vote("hitman", "spy")
            self.game.tick(self.game.deadline)
            self.assertEqual((self.game.phase, self.game.round), ("day", round_number + 1))
            self.assertIsNone(self.game.winner)
            self.assertTrue(all(p.alive for p in self.game.players.values()))

    def test_blind_actions_and_guard_priority(self):
        self.night()
        self.game.act("hitman", "hostage", "civilian")
        self.game.act("spy", "guard", "civilian")
        self.assertFalse(self.game.players["civilian"].hostage)
        self.assertIsNone(self.game.snapshot("stalker")["me"]["action"])
        self.game.resolve_night()
        self.assertFalse(self.game.players["civilian"].hostage)
        self.assertEqual(self.game.players["spy"].last_guard, "civilian")

    def test_guard_consecutive_nights_but_can_self_guard(self):
        self.night()
        self.game.act("spy", "guard", "spy")
        self.game.resolve_night()
        self.game.round = 2
        self.game.actions.clear()
        with self.assertRaises(ValueError):
            self.game.act("spy", "guard", "spy")
        self.game.act("spy", "guard", "civilian")
        self.game.resolve_night()
        self.game.round = 3
        self.game.actions.clear()
        self.game.act("spy", "guard", "spy")

    def test_peek_private_and_cooldown(self):
        self.night()
        self.game.act("stalker", "peek", "hitman")
        self.assertEqual(self.game.snapshot("stalker")["me"]["intel"], [])
        self.game.resolve_night()
        self.assertEqual(self.game.snapshot("stalker")["me"]["intel"][0]["role"], "hitman")
        self.assertEqual(self.game.snapshot("spy")["me"]["intel"], [])
        self.game.round = 2
        self.game.actions.clear()
        with self.assertRaises(ValueError):
            self.game.act("stalker", "peek", "spy")
        self.game.round = 3
        self.game.act("stalker", "peek", "spy")

    def test_gag_blocks_chat_only_expires_and_skips_one_round(self):
        self.game.act("hitman", "gag", "civilian")
        self.assertFalse(self.game.can_chat("civilian"))
        with self.assertRaises(ValueError):
            self.game.act("hitman", "gag", "spy")
        self.game.phase = "tribunal"
        self.game.vote("civilian", "spy")
        self.game.vote("hitman", "civilian")
        self.game.tick(self.game.deadline)
        self.assertEqual(self.game.round, 2)
        self.assertTrue(self.game.can_chat("civilian"))
        with self.assertRaises(ValueError):
            self.game.act("hitman", "gag", "civilian")
        self.game.round = 3
        self.game.act("hitman", "gag", "civilian")

    def test_hostage_silent_alive_permanent(self):
        self.night()
        self.game.act("hitman", "hostage", "civilian")
        self.game.resolve_night()
        self.game.phase = "tribunal"
        self.assertTrue(self.game.players["civilian"].alive)
        self.assertFalse(self.game.can_chat("civilian"))
        with self.assertRaises(ValueError):
            self.game.vote("civilian", "hitman")
        self.game.tick(self.game.deadline)
        self.assertFalse(self.game.can_chat("civilian"))
        for viewer in self.game.players:
            snapshot = self.game.snapshot(viewer)
            for player in snapshot["players"]:
                self.assertEqual(set(player), {"name", "alive"})
            self.assertNotIn("civilian", " ".join(snapshot["events"]))
            self.assertNotIn("actions", snapshot)
            self.assertNotIn("votes", snapshot)

    def test_wrong_role_phase_target_and_duplicate_rejected(self):
        for name, ability, target in [
            ("spy", "gag", "civilian"),
            ("hitman", "hostage", "spy"),
            ("hitman", "gag", "hitman"),
            ("hitman", "gag", "unknown"),
        ]:
            with self.assertRaises(ValueError):
                self.game.act(name, ability, target)
        self.night()
        for ability in [None, "peek", "guard"]:
            with self.assertRaises(ValueError):
                self.game.act("civilian", ability, "hitman")
        self.game.act("hitman", "hostage", "spy")
        with self.assertRaises(ValueError):
            self.game.act("hitman", "hostage", "stalker")
        self.assertFalse(self.game.can_chat("hitman"))

    def test_vote_unique_tie_and_civilian_victory(self):
        self.game.phase = "tribunal"
        self.game.vote("civilian", "hitman")
        with self.assertRaises(ValueError):
            self.game.vote("civilian", "spy")
        self.game.vote("hitman", "civilian")
        self.game.resolve_votes()
        self.assertTrue(all(p.alive for p in self.game.players.values()))
        self.game.votes.clear()
        self.game.vote("spy", "hitman")
        self.game.vote("stalker", "hitman")
        self.game.vote("hitman", "civilian")
        self.game.resolve_votes()
        self.assertEqual(self.game.winner, "civilians")
        self.assertEqual(self.game.phase, "finished")
        self.assertTrue(all("role" in p for p in self.game.snapshot("spy")["players"]))
        self.assertFalse(self.game.can_chat("spy"))

    def test_hitman_victory_when_remaining_citizens_hostage(self):
        self.game.players["civilian2"].alive = False
        self.game.players["civilian3"].alive = False
        self.game.players["spy"].alive = False
        self.game.players["stalker"].hostage = True
        self.night()
        self.game.act("hitman", "hostage", "civilian")
        self.game.resolve_night()
        self.assertEqual(self.game.winner, "hitman")

    def test_timer_and_bots_complete_games_without_browser(self):
        for seed in range(30):
            game = Match([], list("abcdef"), now=0, quick=True, rng=random.Random(seed))
            game.tick(1)
            self.assertFalse(game.bot_day_done)
            phases = set()
            for _ in range(300):
                phases.add(game.phase)
                if game.winner:
                    break
                game.tick(game.deadline)
            self.assertIsNotNone(game.winner, f"seed={seed}")
            self.assertTrue({"day", "night", "tribunal"} <= phases)


class SyndicateTests(unittest.TestCase):
    # FIXTURE: 10 pemain (3 Hitman, 2 Spy, 1 Stalker, 4 Civilian); nama = role agar skenario mudah dibaca.
    NAMES = ["hitman", "hitman2", "hitman3", "spy", "spy2", "stalker"] + [
        "civilian",
        "civilian2",
        "civilian3",
        "civilian4",
    ]

    def setUp(self, bots=False):
        self.game = Match(
            [] if bots else self.NAMES, self.NAMES if bots else [], now=0, rng=random.Random(3)
        )
        for name, player in self.game.players.items():
            player.role = name.rstrip("234")
        self.game.npc_decisions = set()

    def night(self):
        self.game.phase = "night"
        self.game.actions.clear()

    def test_one_hostage_per_night_follows_most_chosen_target(self):
        self.night()
        self.game.act("hitman", "hostage", "civilian")
        self.game.act("hitman2", "hostage", "civilian2")
        self.game.act("hitman3", "hostage", "civilian2")
        self.game.resolve_night()
        self.assertTrue(self.game.players["civilian2"].hostage)
        self.assertFalse(self.game.players["civilian"].hostage)

    def test_hostage_tie_keeps_earliest_choice_and_any_spy_guard_blocks_it(self):
        self.night()
        self.game.act("hitman2", "hostage", "civilian3")
        self.game.act("hitman", "hostage", "civilian")
        self.game.resolve_night()
        self.assertTrue(self.game.players["civilian3"].hostage)
        self.assertFalse(self.game.players["civilian"].hostage)
        self.game.round = 2
        self.night()
        self.game.act("hitman", "hostage", "civilian4")
        self.game.act("spy2", "guard", "civilian4")
        self.game.resolve_night()
        self.assertFalse(self.game.players["civilian4"].hostage)

    def test_syndicate_cannot_hostage_or_gag_allies_but_may_vote_them(self):
        for phase, ability in (("day", "gag"), ("night", "hostage")):
            self.game.phase = phase
            with self.assertRaisesRegex(ValueError, "rekan Syndicate"):
                self.game.act("hitman", ability, "hitman2")
        self.game.phase = "tribunal"
        self.game.vote("hitman", "hitman2")
        self.assertEqual(self.game.votes["hitman"], "hitman2")

    def test_gag_order_is_shared_by_the_syndicate(self):
        self.game.act("hitman", "gag", "civilian")
        with self.assertRaises(ValueError):
            self.game.act("hitman2", "gag", "spy")
        ally = self.game.snapshot("hitman2")["me"]
        self.assertEqual((ally["can_act"], ally["next_gag"]), (False, 3))
        # Warga tidak boleh tahu dari snapshot bahwa Gag sudah dipakai.
        self.assertEqual(self.game.snapshot("spy")["me"]["next_gag"], 1)
        self.game.round = 2
        with self.assertRaises(ValueError):
            self.game.act("hitman3", "gag", "spy")
        self.game.round = 3
        self.game.act("hitman3", "gag", "spy")
        self.assertTrue(self.game.players["spy"].gagged)

    def test_allies_and_their_hostage_choices_are_private_to_the_syndicate(self):
        self.night()
        self.game.act("hitman", "hostage", "stalker")
        me = self.game.snapshot("hitman2")["me"]
        self.assertEqual(me["allies"], ["hitman", "hitman3"])
        self.assertEqual(me["ally_actions"], [{"name": "hitman", "target": "stalker"}])
        self.assertEqual(self.game.snapshot("hitman")["me"]["ally_actions"], [])
        for viewer in ("spy", "stalker", "civilian"):
            snapshot = self.game.snapshot(viewer)
            self.assertEqual((snapshot["me"]["allies"], snapshot["me"]["ally_actions"]), ([], []))
            self.assertNotIn("hitman", " ".join(snapshot["events"]))
        self.game.players["hitman3"].alive = False
        self.game.phase = "day"
        me = self.game.snapshot("hitman")["me"]
        self.assertEqual((me["allies"], me["ally_actions"]), (["hitman2", "hitman3"], []))

    def test_hitman_count_is_public_and_announced_after_each_execution(self):
        def remaining():
            counts = {self.game.snapshot(name)["hitman_remaining"] for name in self.game.players}
            self.assertEqual(len(counts), 1)  # sama untuk semua viewer, termasuk Hitman
            return counts.pop()

        self.assertEqual(remaining(), 3)
        self.night()
        self.game.act("hitman", "hostage", "civilian")
        self.game.resolve_night()  # Hostage tidak mengubah hitungan: hanya eksekusi yang mengubahnya.
        self.assertEqual(remaining(), 3)
        for executed, expected in (("civilian2", 3), ("hitman2", 2)):
            self.game.phase = "tribunal"
            self.game.votes = {"spy": executed}
            self.game.resolve_votes()
            self.assertEqual(
                self.game.events[-1],
                f"Tribunal mengeksekusi {executed}. Hitman tersisa: {expected}. "
                "Role tetap dirahasiakan sampai permainan selesai.",
            )
            for phase in ("day", "night", "tribunal"):
                self.game.phase = phase
                self.assertEqual(remaining(), expected)
            # Role korban tetap rahasia; roster lawan tetap nama dan status hidup saja.
            view = self.game.snapshot("spy")
            self.assertTrue(all(set(p) == {"name", "alive"} for p in view["players"]))

    def test_hitman_count_is_available_during_preparation(self):
        game = Match([], self.NAMES, now=0, rng=random.Random(3), preparing=True)
        for name, player in game.players.items():
            player.role = name.rstrip("234")
        view = game.snapshot("civilian")
        self.assertEqual((view["phase"], view["hitman_remaining"]), ("preparing", 3))

    def test_single_hitman_room_does_not_announce_hitman_count(self):
        game = Match(["hitman", "spy", "stalker", "civilian", "civilian2", "civilian3"], [], now=0)
        for name, player in game.players.items():
            player.role = name if name in {"hitman", "spy", "stalker"} else "civilian"
        self.assertIsNone(game.snapshot("spy")["hitman_remaining"])
        game.phase = "tribunal"
        game.vote("spy", "civilian")
        game.resolve_votes()
        self.assertEqual(
            game.events[-1],
            "Tribunal mengeksekusi civilian. Role tetap dirahasiakan sampai permainan selesai.",
        )
        self.assertIsNone(game.snapshot("hitman")["hitman_remaining"])

    def test_last_hitman_execution_does_not_promise_secret_roles(self):
        self.game.players["hitman2"].alive = False
        self.game.players["hitman3"].alive = False
        self.game.phase = "tribunal"
        self.game.votes = {"spy": "hitman"}
        self.game.resolve_votes()
        # Permainan langsung selesai dan semua role dibuka, jadi tidak ada kalimat "dirahasiakan".
        self.assertEqual(self.game.events[-2], "Tribunal mengeksekusi hitman. Hitman tersisa: 0.")
        self.assertEqual(self.game.winner, "civilians")

    def test_game_continues_until_every_hitman_is_executed(self):
        self.game.phase = "tribunal"
        self.game.vote("spy", "hitman")
        self.game.tick(self.game.deadline)
        self.assertIsNone(self.game.winner)
        self.game.players["hitman2"].alive = False
        self.game.players["hitman3"].alive = False
        self.game.check_winner()
        self.assertEqual(self.game.winner_reason, "hitman_executed")
        self.assertIn("Semua Hitman dieksekusi", self.game.events[-1])
        for name, player in self.game.players.items():
            expected = "lost" if player.role == "hitman" else "won"
            self.assertEqual(self.game.result(name)["outcome"], expected)

    def test_syndicate_wins_when_free_citizens_no_longer_outnumber_living_hitmen(self):
        for name in ("spy", "spy2", "stalker"):
            self.game.players[name].hostage = True
        self.game.check_winner()
        self.assertIsNone(self.game.winner)  # Empat warga bebas masih melampaui tiga Hitman.
        self.game.players["hitman3"].alive = False
        self.game.players["civilian4"].alive = False
        self.game.check_winner()
        self.assertIsNone(self.game.winner)  # Tiga warga bebas melawan dua Hitman hidup.
        self.game.players["civilian3"].hostage = True
        self.game.check_winner()
        self.assertEqual((self.game.winner, self.game.winner_reason), ("hitman", "vote_control"))
        self.assertEqual(self.game.result("hitman")["civilians_voters"], 2)

    def test_rule_bots_follow_ally_hostage_target_and_never_target_allies(self):
        for seed in range(20):
            self.setUp(bots=True)
            self.game.rng = random.Random(seed)
            self.night()
            self.game.npc_decisions.add((1, "night", "hitman"))
            self.game.act("hitman", "hostage", "civilian2")
            self.game.run_bots()
            chosen = {
                self.game.actions[name]["target"] for name in ("hitman", "hitman2", "hitman3")
            }
            self.assertEqual(chosen, {"civilian2"}, seed)
            self.game.phase = "day"
            self.game.bot_day_done = False
            self.game.run_bots()
            gagged = [name for name, p in self.game.players.items() if p.gagged]
            self.assertEqual(len(gagged), 1)
            self.assertNotIn(self.game.players[gagged[0]].role, {"hitman"})

    def test_rule_bots_finish_every_room_size(self):
        for count in range(4, 11):
            for seed in range(10):
                game = Match([], self.NAMES[:count], now=0, quick=True, rng=random.Random(seed))
                for _ in range(300):
                    if game.winner:
                        break
                    game.tick(game.deadline)
                self.assertIsNotNone(game.winner, (count, seed))


class RoomGameTests(unittest.TestCase):
    def setUp(self):
        self.rooms = RoomService()
        self.room = self.rooms.create("alice")
        self.rooms.set_bot(self.room.code, "alice", True)

    def test_room_options_capacity_and_bot_replacement(self):
        room = self.rooms.create("host", capacity=10)
        self.rooms.set_bot(room.code, "host", True)
        self.assertEqual(len(self.rooms.bot_names(room)), 9)
        for i in range(9):
            self.rooms.join(room.code, f"guest{i}")
        self.assertEqual(self.rooms.bot_names(room), [])
        with self.assertRaises(ValueError):
            self.rooms.join(room.code, "overflow")
        self.rooms.start(room.code, "host")
        self.assertEqual(len(room.match.players), 10)
        self.assertNotIn("max_rounds", self.rooms.snapshot(room))

    def test_create_api_validates_gdd_options(self):
        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[require_authenticated_user] = lambda: SimpleNamespace(
            username="host"
        )
        with (
            patch("controller.api.rooms.room_service", self.rooms),
            patch("controller.api.rooms.PersistenceService"),
            TestClient(app) as client,
        ):
            for body in [{"capacity": 3}, {"capacity": 11}]:
                self.assertEqual(client.post("/api/rooms", json=body).status_code, 422)
            response = client.post("/api/rooms", json={"capacity": 9, "max_rounds": 6})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["capacity"], 9)
            # Payload frontend lama boleh diterima, tetapi tidak menetapkan batas ronde.
            self.assertNotIn("max_rounds", response.json())

    def test_bot_fill_host_start_rejoin_and_roster_lock(self):
        self.assertEqual(len(self.rooms.snapshot(self.room)["bots"]), 5)
        self.rooms.join(self.room.code, "bob")
        self.assertEqual(len(self.rooms.snapshot(self.room)["bots"]), 4)
        with self.assertRaises(ValueError):
            self.rooms.start(self.room.code, "bob")
        self.rooms.start(self.room.code, "alice")
        self.rooms.join(self.room.code, "bob")
        for operation in [
            lambda: self.rooms.join(self.room.code, "outsider"),
            lambda: self.rooms.set_bot(self.room.code, "alice", False),
            lambda: self.rooms.leave(self.room.code, "alice"),
            lambda: self.rooms.start(self.room.code, "alice"),
        ]:
            with self.assertRaises(ValueError):
                operation()
        self.assertEqual(
            self.rooms.state(self.room.code, "alice")["game"]["me"]["role"],
            self.room.match.players["alice"].role,
        )

    def test_stale_phase_and_nonmember(self):
        self.rooms.start(self.room.code, "alice")
        with self.assertRaises(ValueError):
            self.rooms.play(
                self.room.code,
                "alice",
                match_id="old",
                round_number=1,
                phase="day",
                target="NOX",
                ability="gag",
            )
        with self.assertRaises(ValueError):
            self.rooms.state(self.room.code, "outsider")

    def test_leave_transfers_owner_and_cleans_empty_room(self):
        self.rooms.join(self.room.code, "bob")
        self.rooms.leave(self.room.code, "alice")
        self.assertEqual(self.room.owner, "bob")
        self.rooms.leave(self.room.code, "bob")
        self.assertNotIn(self.room.code, self.rooms.rooms)

    # HTTP integration dengan identitas fixture; otorisasi room tetap service sungguhan.
    def test_http_membership_checker_and_play_validation(self):
        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[require_authenticated_user] = lambda x_user=Header(
            "alice"
        ): SimpleNamespace(username=x_user)
        with patch("controller.api.rooms.room_service", self.rooms), TestClient(app) as client:
            base = "/api/rooms/" + self.room.code
            self.assertEqual(
                client.post(
                    base + "/start", json={"quick": True}, headers={"x-user": "outsider"}
                ).status_code,
                400,
            )
            self.assertEqual(client.get(base + "/checker").status_code, 410)
            self.assertEqual(client.post(base + "/start", json={"quick": True}).status_code, 200)
            self.assertEqual(client.get(base + "/checker").status_code, 410)
            response = client.get(base + "/game")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(len(response.json()["game"]["players"]), 6)
            self.assertEqual(
                client.get(base + "/game", headers={"x-user": "outsider"}).status_code, 400
            )
            self.assertEqual(client.post(base + "/play", json={"ability": "kill"}).status_code, 422)
            self.room.match.players[
                next(n for n, p in self.room.match.players.items() if p.role == "hitman")
            ].alive = False
            self.room.match.check_winner()
            self.assertEqual(client.get(base + "/checker").status_code, 410)


class SocketGameTests(unittest.IsolatedAsyncioTestCase):
    async def test_revoked_socket_token_cannot_send(self):
        from services.auth_service import SessionValidationError

        sio = Mock(emit=AsyncMock())
        controller = SocketGameController(sio, Mock(), Mock())
        controller.socket_players["sid"] = "alice"
        controller.socket_tokens["sid"] = "revoked-test-token"
        with patch(
            "realtime.socket_handlers.auth_service.user_for_token",
            side_effect=SessionValidationError(),
        ):
            await controller.send_chat("sid", {"username": "alice", "message": "halo"})
        self.assertEqual(sio.emit.call_args.args[0], "system_alert")
        self.assertIn("login", sio.emit.call_args.args[1]["msg"])

    async def test_night_hostage_gag_malformed_and_spoof_never_echo(self):
        rooms = RoomService()
        room = rooms.create("alice")
        rooms.set_bot(room.code, "alice", True)
        rooms.start(room.code, "alice")
        sio = Mock(emit=AsyncMock(), enter_room=AsyncMock())
        controller = SocketGameController(sio, Mock(), Mock())
        controller.socket_players["sid"] = "alice"
        controller.socket_rooms["sid"] = room.code
        with (
            patch("realtime.socket_handlers.room_service", rooms),
            patch("realtime.socket_handlers.PersistenceService"),
        ):
            for data in [
                None,
                [],
                {"username": "alice", "message": {}},
                {"username": "NOX", "message": "spoof"},
            ]:
                await controller.send_chat("sid", data)
            room.match.phase = "night"
            await controller.send_chat("sid", {"username": "alice", "message": "night"})
            room.match.phase = "day"
            room.match.players["alice"].gagged = True
            await controller.send_chat("sid", {"username": "alice", "message": "gag"})
            room.match.players["alice"].gagged = False
            room.match.players["alice"].hostage = True
            await controller.send_chat("sid", {"username": "alice", "message": "hostage"})
        self.assertFalse(any(c.args[0] == "receive_chat" for c in sio.emit.call_args_list))
        self.assertEqual(room.match.messages, [])

    async def test_late_ai_cannot_speak_at_night(self):
        rooms = RoomService()
        room = rooms.create("alice")
        rooms.set_bot(room.code, "alice", True)
        rooms.start(room.code, "alice")
        room.match.begin()  # lewati layar persiapan
        room.match.ai_controlled = False  # Uji jalur balasan legacy, bukan scheduler NPC.
        sio = Mock(emit=AsyncMock(), enter_room=AsyncMock())
        analysis = Mock()
        analysis.predict_intent.return_value = "neutral"
        analysis.aggressiveness_for_intent.return_value = 0

        async def late_reply(**kwargs):
            room.match.phase = "night"
            return "Balasan terlambat"

        analysis.create_host_response = AsyncMock(side_effect=late_reply)
        controller = SocketGameController(sio, analysis, Mock())
        controller.socket_players["sid"] = "alice"
        controller.socket_rooms["sid"] = room.code
        controller.room_analysis[room.code] = analysis
        with (
            patch("realtime.socket_handlers.room_service", rooms),
            patch("realtime.socket_handlers.PersistenceService"),
        ):
            await controller.send_chat("sid", {"username": "alice", "message": "halo"})
        self.assertEqual(len(room.match.messages), 1)
        analysis.create_host_response.assert_awaited_once()
        self.assertEqual(room.match.messages[0]["sender"], "alice")
        self.assertEqual(controller.ai_pending, set())

"""Keputusan NPC diuji dengan respons model tiruan, tanpa jaringan atau database produksi."""

import asyncio
import json
import unittest
from unittest.mock import AsyncMock, Mock, patch

from services.npc_service import NPCDecision, NPCService, npc_context
from services.npc_service import request_decision
from config.settings import Settings
from services.persistence_service import PersistenceError
from services.room_service import RoomService


class NPCTests(unittest.IsolatedAsyncioTestCase):
    # Enam peserta dan role tetap membuat aturan serta batas informasi dapat diperiksa deterministik.
    def setUp(self):
        self.rooms = RoomService()
        self.room = self.rooms.create("human")
        self.rooms.set_bot(self.room.code, "human", True)
        self.rooms.start(self.room.code, "human")
        self.match = self.room.match
        for player in self.match.players.values():
            player.role = "civilian"
        self.match.players["NOX"].role = "hitman"
        self.match.players["ECHO"].role = "spy"
        self.match.players["VEIL"].role = "stalker"
        self.sio = Mock(emit=AsyncMock())
        self.service = NPCService(self.sio)
        self.rooms_patch = patch("services.npc_service.room_service", self.rooms)
        self.rooms_patch.start()
        self.persistence_patch = patch("services.npc_service.PersistenceService")
        self.persistence = self.persistence_patch.start().return_value

    async def asyncTearDown(self):
        await self.service.close()
        self.persistence_patch.stop()
        self.rooms_patch.stop()

    # Jalankan satu keputusan untuk NPC tertentu melalui validasi yang dipakai timer server.
    async def turn(self, name, decision):
        key = (self.match.id, self.match.round, self.match.phase, name)
        with patch("services.npc_service.request_decision", AsyncMock(return_value=decision)):
            await self.service.turn(self.room.code, self.match, key, npc_context(self.match, name))

    def test_context_never_contains_opponents_private_state(self):
        self.match.players["human"].hostage = True
        self.match.players["ECHO"].intel = [{"secret": "other-player-intel"}]
        context = npc_context(self.match, "NOX")
        self.assertTrue(all(set(p) == {"name", "alive"} for p in context["players"]))
        self.assertNotIn("other-player-intel", json.dumps(context))
        self.assertEqual(context["me"]["role"], "hitman")
        self.assertIn("human", context["legal_actions"]["gag"])

    def test_hostage_can_guard_but_cannot_chat_or_vote(self):
        self.match.phase = "night"
        spy = self.match.players["ECHO"]
        spy.hostage = True
        spy.last_guard, spy.last_guard_round = "human", 1
        self.match.round = 2
        context = npc_context(self.match, "ECHO")
        self.assertFalse(context["me"]["can_chat"])
        self.assertNotIn("human", context["legal_actions"]["guard"])
        self.assertIn("ECHO", context["legal_actions"]["guard"])
        self.match.act("ECHO", "guard", "ECHO")
        self.match.phase = "tribunal"
        self.assertNotIn("vote", npc_context(self.match, "ECHO")["legal_actions"])

    async def test_legal_vote_and_chat_are_persisted_then_broadcast(self):
        self.match.phase = "tribunal"
        self.match.players["VEIL"].intel = [{"round": 1, "name": "NOX", "role": "hitman"}]
        await self.turn("VEIL", NPCDecision(action="vote", target="NOX", message="Aku curiga NOX."))
        self.assertEqual(self.match.votes, {"VEIL": "NOX"})
        self.persistence.record_bot_message.assert_called_once()
        self.sio.emit.assert_awaited_once()
        self.assertEqual(self.match.messages[0]["sender"], "VEIL")

    async def test_illegal_action_does_not_change_state_and_fallback_can_act(self):
        self.match.phase = "night"
        await self.turn("NOX", NPCDecision(action="hostage", target="outsider"))
        self.assertEqual(self.match.actions, {})
        self.assertEqual(self.match.npc_decisions, set())
        self.match.run_bots()
        self.assertIn("NOX", self.match.actions)
        self.sio.emit.assert_not_awaited()

    async def test_wait_is_not_overridden_by_random_fallback(self):
        self.match.phase = "tribunal"
        await self.turn("NOX", NPCDecision())
        self.match.run_bots()
        self.assertNotIn("NOX", self.match.votes)

    async def test_stale_response_cannot_act_or_speak_in_new_phase(self):
        async def late(*args):
            self.match.phase = "night"
            return NPCDecision(action="gag", target="human", message="Terlambat")

        key = (self.match.id, 1, "day", "NOX")
        with patch("services.npc_service.request_decision", side_effect=late):
            await self.service.turn(self.room.code, self.match, key, npc_context(self.match, "NOX"))
        self.assertFalse(self.match.players["human"].gagged)
        self.assertEqual(self.match.messages, [])
        self.sio.emit.assert_not_awaited()

    async def test_persistence_failure_never_broadcasts_unsaved_chat(self):
        self.persistence.record_bot_message.side_effect = PersistenceError("fixture")
        await self.turn("NOX", NPCDecision(message="Tidak tersimpan"))
        self.assertEqual(self.match.messages, [])
        self.sio.emit.assert_not_awaited()

    async def test_scheduler_starts_without_human_chat_and_does_not_duplicate_turns(self):
        self.match.deadline -= 5
        with patch(
            "services.npc_service.request_decision",
            AsyncMock(return_value=NPCDecision(message="Alibimu?")),
        ) as request:
            self.service.schedule()
            self.service.schedule()
            await asyncio.gather(*list(self.service.tasks))
        self.assertEqual(request.await_count, 5)
        self.assertEqual(len(self.match.messages), 5)
        self.assertTrue(all(m["sender"] != "human" for m in self.match.messages))

    async def test_network_failure_is_recorded_and_timer_still_progresses(self):
        self.match.phase = "night"
        key = (self.match.id, 1, "night", "NOX")
        with patch("services.npc_service.request_decision", AsyncMock(side_effect=TimeoutError)):
            await self.service.turn(self.room.code, self.match, key, npc_context(self.match, "NOX"))
        trace = self.persistence.record_trace.call_args.args[0]
        self.assertEqual(trace["stage"], "npc_fallback")
        self.match.tick(self.match.deadline)
        self.assertEqual(self.match.phase, "tribunal")

    def test_invalid_model_json_is_rejected(self):
        for value in ['{"action":"kill"}', '{"action":"wait","role":"hitman"}', "not json"]:
            with self.assertRaises(ValueError):
                NPCDecision.model_validate_json(value)

    async def test_selected_provider_is_used_without_silent_provider_switch(self):
        for provider in ["docker", "api"]:
            config = Settings(ai_provider=provider, api_backend="openrouter")
            with (
                patch(
                    "services.npc_service.ollama_reply", AsyncMock(return_value='{"action":"wait"}')
                ) as local,
                patch(
                    "services.npc_service.openrouter_reply",
                    AsyncMock(return_value='{"action":"vote","target":"NOX"}'),
                ) as cloud,
            ):
                decision = await request_decision("private prompt", config)
                if provider == "docker":
                    self.assertEqual(decision.action, "wait")
                    local.assert_awaited_once_with("private prompt", config=config)
                    cloud.assert_not_awaited()
                else:
                    self.assertEqual(decision.target, "NOX")
                    cloud.assert_awaited_once_with("private prompt", config=config)
                    local.assert_not_awaited()

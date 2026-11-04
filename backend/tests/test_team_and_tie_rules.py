"""Aturan 3 Nov 2026: seri di Tribunal, rekan Spy, chat tim malam, dan seri pilihan Hostage.

Tanpa database: room dibuat langsung di registry, jadi tes ini juga jalan di laptop tanpa MySQL.
"""

import json
import random
import time
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from fastapi import FastAPI, Header
from fastapi.testclient import TestClient

from app.controller.api.rooms import router
from app.controller.middleware.auth import require_authenticated_user
from app.module.activity_service import activity
from app.module.checker_service import checker_service
from app.module.match_engine import (
    TEAM_CHAT_LIMIT,
    TRIBUNAL_EXTRA_QUICK_SECONDS,
    TRIBUNAL_EXTRA_SECONDS,
    Match,
    snapshot_berlabel,
)
from app.module.npc_brain.generated import otak_fuzzy
from app.module.npc_service import NPCService, riwayat_nlu
from app.module.room_service import Room, RoomService

ENAM = ["hitman", "spy", "stalker", "civilian", "civilian2", "civilian3"]
DELAPAN = ["hitman", "hitman2", "spy", "spy2", "stalker", "civilian", "civilian2", "civilian3"]
RAHASIA_HITMAN = "rahasia-syndicate-sandera-civilian"
RAHASIA_SPY = "rahasia-spy-jaga-stalker"


# Nama pemain = role (akhiran angka dibuang) supaya skenario mudah dibaca.
def pertandingan(humans, bots=(), **pilihan):
    game = Match(list(humans), list(bots), rng=random.Random(5), **pilihan)
    for name, player in game.players.items():
        player.role = name.rstrip("23")
    return game


def teks_snapshot(game, viewer):
    return json.dumps(game.snapshot(viewer), ensure_ascii=False)


class TribunalExtraTests(unittest.TestCase):
    # FIXTURE: Tribunal pertama lewat timer asli (ronde 2).
    def setUp(self):
        self.game = pertandingan(ENAM, now=0)
        self.game.tick(self.game.deadline)  # siang → malam
        self.game.tick(self.game.deadline)  # malam → siang ronde 2
        self.game.tick(self.game.deadline)  # siang → Tribunal
        self.assertEqual((self.game.round, self.game.phase), (2, "tribunal"))
        self.mulai = self.game.deadline - self.game.durations["tribunal"]

    def seri(self):
        self.game.vote("spy", "hitman")
        self.game.vote("hitman", "spy")

    def test_tie_adds_time_once_keeps_votes_and_then_ends_without_execution(self):
        self.seri()
        self.assertFalse(self.game.snapshot("spy")["tribunal_extra"])
        batas = self.game.deadline
        self.game.tick(batas)
        self.assertEqual(
            (self.game.phase, self.game.deadline), ("tribunal", batas + TRIBUNAL_EXTRA_SECONDS)
        )
        self.assertEqual(self.game.votes, {"spy": "hitman", "hitman": "spy"})
        self.assertIn("Suara seri. Tribunal ditambah 30 detik", self.game.events[-1])
        # Penanda publik: sama untuk semua pemain.
        for viewer in self.game.players:
            self.assertTrue(self.game.snapshot(viewer)["tribunal_extra"])
        # Sebelum waktu tambahan habis tidak ada yang berubah.
        self.game.tick(batas + TRIBUNAL_EXTRA_SECONDS - 1)
        self.assertEqual(self.game.phase, "tribunal")
        self.game.tick(self.game.deadline)
        self.assertEqual((self.game.phase, self.game.round), ("night", 2))
        self.assertTrue(all(p.alive for p in self.game.players.values()))
        self.assertTrue(any("tanpa eksekusi" in event for event in self.game.events[-2:]))
        self.assertFalse(self.game.snapshot("spy")["tribunal_extra"])

    def test_votes_can_be_cancelled_and_recast_during_extra_time(self):
        self.seri()
        self.game.tick(self.game.deadline)
        self.assertTrue(self.game.snapshot("spy")["me"]["can_cancel_vote"])
        self.game.cancel_vote("spy")
        self.game.vote("spy", "civilian")  # boleh pindah ke nama yang tidak seri
        self.game.vote("stalker", "civilian")
        self.game.tick(self.game.deadline)
        self.assertFalse(self.game.players["civilian"].alive)
        self.assertEqual(self.game.phase, "night")

    def test_no_votes_is_not_a_tie_and_gets_no_extra_time(self):
        self.game.tick(self.game.deadline)
        self.assertEqual(self.game.phase, "night")
        self.assertFalse(any("Suara seri" in event for event in self.game.events))

    def test_single_leader_is_executed_at_the_first_deadline(self):
        self.game.vote("spy", "civilian")
        self.game.vote("stalker", "civilian")
        self.game.vote("hitman", "spy")
        self.game.tick(self.game.deadline)
        self.assertFalse(self.game.players["civilian"].alive)
        self.assertFalse(any("Suara seri" in event for event in self.game.events))

    def test_quick_mode_uses_its_own_extra_time(self):
        game = pertandingan(ENAM, now=0, quick=True)
        game.phase = "tribunal"
        game.vote("spy", "hitman")
        game.vote("hitman", "spy")
        batas = game.deadline
        game.tick(batas)
        self.assertEqual(game.deadline, batas + TRIBUNAL_EXTRA_QUICK_SECONDS)
        self.assertIn("ditambah 10 detik", game.events[-1])

    def test_extra_time_is_available_again_on_the_next_tribunal(self):
        self.seri()
        self.game.tick(self.game.deadline)
        self.game.tick(self.game.deadline)  # masih seri → malam
        self.game.tick(self.game.deadline)  # malam → siang ronde 3
        self.game.tick(self.game.deadline)  # siang → Tribunal ronde 3
        self.assertEqual((self.game.round, self.game.phase), (3, "tribunal"))
        self.assertFalse(self.game.snapshot("spy")["tribunal_extra"])
        self.seri()
        batas = self.game.deadline
        self.game.tick(batas)
        self.assertEqual(
            (self.game.phase, self.game.deadline), ("tribunal", batas + TRIBUNAL_EXTRA_SECONDS)
        )

    # Hitungan waktu dari deadline tidak boleh mundur saat waktu ditambah.
    def test_phase_length_keeps_elapsed_time_running_through_the_extension(self):
        self.seri()
        panjang = self.game.durations["tribunal"]
        self.assertEqual(self.game.phase_length(), panjang)
        batas = self.game.deadline
        self.game.tick(batas)
        self.assertEqual(self.game.phase_length(), panjang + TRIBUNAL_EXTRA_SECONDS)
        self.assertEqual(self.game.deadline - self.game.phase_length(), self.mulai)
        self.assertEqual(self.game.phase_length() - (self.game.deadline - batas), panjang)
        self.game.tick(self.game.deadline)
        self.assertEqual(self.game.phase_length(), self.game.durations["night"])

    # Bot: bot yang sudah vote tidak pindah suara, bot yang belum vote masih bisa memutuskan.
    def test_bots_keep_their_votes_and_undecided_bots_may_still_vote(self):
        bots = ["hitman", "spy", "stalker", "civilian2", "civilian3"]
        game = pertandingan(["civilian"], bots, now=0)
        game.round, game.phase = 2, "tribunal"
        for bot in bots:
            game.npc_decisions.add((2, "tribunal", bot))  # otak sudah memutuskan: tanpa cadangan
        game.vote("civilian", "hitman")
        game.vote("spy", "stalker")
        game.tick(game.deadline)
        self.assertTrue(game.tribunal_extra)
        self.assertEqual(game.snapshot("spy")["me"]["vote"], "stalker")
        self.assertFalse(game.snapshot("spy")["me"]["can_vote"])
        self.assertTrue(game.snapshot("civilian2")["me"]["can_vote"])
        game.vote("civilian2", "hitman")
        game.tick(game.deadline)
        self.assertEqual(game.winner, "civilians")

    # Cadangan engine mengisi suara bot yang otaknya gagal sekali per Tribunal, sebelum seri diperiksa.
    def test_fallback_votes_run_once_even_with_extra_time(self):
        bots = ["hitman", "spy", "stalker", "civilian2", "civilian3"]
        game = pertandingan(["civilian"], bots, now=0)
        game.round, game.phase = 2, "tribunal"
        game.npc_decisions = {(2, "tribunal", bot) for bot in bots[1:]}  # otak hitman gagal
        game.rng = Mock(shuffle=lambda daftar: daftar.sort())  # cadangan memilih "civilian"
        game.vote("civilian", "stalker")
        game.vote("spy", "stalker")
        game.vote("stalker", "civilian")
        game.tick(game.deadline)
        self.assertEqual(game.votes["hitman"], "civilian")
        self.assertTrue(game.tribunal_extra)
        game.cancel_vote("hitman")
        game.tick(game.deadline)
        self.assertNotIn("hitman", game.votes)
        self.assertFalse(game.players["stalker"].alive)
        self.assertEqual(game.phase, "night")


class BrainExtraTimeTests(unittest.TestCase):
    # Otak hasil ekspor tidak diubah: selama waktu tambahan, porsi fase tetap penuh, bot yang sudah vote
    # tidak memilih lagi, dan keputusan bot lain tetap berjalan.
    def test_brains_keep_deciding_without_moving_votes_already_cast(self):
        game = pertandingan([], ENAM, now=0.0)
        game.round, game.phase = 2, "tribunal"
        otak = {nama: otak_fuzzy.Ingatan(nama) for nama in ENAM}
        for nama, ingatan in otak.items():
            ingatan.sinkron_snapshot(game.snapshot(nama), 1.0)
        game.vote("spy", "hitman")
        game.vote("hitman", "spy")
        game.npc_decisions = {(2, "tribunal", nama) for nama in ENAM}
        game.tick(game.deadline)
        self.assertTrue(game.tribunal_extra)
        sekarang = game.deadline - 5
        for nama, ingatan in otak.items():
            view = ingatan.sinkron_snapshot(game.snapshot(nama), sekarang)
            self.assertEqual(otak_fuzzy.waktu_berjalan(ingatan, view), 1.0)
            aksi = otak_fuzzy.putuskan(ingatan, view)["npc_decision"]["action"]
            if nama in ("spy", "hitman"):
                self.assertNotEqual(aksi, "vote", nama)

    # Bot yang pertama melangkah saat waktu tambahan tetap mencatat awal Tribunal yang sebenarnya.
    def test_first_step_in_extra_time_keeps_the_real_phase_start(self):
        for cepat in (False, True):
            game = pertandingan([], ENAM, now=0.0, quick=cepat)
            game.round, game.phase, game.deadline = 2, "tribunal", 500.0
            mulai = game.deadline - game.durations["tribunal"]
            game.vote("spy", "hitman")
            game.vote("hitman", "spy")
            game.npc_decisions = {(2, "tribunal", nama) for nama in ENAM}
            game.tick(game.deadline)
            self.assertTrue(game.tribunal_extra)
            ingatan = otak_fuzzy.Ingatan("stalker", cepat=cepat)
            view = ingatan.sinkron_snapshot(game.snapshot("stalker"), game.deadline - 1)
            self.assertEqual(ingatan.mulai_fase[(2, "tribunal")], mulai)
            self.assertTrue(view["tribunal_tambahan"])

    def test_extra_time_in_brain_matches_engine(self):
        self.assertEqual(otak_fuzzy.TAMBAHAN_TRIBUNAL, TRIBUNAL_EXTRA_SECONDS)
        self.assertEqual(otak_fuzzy.TAMBAHAN_TRIBUNAL_CEPAT, TRIBUNAL_EXTRA_QUICK_SECONDS)


class SchedulerExtraTimeTests(unittest.IsolatedAsyncioTestCase):
    # Jadwal bot membaca lama fase dari deadline: waktu tambahan tidak boleh membuat bot menunggu
    # seolah fase baru dimulai (quick 4 pemain: Tribunal 10 detik + tambahan 10 detik).
    async def test_elapsed_does_not_jump_back_when_time_is_added(self):
        rooms = RoomService()
        game = Match(["human"], ["NOX", "ECHO", "VEIL"], quick=True)
        room = Room("ABC123", "human", ["human"], match=game)
        game.ai_controlled = True
        rooms.rooms[room.code] = room
        runtime = Mock()
        runtime.otak_bot.return_value = Mock(sibuk=False)
        service = NPCService(Mock(emit=AsyncMock()), runtime=runtime)
        game.round, game.phase = 2, "tribunal"
        game.npc_decisions = {(2, "tribunal", bot) for bot in ("NOX", "ECHO", "VEIL")}
        game.vote("human", "NOX")
        game.vote("NOX", "human")
        sekarang = time.time()
        game.deadline = sekarang
        game.tick(sekarang)
        self.assertTrue(game.tribunal_extra)
        with (
            patch("app.module.npc_service.room_service", rooms),
            patch.object(service, "_sudah_waktunya_melangkah", return_value=False) as jadwal,
        ):
            service.jalankan_bot_yang_sudah_waktunya()
        elapsed = jadwal.call_args.args[2]
        self.assertAlmostEqual(elapsed, game.durations["tribunal"], delta=1)
        await service.close()


class HostageTieTests(unittest.TestCase):
    TIGA = ["hitman", "hitman2", "hitman3"]

    def malam(self, humans, bots):
        warga = ["spy", "spy2", "stalker", "civilian", "civilian2", "civilian3", "civilian4"]
        game = pertandingan(humans + warga, bots, now=0)
        game.phase = "night"
        return game

    def test_human_choice_wins_a_tie_against_a_bot_in_either_order(self):
        for urutan in (("hitman", "hitman2"), ("hitman2", "hitman")):
            game = self.malam(["hitman"], ["hitman2"])
            pilihan = {"hitman": "civilian", "hitman2": "civilian2"}
            for nama in urutan:
                game.act(nama, "hostage", pilihan[nama])
            self.assertEqual(game.syndicate_target(), "civilian", urutan)
            self.assertEqual(game.snapshot("hitman2")["me"]["syndicate_target"], "civilian")
            game.resolve_night()
            self.assertTrue(game.players["civilian"].hostage)
            self.assertFalse(game.players["civilian2"].hostage)

    def test_same_kind_ties_keep_the_earliest_choice(self):
        for humans, bots in ((["hitman", "hitman2"], []), ([], ["hitman", "hitman2"])):
            game = self.malam(humans, bots)
            game.act("hitman2", "hostage", "civilian2")
            game.act("hitman", "hostage", "civilian")
            self.assertEqual(game.syndicate_target(), "civilian2")

    def test_majority_still_beats_a_human_choice(self):
        game = self.malam(["hitman"], ["hitman2", "hitman3"])
        game.act("hitman", "hostage", "civilian")
        game.act("hitman2", "hostage", "civilian2")
        game.act("hitman3", "hostage", "civilian2")
        self.assertEqual(game.syndicate_target(), "civilian2")

    def test_cancelling_the_human_choice_returns_the_target_to_the_bot(self):
        game = self.malam(["hitman"], ["hitman2"])
        game.act("hitman2", "hostage", "civilian2")
        game.act("hitman", "hostage", "civilian")
        game.cancel_action("hitman")
        self.assertEqual(game.syndicate_target(), "civilian2")


class SpyAlliesTests(unittest.TestCase):
    def setUp(self):
        self.game = pertandingan(DELAPAN, now=0)
        self.game.phase = "night"

    def test_spies_know_each_other_and_their_guard_choices(self):
        self.game.act("spy", "guard", "civilian")
        self.game.act("hitman", "hostage", "stalker")
        me = self.game.snapshot("spy2")["me"]
        self.assertEqual(me["spy_allies"], ["spy"])
        self.assertEqual(me["spy_actions"], [{"name": "spy", "target": "civilian"}])
        # Pilihan sendiri tidak diulang di daftar rekan, dan kode bot tetap membaca allies sebagai Syndicate.
        self.assertEqual(self.game.snapshot("spy")["me"]["spy_actions"], [])
        self.assertEqual(self.game.snapshot("spy")["me"]["spy_allies"], ["spy2"])
        self.assertEqual((me["allies"], me["ally_actions"]), ([], []))
        # Pilihan rekan hanya berlaku malam ini; daftar rekan tetap ada.
        self.game.phase = "day"
        me = self.game.snapshot("spy2")["me"]
        self.assertEqual((me["spy_allies"], me["spy_actions"]), (["spy"], []))

    def test_other_roles_get_empty_values(self):
        self.game.act("spy", "guard", "civilian")
        for viewer in ("hitman", "stalker", "civilian"):
            me = self.game.snapshot(viewer)["me"]
            self.assertEqual((me["spy_allies"], me["spy_actions"]), ([], []), viewer)
            self.assertNotIn("guard", json.dumps(me["ally_actions"]))

    def test_rooms_with_one_spy_have_no_spy_allies(self):
        for count in (4, 5, 6):
            game = Match([str(i) for i in range(count)], [], now=0)
            game.phase = "night"
            spy = next(n for n, p in game.players.items() if p.role == "spy")
            me = game.snapshot(spy)["me"]
            self.assertEqual((me["spy_allies"], me["spy_actions"]), ([], []), count)

    def test_bot_snapshot_translates_spy_names_to_labels(self):
        labels = {name: f"Nama {name}" for name in DELAPAN}
        game = pertandingan([], DELAPAN, now=0, labels=labels)
        game.phase = "night"
        game.act("spy", "guard", "civilian")
        me = snapshot_berlabel(game.snapshot("spy2"), game.labels)["me"]
        self.assertEqual(me["spy_allies"], ["Nama spy"])
        self.assertEqual(me["spy_actions"], [{"name": "Nama spy", "target": "Nama civilian"}])
        # Snapshot asli tetap memakai username.
        self.assertEqual(game.snapshot("spy2")["me"]["spy_allies"], ["spy"])

    def test_bot_snapshot_translates_team_data_to_labels(self):
        labels = {name: f"Nama {name}" for name in DELAPAN}
        game = pertandingan(["hitman"], [n for n in DELAPAN if n != "hitman"], now=0, labels=labels)
        game.act("hitman2", "gag", "civilian")
        game.phase = "night"
        pesan = {"id": "t1", "sender": "hitman", "message": RAHASIA_HITMAN}
        game.team_messages["hitman"].append(pesan)
        snapshot = game.snapshot("hitman2")
        # Bot belum menerima pesan tim dari engine (Fase 7), jadi bentuknya ditiru di sini.
        snapshot["me"]["team_messages"] = [pesan]
        me = snapshot_berlabel(snapshot, game.labels)["me"]
        self.assertEqual(me["ally_gags"], ["Nama civilian"])
        self.assertEqual(me["team_messages"][0]["sender"], "Nama hitman")
        self.assertEqual(me["team_humans"], ["Nama hitman"])
        # Salinan: snapshot asli tetap memakai username.
        self.assertEqual(snapshot["me"]["ally_gags"], ["civilian"])
        self.assertEqual(pesan["sender"], "hitman")


class TeamChatTests(unittest.TestCase):
    def setUp(self):
        self.game = pertandingan(DELAPAN, now=0)
        self.game.phase = "night"

    def test_channels_are_separate_and_reach_only_the_team(self):
        self.game.add_team_message("hitman", f"  {RAHASIA_HITMAN}  ")
        self.game.add_team_message("spy2", RAHASIA_SPY)
        for viewer in ("hitman", "hitman2"):
            me = self.game.snapshot(viewer)["me"]
            self.assertTrue(me["can_team_chat"])
            self.assertEqual([m["message"] for m in me["team_messages"]], [RAHASIA_HITMAN])
            self.assertEqual(me["team_messages"][0]["sender"], "hitman")
            self.assertNotIn(RAHASIA_SPY, teks_snapshot(self.game, viewer))
        for viewer in ("spy", "spy2"):
            me = self.game.snapshot(viewer)["me"]
            self.assertEqual([m["message"] for m in me["team_messages"]], [RAHASIA_SPY])
            self.assertNotIn(RAHASIA_HITMAN, teks_snapshot(self.game, viewer))
        for viewer in ("stalker", "civilian", "civilian2", "civilian3"):
            me = self.game.snapshot(viewer)["me"]
            self.assertEqual((me["can_team_chat"], me["team_messages"]), (False, []))
            self.assertNotIn(RAHASIA_HITMAN, teks_snapshot(self.game, viewer))
            self.assertNotIn(RAHASIA_SPY, teks_snapshot(self.game, viewer))

    # Pesan tim tidak pernah muncul di data publik: chat, catatan, atau nomor urut chat publik.
    def test_team_messages_never_touch_public_data_or_public_message_ids(self):
        self.game.phase = "day"
        pertama = self.game.add_message("civilian", "pesan publik pertama")
        self.game.phase = "night"
        self.game.add_team_message("hitman", RAHASIA_HITMAN)
        self.game.add_team_message("spy", RAHASIA_SPY)
        self.assertEqual(self.game.jumlah_pesan, 1)
        self.game.phase = "day"
        kedua = self.game.add_message("civilian", "pesan publik kedua")
        # Lompatan nomor pada ID akan memberi tahu warga bahwa ada pesan rahasia.
        self.assertEqual(int(kedua["id"][:6]), int(pertama["id"][:6]) + 1)
        for viewer in DELAPAN:
            snapshot = self.game.snapshot(viewer)
            for teks in (RAHASIA_HITMAN, RAHASIA_SPY):
                self.assertNotIn(teks, json.dumps(snapshot["messages"]))
                self.assertNotIn(teks, json.dumps(snapshot["events"]))
        self.assertEqual([m["message"] for m in self.game.messages],
                         ["pesan publik pertama", "pesan publik kedua"])  # fmt: skip

    # Di luar malam dan di layar hasil tidak ada pesan tim untuk siapa pun, termasuk timnya sendiri.
    def test_team_messages_are_absent_outside_the_night_and_on_the_result_screen(self):
        self.game.add_team_message("hitman", RAHASIA_HITMAN)
        self.game.add_team_message("spy", RAHASIA_SPY)
        for phase in ("day", "tribunal"):
            self.game.phase = phase
            for viewer in DELAPAN:
                me = self.game.snapshot(viewer)["me"]
                self.assertEqual((me["can_team_chat"], me["team_messages"]), (False, []))
        self.game.phase = "night"
        self.game.players["hitman"].alive = False
        self.game.players["hitman2"].alive = False
        self.game.check_winner()
        self.assertEqual((self.game.phase, self.game.winner), ("finished", "civilians"))
        for viewer in DELAPAN:
            teks = teks_snapshot(self.game, viewer)
            self.assertNotIn(RAHASIA_HITMAN, teks)
            self.assertNotIn(RAHASIA_SPY, teks)
            self.assertEqual(self.game.snapshot(viewer)["me"]["team_messages"], [])
            self.assertNotIn(RAHASIA_HITMAN, json.dumps(self.game.result(viewer)))

    def test_only_entitled_players_may_send(self):
        for nama in ("civilian", "stalker"):
            with self.assertRaisesRegex(ValueError, "Chat tim tidak tersedia"):
                self.game.add_team_message(nama, "halo")
        # Spy yang disandera dan pemain yang sudah tersingkir kehilangan chat tim dan isinya.
        self.game.add_team_message("spy", RAHASIA_SPY)
        self.game.players["spy2"].hostage = True
        self.game.players["hitman2"].alive = False
        for nama in ("spy2", "hitman2"):
            me = self.game.snapshot(nama)["me"]
            self.assertEqual((me["can_team_chat"], me["team_messages"]), (False, []))
            with self.assertRaisesRegex(ValueError, "Chat tim tidak tersedia"):
                self.game.add_team_message(nama, "halo")
        # Gag hanya membatasi chat publik.
        self.game.players["spy"].gagged = True
        self.game.add_team_message("spy", "tetap bisa")
        # Hanya saat malam.
        self.game.phase = "day"
        with self.assertRaisesRegex(ValueError, "Chat tim tidak tersedia"):
            self.game.add_team_message("hitman", "siang")

    def test_rooms_without_two_of_a_role_have_no_channel(self):
        for count in (4, 5, 6):
            game = Match([str(i) for i in range(count)], [], now=0)
            game.phase = "night"
            for name in game.players:
                self.assertFalse(game.snapshot(name)["me"]["can_team_chat"], (count, name))
                with self.assertRaises(ValueError):
                    game.add_team_message(name, "halo")

    def test_channel_stays_open_for_the_survivor_of_a_two_player_team(self):
        self.game.players["spy"].alive = False
        self.game.add_team_message("spy2", RAHASIA_SPY)
        self.assertEqual(len(self.game.snapshot("spy2")["me"]["team_messages"]), 1)

    def test_message_length_matches_public_chat_and_history_is_capped(self):
        for teks in ("   ", "x" * 1001):
            with self.assertRaisesRegex(ValueError, "1–1000"):
                self.game.add_team_message("hitman", teks)
        self.game.add_team_message("hitman", "x" * 1000)
        for nomor in range(TEAM_CHAT_LIMIT + 5):
            self.game.add_team_message("hitman", f"pesan {nomor}")
            self.game.add_team_message("spy", f"pesan {nomor}")
        for viewer in ("hitman", "spy"):
            pesan = self.game.snapshot(viewer)["me"]["team_messages"]
            self.assertEqual(len(pesan), TEAM_CHAT_LIMIT)
            self.assertEqual(pesan[-1]["message"], f"pesan {TEAM_CHAT_LIMIT + 4}")

    # Chat tim hanya ada di view bot: di ingatan.chat ia akan terbaca sebagai bukti publik.
    def test_team_messages_stay_out_of_bot_chat_memory(self):
        self.game.add_team_message("hitman2", RAHASIA_HITMAN)
        ingatan = otak_fuzzy.Ingatan("hitman")
        view = ingatan.sinkron_snapshot(self.game.snapshot("hitman"), 1.0)
        self.assertEqual(ingatan.chat, [])
        self.assertEqual(view["saya"]["chat_tim"][0]["pengirim"], "hitman2")
        self.assertEqual(view["saya"]["chat_tim"][0]["teks"], RAHASIA_HITMAN)
        self.assertEqual(ingatan._chat_tim["jumlah"], 1)
        self.assertNotIn(RAHASIA_HITMAN, json.dumps(ingatan._chat_tim))

    # Rekan manusia hanya diberitahukan ke bot: pemain manusia tidak boleh tahu siapa bot.
    def test_team_humans_are_told_only_to_bots(self):
        manusia = ["hitman", "spy", "civilian"]
        game = pertandingan(manusia, [n for n in DELAPAN if n not in manusia], now=0)
        self.assertEqual(game.snapshot("hitman2")["me"]["team_humans"], ["hitman"])
        self.assertEqual(game.snapshot("spy2")["me"]["team_humans"], ["spy"])
        for bot in ("stalker", "civilian2", "civilian3"):
            self.assertEqual(game.snapshot(bot)["me"]["team_humans"], [])
        for orang in manusia:
            self.assertEqual(game.snapshot(orang)["me"]["team_humans"], [])
        # Sesama bot tidak masuk daftar.
        semua_bot = pertandingan([], DELAPAN, now=0)
        self.assertEqual(semua_bot.snapshot("hitman")["me"]["team_humans"], [])

    # Bot belum membaca chat tim: snapshot, ingatan, dan prompt LLM mode pembanding bersih.
    def test_bots_on_the_team_do_not_receive_team_messages(self):
        game = pertandingan(
            ["hitman", "spy"], [n for n in DELAPAN if n not in ("hitman", "spy")], now=0
        )
        game.phase = "night"
        game.add_team_message("hitman", RAHASIA_HITMAN)
        game.add_team_message("spy", RAHASIA_SPY)
        self.assertEqual(len(game.snapshot("hitman")["me"]["team_messages"]), 1)
        for bot in ("hitman2", "spy2"):
            me = game.snapshot(bot)["me"]
            self.assertEqual((me["can_team_chat"], me["team_messages"]), (False, []))
            with self.assertRaises(ValueError):
                game.add_team_message(bot, "bot belum bicara")
            pandangan = json.dumps(
                snapshot_berlabel(game.snapshot(bot), game.labels), ensure_ascii=False
            )
            self.assertNotIn(RAHASIA_HITMAN, pandangan)
            self.assertNotIn(RAHASIA_SPY, pandangan)
            ingatan = otak_fuzzy.Ingatan(bot)
            ingatan.sinkron_snapshot(snapshot_berlabel(game.snapshot(bot), game.labels), 1.0)
            self.assertEqual(ingatan.chat, [])


class TeamChatEndpointTests(unittest.TestCase):
    def setUp(self):
        self.rooms = RoomService()
        self.game = pertandingan(DELAPAN)
        self.game.phase = "night"
        self.room = Room("ABC123", "hitman", list(DELAPAN), match=self.game)
        self.rooms.rooms[self.room.code] = self.room
        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[require_authenticated_user] = lambda x_user=Header(
            "hitman"
        ): SimpleNamespace(username=x_user)
        self.client = TestClient(app)
        patcher = patch("app.controller.api.rooms.room_service", self.rooms)
        patcher.start()
        self.addCleanup(patcher.stop)

    def post(self, user, **ubah):
        body = {"match_id": self.game.id, "round_number": self.game.round, "phase": "night",
                "message": RAHASIA_HITMAN} | ubah  # fmt: skip
        return self.client.post(
            f"/api/rooms/{self.room.code}/team-chat", json=body, headers={"x-user": user}
        )

    def test_sender_gets_the_private_snapshot_and_teammate_reads_it(self):
        respons = self.post("hitman")
        self.assertEqual(respons.status_code, 200)
        pesan = respons.json()["game"]["me"]["team_messages"]
        self.assertEqual([(m["sender"], m["message"]) for m in pesan], [("hitman", RAHASIA_HITMAN)])
        rekan = self.client.get(
            f"/api/rooms/{self.room.code}/game", headers={"x-user": "hitman2"}
        ).json()
        self.assertEqual(rekan["game"]["me"]["team_messages"], pesan)
        warga = self.client.get(f"/api/rooms/{self.room.code}/game", headers={"x-user": "civilian"})
        self.assertNotIn(RAHASIA_HITMAN, warga.text)

    def test_phase_token_role_and_payload_are_validated(self):
        self.assertEqual(self.post("hitman", match_id="lama").status_code, 400)
        self.assertEqual(self.post("hitman", round_number=9).status_code, 400)
        self.assertEqual(self.post("hitman", phase="day").status_code, 422)
        self.assertEqual(self.post("hitman", message="").status_code, 422)
        self.assertEqual(self.post("hitman", message="x" * 1001).status_code, 422)
        self.assertEqual(self.post("hitman", message="   ").status_code, 400)
        self.assertEqual(self.post("civilian").status_code, 400)
        self.assertEqual(self.post("orang_luar").status_code, 400)
        self.assertEqual(self.game.team_messages, {"hitman": [], "spy": []})

    def test_stale_message_after_the_night_ends_is_rejected(self):
        ronde = self.game.round
        self.game.deadline = time.time() - 1
        self.assertEqual(self.post("hitman", round_number=ronde).status_code, 400)
        self.assertEqual(self.game.team_messages["hitman"], [])

    # Privasi: pesan tim tidak masuk jejak aktivitas panel, checker, riwayat NLU, atau database.
    def test_team_message_stays_out_of_activity_checker_nlu_and_database(self):
        with (
            patch("app.controller.api.rooms.PersistenceService") as arsip,
            patch("app.module.npc_service.PersistenceService") as arsip_npc,
        ):
            self.assertEqual(self.post("hitman").status_code, 200)
        arsip.assert_not_called()
        arsip_npc.assert_not_called()
        self.assertNotIn(RAHASIA_HITMAN, json.dumps(activity.list(self.room.code), default=str))
        self.assertEqual(checker_service.list(self.room.code), [])
        self.assertNotIn(self.game.id, riwayat_nlu)
        self.assertEqual(self.game.messages, [])
        self.assertNotIn(RAHASIA_HITMAN, json.dumps(self.game.events))


if __name__ == "__main__":
    unittest.main()

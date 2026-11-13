"""Malam dan chat tim bot: engine asli, otak hasil ekspor, dan NPCService dengan rekan manusia tiruan.

Uji main dengan manusia sungguhan tidak ada di sini: rekan manusia ditiru lewat Match.act dan add_team_message.
"""

import json
import random
import time
import unittest
from unittest.mock import AsyncMock, Mock, patch

from app.game.match_engine import Match, snapshot_berlabel
from app.bot import fuzzy_controller
from app.bot import ingatan as ingatan_bot
from app.bot.bot_controller import BrainRuntime
from app.bot.nlu import NLUBersama
from app.bot.bot_controller import NPCService, riwayat_nlu, tulis_kalimat_tim
from app.services.room_service import pindahkan_aksi_malam
from app.services.activity_service import activity
from app.services.checker_service import checker_service
from app.services.room_service import Room, RoomService
from tests.palsu.arsip_palsu import arsip_bot_palsu
from tests.palsu.nlu_palsu import NLUPalsu
from app.bot.nlg_controller import tulis_chat_tim

DELAPAN = ["hitman", "hitman2", "spy", "spy2", "stalker", "civilian", "civilian2", "civilian3"]
RAHASIA = "rahasia-tim-jangan-bocor"


# Nama pemain = role (akhiran angka dibuang) supaya skenario mudah dibaca.
def pertandingan(humans, bots=(), **pilihan):
    game = Match(list(humans), list(bots), rng=random.Random(5), **pilihan)
    for name, player in game.players.items():
        player.role = name.rstrip("23")
    return game


def lainnya(*manusia):
    return [n for n in DELAPAN if n not in manusia]


def malam(game, ronde=1):
    game.round, game.phase, game.actions = ronde, "night", {}
    game.deadline = 1000.0
    return game


# Satu langkah keputusan bot seperti NPCService.brain_turn, tanpa jaringan.
def langkah(game, ingatan, nama, sekarang):
    view = ingatan.sinkron_snapshot(snapshot_berlabel(game.snapshot(nama), game.labels), sekarang)
    return view, fuzzy_controller.putuskan(ingatan, view)


# Pilihan otak diterapkan ke engine seperti _kirim_vote_atau_aksi.
def terapkan(game, nama, npc):
    if npc["action"] in fuzzy_controller.AKSI_RAHASIA:
        if npc.get("pindah"):
            pindahkan_aksi_malam(game, nama, npc["action"], npc["target"])
        else:
            game.act(nama, npc["action"], npc["target"])


class EngineTests(unittest.TestCase):
    def test_bots_read_and_send_team_messages(self):
        game = malam(pertandingan(["hitman"], lainnya("hitman")))
        self.assertTrue(game.can_team_chat("hitman2"))
        game.add_team_message("hitman2", "Aku incar civilian.")
        self.assertEqual(game.snapshot("hitman")["me"]["team_messages"][0]["sender"], "hitman2")
        game.add_team_message("hitman", "Oke.")
        self.assertEqual(len(game.snapshot("hitman2")["me"]["team_messages"]), 2)
        self.assertEqual(game.snapshot("civilian")["me"]["team_messages"], [])

    def test_team_humans_leave_the_list_once_eliminated(self):
        game = pertandingan(["hitman", "spy"], lainnya("hitman", "spy"))
        self.assertEqual(game.snapshot("hitman2")["me"]["team_humans"], ["hitman"])
        game.players["hitman"].alive = False
        game.players["spy"].left = True
        game.players["spy"].alive = False
        self.assertEqual(game.snapshot("hitman2")["me"]["team_humans"], [])
        self.assertEqual(game.snapshot("spy2")["me"]["team_humans"], [])

    def test_moving_a_night_choice_restores_the_old_one_when_rejected(self):
        game = malam(pertandingan(["hitman"], lainnya("hitman")))
        game.act("hitman", "hostage", "civilian")
        game.act("hitman2", "hostage", "civilian2")
        urutan = list(game.actions)
        with self.assertRaises(ValueError):
            pindahkan_aksi_malam(game, "hitman2", "hostage", "hitman")
        self.assertEqual(game.actions["hitman2"]["target"], "civilian2")
        self.assertEqual(list(game.actions), urutan)
        pindahkan_aksi_malam(game, "hitman2", "hostage", "civilian")
        self.assertEqual(game.actions["hitman2"]["target"], "civilian")
        self.assertEqual(game.syndicate_target(), "civilian")


class BrainOnEngineTests(unittest.TestCase):
    # Manusia sudah memilih target lain sebelum batas: bot belum pindah, lalu pindah tepat di batas.
    def test_hitman_moves_exactly_at_the_lock(self):
        for cepat, batas in ((False, 15), (True, 10)):
            game = malam(pertandingan(["hitman"], lainnya("hitman"), quick=cepat))
            ingatan = ingatan_bot.Ingatan("hitman2", cepat=cepat)
            mulai = game.deadline - game.durations["night"]
            _, h = langkah(game, ingatan, "hitman2", mulai + 1)
            terapkan(game, "hitman2", h["npc_decision"])
            pilihan_bot = game.actions["hitman2"]["target"]
            target_manusia = next(n for n in ("civilian", "civilian2", "spy") if n != pilihan_bot)
            game.act("hitman", "hostage", target_manusia)
            _, h = langkah(game, ingatan, "hitman2", game.deadline - batas - 0.5)
            self.assertEqual(h["npc_decision"]["action"], "wait")
            _, h = langkah(game, ingatan, "hitman2", game.deadline - batas)
            self.assertEqual(
                h["npc_decision"],
                {"action": "hostage", "target": target_manusia, "message": "", "pindah": True},
            )
            self.assertEqual(h["nlg_tim"]["pemicu"], "ikut_manusia")
            terapkan(game, "hitman2", h["npc_decision"])
            self.assertEqual(game.actions["hitman2"]["target"], target_manusia)

    def test_human_change_after_the_lock_wins_and_the_bot_stays(self):
        game = malam(pertandingan(["hitman"], lainnya("hitman")))
        ingatan = ingatan_bot.Ingatan("hitman2")
        game.act("hitman", "hostage", "civilian")
        _, h = langkah(game, ingatan, "hitman2", game.deadline - 15)
        self.assertEqual(h["npc_decision"]["target"], "civilian")
        terapkan(game, "hitman2", h["npc_decision"])
        game.cancel_action("hitman")
        game.act("hitman", "hostage", "civilian2")
        _, h = langkah(game, ingatan, "hitman2", game.deadline - 5)
        self.assertEqual(h["npc_decision"]["action"], "wait")
        self.assertIsNone(h["nlg_tim"])
        self.assertEqual(game.actions["hitman2"]["target"], "civilian")
        self.assertEqual(game.syndicate_target(), "civilian2")

    def test_human_spy_choosing_the_same_target_moves_the_bot(self):
        game = malam(pertandingan(["spy"], lainnya("spy")))
        ingatan = ingatan_bot.Ingatan("spy2")
        _, h = langkah(game, ingatan, "spy2", game.deadline - 25)
        terapkan(game, "spy2", h["npc_decision"])
        self.assertEqual(h["nlg_tim"]["pemicu"], "pilih_target")
        lama = game.actions["spy2"]["target"]
        ingatan.catat_chat_tim({"ronde": 1}, h["nlg_tim"], True)
        game.act("spy", "guard", lama)
        _, h = langkah(game, ingatan, "spy2", game.deadline - 20)
        self.assertTrue(h["npc_decision"]["pindah"])
        self.assertEqual(
            (h["nlg_tim"]["pemicu"], h["nlg_tim"]["pilihan_rekan"]), ("pindah_sama", lama)
        )
        terapkan(game, "spy2", h["npc_decision"])
        self.assertNotEqual(game.actions["spy2"]["target"], lama)
        # Target bot kini lain, jadi langkah berikutnya tetap dan diam.
        _, h = langkah(game, ingatan, "spy2", game.deadline - 18)
        self.assertEqual(h["npc_decision"]["action"], "wait")
        self.assertIsNone(h["nlg_tim"])

    def test_spy_does_not_move_after_the_lock(self):
        game = malam(pertandingan(["spy"], lainnya("spy")))
        ingatan = ingatan_bot.Ingatan("spy2")
        _, h = langkah(game, ingatan, "spy2", game.deadline - 25)
        terapkan(game, "spy2", h["npc_decision"])
        game.act("spy", "guard", game.actions["spy2"]["target"])
        _, h = langkah(game, ingatan, "spy2", game.deadline - 15)
        self.assertEqual(h["npc_decision"]["action"], "wait")
        self.assertIsNone(h["nlg_tim"])

    def test_two_bot_spies_do_not_share_a_target_and_stay_silent(self):
        game = malam(pertandingan([], DELAPAN))
        otak = {n: ingatan_bot.Ingatan(n) for n in ("spy", "spy2")}
        for nama, ingatan in otak.items():
            _, h = langkah(game, ingatan, nama, game.deadline - 25)
            self.assertIsNone(h["nlg_tim"])
            terapkan(game, nama, h["npc_decision"])
        self.assertNotEqual(game.actions["spy"]["target"], game.actions["spy2"]["target"])

    # Dua bot terlanjur memilih target sama (langkahnya bertumpuk): hanya satu yang pindah.
    def test_racing_bot_spies_are_separated_by_one_move(self):
        game = malam(pertandingan([], DELAPAN))
        game.act("spy", "guard", "civilian")
        game.act("spy2", "guard", "civilian")
        otak = {n: ingatan_bot.Ingatan(n) for n in ("spy", "spy2")}
        for nama, ingatan in otak.items():
            _, h = langkah(game, ingatan, nama, game.deadline - 25)
            terapkan(game, nama, h["npc_decision"])
        self.assertEqual(game.actions["spy"]["target"], "civilian")
        self.assertNotEqual(game.actions["spy2"]["target"], "civilian")

    def test_guard_may_repeat_the_same_target(self):
        game = malam(pertandingan([], DELAPAN), ronde=2)
        game.players["spy"].last_guard, game.players["spy"].last_guard_round = "civilian", 1
        ingatan = ingatan_bot.Ingatan("spy")
        ingatan.sinkron_snapshot(
            snapshot_berlabel(game.snapshot("spy"), game.labels), game.deadline - 29
        )
        ingatan.chat.append({"id": "a", "ronde": 2, "fase": "day", "waktu": 1.0, "pengirim": "civilian", "teks": "Aku Stalker.",
                             "intent": "neutral", "conf_intent": 0.9, "target": []})  # fmt: skip
        _, h = langkah(game, ingatan, "spy", game.deadline - 28)
        self.assertEqual(h["npc_decision"]["target"], "civilian")
        terapkan(game, "spy", h["npc_decision"])
        game.resolve_night()
        self.assertEqual(game.players["spy"].last_guard, "civilian")

    # Peek selalu terpakai dan selalu sah bagi engine, juga saat semua pemain sudah diperiksa.
    def test_peek_fallback_is_accepted_by_the_engine(self):
        game = malam(pertandingan([], DELAPAN), ronde=5)
        game.players["stalker"].intel = [
            {"round": 1, "name": n, "role": game.players[n].role}
            for n in DELAPAN
            if n not in ("stalker", "hitman", "hitman2")
        ] + [{"round": 2, "name": n, "role": "civilian"} for n in ("hitman", "hitman2")]
        _, h = langkah(game, ingatan_bot.Ingatan("stalker"), "stalker", game.deadline - 25)
        self.assertEqual(h["npc_decision"]["action"], "peek")
        terapkan(game, "stalker", h["npc_decision"])
        self.assertIn("stalker", game.actions)

    # Urutan A, A, B: A tetap dilewati walau B gagal di antaranya, dan engine menerima target penggantinya.
    def test_target_failed_twice_stays_skipped_after_another_failure(self):
        game = malam(pertandingan([], DELAPAN), ronde=4)
        game.syndicate_log = [
            {"round": 1, "name": "spy", "success": False},
            {"round": 2, "name": "spy", "success": False},
            {"round": 3, "name": "spy2", "success": False},
        ]
        _, h = langkah(game, ingatan_bot.Ingatan("hitman"), "hitman", game.deadline - 25)
        self.assertEqual(h["pengetahuan"]["gagal_sandera"], {"spy": 2, "spy2": 1})
        self.assertEqual(h["npc_decision"]["action"], "hostage")
        self.assertNotEqual(h["npc_decision"]["target"], "spy")
        terapkan(game, "hitman", h["npc_decision"])
        self.assertIn("hitman", game.actions)

    # Dua Spy yang saling menjaga: Hitman keluar dari keduanya, dan Hostage berikutnya bisa berhasil.
    def test_hitman_leaves_both_targets_guarded_by_two_spies(self):
        game = malam(pertandingan([], DELAPAN), ronde=5)
        game.syndicate_log = [
            {"round": r, "name": nama, "success": False}
            for r, nama in enumerate(("spy", "spy", "spy2", "spy2"), 1)
        ]
        _, h = langkah(game, ingatan_bot.Ingatan("hitman"), "hitman", game.deadline - 25)
        self.assertNotIn(h["npc_decision"]["target"], ("spy", "spy2"))
        terapkan(game, "hitman", h["npc_decision"])
        game.act("spy", "guard", "spy2")
        game.act("spy2", "guard", "spy")
        game.resolve_night()
        self.assertTrue(game.syndicate_log[-1]["success"])

    # Semua target sudah gagal dua kali: Hostage tetap terpakai, bukan menunggu.
    def test_all_targets_failed_twice_still_picks_one(self):
        warga = [n for n in DELAPAN if not n.startswith("hitman")]
        game = malam(pertandingan([], DELAPAN), ronde=2 * len(warga) + 1)
        game.syndicate_log = [
            {"round": 2 * i + k + 1, "name": nama, "success": False}
            for i, nama in enumerate(warga)
            for k in range(2)
        ]
        _, h = langkah(game, ingatan_bot.Ingatan("hitman"), "hitman", game.deadline - 25)
        self.assertEqual(set(h["pengetahuan"]["gagal_sandera"].values()), {2})
        self.assertEqual(h["npc_decision"]["action"], "hostage")
        terapkan(game, "hitman", h["npc_decision"])
        self.assertIn("hitman", game.actions)

    def test_hostage_and_peek_never_wait_while_the_engine_allows_them(self):
        for nama in ("hitman", "stalker", "spy"):
            game = malam(pertandingan([], DELAPAN))
            _, h = langkah(game, ingatan_bot.Ingatan(nama), nama, game.deadline - 25)
            self.assertNotEqual(h["npc_decision"]["action"], "wait", nama)
            terapkan(game, nama, h["npc_decision"])
            self.assertIn(nama, game.actions)


class TeamWriterTests(unittest.TestCase):
    def test_template_answer_passes_and_public_payloads_have_no_team_role(self):
        p = {"pembicara": "NOX", "aksi": "chat_tim", "tim": "hitman", "pemicu": "beda", "target_saya": "ECHO",
             "pilihan_rekan": "VEIL", "alasan": ["ECHO menuduh atau vote aku."], "chat_tim": []}  # fmt: skip
        hasil = tulis_chat_tim(p, ["NOX", "ECHO", "VEIL", "RAVEN"])
        self.assertEqual(hasil["sumber"], "templat")
        self.assertIn("ECHO", hasil["teks"])
        self.assertNotIn("tim", fuzzy_controller.siapkan_nlg(fuzzy_controller.rencana_chat({"aksi": "jawab", "target": None, "alasan": []}),
                                                       {"saya": {"nama": "NOX"}}))  # fmt: skip


class NPCTeamChatTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.runtime = BrainRuntime()
        self.runtime.penulis_npc.konfigurasi.penulis = "templat"
        self.runtime.muat_sekarang(nlu=NLUBersama(NLUPalsu(r"curiga", r"bukan hitman"), "cadangan"))
        self.rooms = RoomService()
        self.game = pertandingan(["hitman"], lainnya("hitman"))
        self.game.ai_controlled = True
        malam(self.game)
        self.game.deadline = time.time() + 30
        self.room = Room("MLM123", "hitman", list(DELAPAN), match=self.game)
        self.rooms.rooms[self.room.code] = self.room
        self.sio = Mock(emit=AsyncMock())
        self.service = NPCService(self.sio, runtime=self.runtime)
        self.enterContext(patch("app.bot.bot_controller.room_service", self.rooms))
        self.persistence = self.enterContext(arsip_bot_palsu())
        self.runtime.siapkan_pertandingan(self.game, self.room.code)
        self.otak = self.runtime.otak_bot(self.game.id, "hitman2")

    async def asyncTearDown(self):
        await self.service.close()
        self.runtime.tutup()

    async def langkah_bot(self, otak=None):
        await self.service.brain_turn(self.room.code, self.game, otak or self.otak)

    async def test_bot_tells_its_human_teammate_and_nothing_leaks(self):
        self.game.add_team_message("hitman", RAHASIA)
        await self.langkah_bot()
        self.assertIn("hitman2", self.game.actions)
        target = self.game.actions["hitman2"]["target"]
        pesan = self.game.snapshot("hitman")["me"]["team_messages"]
        self.assertEqual([m["sender"] for m in pesan], ["hitman", "hitman2"])
        self.assertIn(target, pesan[1]["message"])
        # Bukan chat publik, bukan database, bukan siaran, bukan NLU.
        self.assertEqual(self.game.messages, [])
        self.assertEqual(self.game.jumlah_pesan, 0)
        self.persistence.return_value.record_bot_message.assert_not_called()
        self.sio.emit.assert_not_awaited()
        self.assertNotIn(self.game.id, riwayat_nlu)
        self.assertEqual(self.otak.ingatan.chat, [])
        self.assertEqual(self.otak.riwayat, [])
        # Ingatan hanya mencatat pemicunya.
        self.assertEqual(self.otak.ingatan.chat_tim_bot[0]["pemicu"], "pilih_target")
        self.assertNotIn(RAHASIA, str(vars(self.otak.ingatan)))
        self.assertNotIn(pesan[1]["message"], str(vars(self.otak.ingatan)))
        # Jejak panel hanya memuat status dan panjang teks, bukan isi pesan siapa pun.
        jejak = self.persistence.return_value.record_trace.call_args.args[0]
        self.assertEqual(
            json.loads(jejak["output"])["chat_tim"],
            {"status": "terkirim", "panjang": len(pesan[1]["message"])},
        )
        teks_jejak = json.dumps(jejak, ensure_ascii=False, default=str)
        self.assertNotIn(RAHASIA, teks_jejak)
        self.assertNotIn(pesan[1]["message"], teks_jejak)
        for jejak_ingatan in checker_service.list(self.room.code):
            self.assertNotIn(RAHASIA, json.dumps(jejak_ingatan, ensure_ascii=False, default=str))
        self.assertNotIn(RAHASIA, json.dumps(activity.list(self.room.code), default=str))
        # Warga tidak melihat apa pun.
        self.assertNotIn(RAHASIA, json.dumps(self.game.snapshot("civilian"), default=str))
        self.assertNotIn(
            pesan[1]["message"], json.dumps(self.game.snapshot("civilian"), default=str)
        )

    async def test_public_nlg_context_never_carries_team_messages(self):
        self.game.add_team_message("hitman", RAHASIA)
        snapshot = snapshot_berlabel(self.game.snapshot("hitman2"), self.game.labels)
        view, keputusan, konteks = self.runtime.langkah(self.otak, snapshot, time.time())
        self.assertIn(RAHASIA, json.dumps(view["saya"]["chat_tim"]))
        self.assertIn(RAHASIA, json.dumps(keputusan["nlg_tim"]["chat_tim"]))
        self.assertNotIn(RAHASIA, json.dumps(konteks, default=str))
        self.assertIsNone(keputusan["nlg"])
        self.assertNotIn(RAHASIA, json.dumps(keputusan["penjelasan"], default=str))
        self.assertNotIn(RAHASIA, json.dumps(keputusan["nlu_baru"], default=str))
        self.assertNotIn(RAHASIA, self.runtime.nlu._memo.__repr__())

    async def test_empty_answer_records_the_trigger_without_a_message(self):
        with patch.object(
            self.runtime, "tulis_tim", return_value={"teks": "", "sumber": "llm_kosong"}
        ):
            await self.langkah_bot()
        self.assertEqual(self.game.snapshot("hitman")["me"]["team_messages"], [])
        self.assertEqual(self.otak.ingatan.chat_tim_bot[0]["terkirim"], False)
        jejak = self.persistence.return_value.record_trace.call_args.args[0]
        self.assertEqual(
            json.loads(jejak["output"])["chat_tim"], {"status": "kosong", "panjang": 0}
        )

    async def test_late_sentence_is_dropped_when_the_night_is_over(self):
        def tulis(*_):
            self.game.deadline = time.time() - 1
            return {"teks": "Aku incar civilian.", "sumber": "templat"}

        with patch.object(self.runtime, "tulis_tim", side_effect=tulis):
            await self.langkah_bot()
        self.assertEqual(self.game.team_messages["hitman"], [])
        self.assertFalse(self.otak.ingatan.chat_tim_bot[0]["terkirim"])

    # Sisa malam pendek: batas tulis mengikuti sisa malam, lalu kabar tetap sampai lewat templat.
    async def test_slow_writer_falls_back_to_template(self):
        asli = self.runtime.tulis_tim
        payload = {"pembicara": "hitman2", "aksi": "chat_tim", "tim": "hitman", "pemicu": "ikut_manusia", "target_saya": "civilian",
                   "pilihan_rekan": "civilian", "alasan": [], "chat_tim": []}  # fmt: skip

        def lambat(otak, p, roster, pakai_llm=True):
            if pakai_llm:
                time.sleep(1.5)
                return {"teks": "terlambat", "sumber": "llm"}
            return asli(otak, p, roster, False)

        with patch.object(self.runtime, "tulis_tim", side_effect=lambat):
            hasil = await tulis_kalimat_tim(self.runtime, self.otak, payload, list(DELAPAN), 2.5)
        self.assertEqual(hasil["sumber"], "templat")
        self.assertIn("civilian", hasil["teks"])

    async def test_rejected_choice_is_not_announced(self):
        keputusan = {"npc_decision": {"action": "hostage", "target": "hitman", "message": ""},
                     "rencana_chat": fuzzy_controller.rencana_chat_tunggu("malam"), "nlg": None,
                     "nlg_tim": {"pemicu": "pilih_target"}}  # fmt: skip
        with patch.object(self.runtime, "langkah", return_value=({"ronde": 1}, keputusan, {"roster": []})), \
                patch.object(self.runtime, "tulis_tim") as tulis:  # fmt: skip
            await self.langkah_bot()
        tulis.assert_not_called()
        self.assertEqual(self.game.team_messages["hitman"], [])

    async def test_all_bot_team_stays_silent_and_eliminated_human_stops_the_chat(self):
        semua_bot = pertandingan([], DELAPAN)
        semua_bot.ai_controlled = True
        malam(semua_bot)
        semua_bot.deadline = time.time() + 30
        self.rooms.rooms["MLM456"] = Room("MLM456", "hitman", list(DELAPAN), match=semua_bot)
        self.runtime.siapkan_pertandingan(semua_bot, "MLM456")
        await self.service.brain_turn(
            "MLM456", semua_bot, self.runtime.otak_bot(semua_bot.id, "hitman")
        )
        self.assertIn("hitman", semua_bot.actions)
        self.assertEqual(semua_bot.team_messages["hitman"], [])

        self.game.players["hitman"].alive = False
        await self.langkah_bot()
        self.assertIn("hitman2", self.game.actions)
        self.assertEqual(self.game.team_messages["hitman"], [])

    async def test_hostage_human_spy_receives_no_messages(self):
        spy = self.runtime.otak_bot(self.game.id, "spy2")
        self.game.players["spy"].bot = False
        self.game.players["spy"].hostage, self.game.players["spy"].hostage_round = True, 1
        await self.langkah_bot(spy)
        self.assertIn("spy2", self.game.actions)
        self.assertEqual(self.game.team_messages["spy"], [])

    # Rekan manusia tiruan satu malam penuh: bot memilih, manusia memilih lain, bot menanggapi sekali, lalu ikut saat terkunci.
    async def test_full_night_with_a_simulated_human_teammate(self):
        sekarang = time.time()
        self.game.deadline = sekarang + 40
        await self.langkah_bot()
        target_bot = self.game.actions["hitman2"]["target"]
        lain = next(n for n in ("civilian", "civilian2", "spy") if n != target_bot)
        self.game.act("hitman", "hostage", lain)
        await self.langkah_bot()
        await self.langkah_bot()  # tanggapan yang sama tidak diulang
        self.assertEqual(len(self.game.team_messages["hitman"]), 2)
        self.game.deadline = time.time() + 15
        await self.langkah_bot()
        self.assertEqual(self.game.actions["hitman2"]["target"], lain)
        pesan = self.game.team_messages["hitman"]
        self.assertEqual(len(pesan), 3)
        self.assertIn(lain, pesan[-1]["message"])
        self.assertEqual([x["pemicu"] for x in self.otak.ingatan.chat_tim_bot][-1], "ikut_manusia")
        self.game.cancel_action("hitman")
        self.game.act("hitman", "hostage", target_bot)
        self.game.deadline = time.time() + 5
        await self.langkah_bot()
        self.assertEqual(self.game.actions["hitman2"]["target"], lain)
        self.assertEqual(self.game.syndicate_target(), target_bot)
        self.assertEqual(len(self.game.team_messages["hitman"]), 3)


if __name__ == "__main__":
    unittest.main()

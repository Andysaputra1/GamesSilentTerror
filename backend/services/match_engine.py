"""Engine aturan murni: tidak bergantung HTTP, Socket.IO, MySQL, atau LLM.

RoomService memegang lock ketika memanggil engine. Snapshot selalu dibuat
untuk satu pemain: role, Hostage, Gag, dan hasil Peek tidak masuk data publik.
"""

from math import ceil
from collections import Counter
from dataclasses import dataclass, field
import random
import time
from uuid import uuid4


@dataclass
class Participant:
    name: str
    role: str
    bot: bool = False
    alive: bool = True
    hostage: bool = False
    gagged: bool = False
    next_gag: int = 1
    next_peek: int = 1
    last_guard: str | None = None
    last_guard_round: int = 0
    intel: list[dict] = field(default_factory=list)


# Durasi mengikuti roster awal (manusia + NPC), bukan jumlah warga bebas yang bersifat rahasia.
def phase_durations(count, quick=False):
    if quick:
        return {
            "day": ceil(count * 10 / 3),
            "night": ceil(count * 2.5),
            "tribunal": ceil(count * 2.5),
        }
    return {"day": count * 20, "night": count * 5, "tribunal": ceil(count * 7.5)}


class Match:
    # CONSTRUCTOR: acak role di server; tepat satu Hitman, Spy, dan Stalker.
    def __init__(self, humans, bots, *, quick=False, max_rounds=8, now=None, rng=None):
        names = list(humans) + list(bots)
        if not 4 <= len(names) <= 10 or len(set(names)) != len(names):
            raise ValueError("Permainan membutuhkan 4–10 identitas berbeda.")
        if max_rounds not in {6, 8, 12}:
            raise ValueError("Pilih durasi 6, 8, atau 12 ronde.")
        self.rng = rng or random.SystemRandom()
        roles = ["hitman", "spy", "stalker"] + ["civilian"] * (len(names) - 3)
        self.rng.shuffle(roles)
        self.players = {
            name: Participant(name, role, name in bots) for name, role in zip(names, roles)
        }
        self.id = uuid4().hex
        self.round = 1
        self.max_rounds = max_rounds
        self.ai_controlled = (
            False  # Diaktifkan RoomService; unit engine tetap dapat diuji tanpa jaringan.
        )
        self.npc_decisions = set()
        self.ai_grace_phase = None
        self.phase = "day"
        self.durations = phase_durations(len(names), quick)
        self.deadline = (time.time() if now is None else now) + self.durations["day"]
        self.actions = {}
        self.votes = {}
        self.skip_consents = set()
        self.events = ["Permainan dimulai. Diskusikan alibi tanpa membocorkan identitasmu."]
        self.messages = []
        self.winner = None
        self.winner_reason = None
        self.bot_day_done = False
        self.bot_night_done = False
        self.bot_vote_done = False

    def reserve_ai_reply(self, now=None):
        """At most one bounded extension per phase; manual skip still takes precedence."""
        now = time.time() if now is None else now
        phase = (self.round, self.phase)
        if self.phase in {"day", "tribunal"} and self.ai_grace_phase != phase:
            self.ai_grace_phase = phase
            self.deadline = max(self.deadline, now + 35)

    # HELPER: Hostage menghapus suara, bukan nyawa atau skill malam milik warga.
    def actor(self, name):
        player = self.players.get(name)
        if not player or not player.alive or self.phase == "finished":
            raise ValueError("Kamu tidak dapat melakukan aksi ini.")
        return player

    # VALIDASI CHAT: Gag/Hostage/kematian dan fase malam ditegakkan di backend.
    def can_chat(self, name):
        player = self.players.get(name)
        return bool(
            player
            and player.alive
            and not player.hostage
            and not player.gagged
            and self.phase in {"day", "tribunal"}
        )

    # VALIDASI TARGET: tidak boleh memilih pemain mati atau identitas di luar pertandingan.
    def target(self, actor, name, *, allow_self=False):
        target = self.players.get(name)
        if not target or not target.alive or (name == actor.name and not allow_self):
            raise ValueError("Target tidak valid.")
        return target

    # AKSI PRIVAT: pilihan malam disimpan, belum diresolusikan sebelum deadline.
    def act(self, name, ability, target_name):
        player = self.actor(name)
        if ability == "gag":
            if self.phase != "day" or player.role != "hitman" or self.round < player.next_gag:
                raise ValueError("Gag Order belum tersedia.")
            target = self.target(player, target_name)
            target.gagged = True
            player.next_gag = self.round + 2
            return
        expected = {"hitman": "hostage", "spy": "guard", "stalker": "peek"}.get(player.role)
        if expected is None or self.phase != "night" or ability != expected or name in self.actions:
            raise ValueError("Aksi malam tidak tersedia atau sudah dikunci.")
        self.target(player, target_name, allow_self=ability == "guard")
        if (
            ability == "guard"
            and player.last_guard == target_name
            and player.last_guard_round == self.round - 1
        ):
            raise ValueError("Tidak boleh Guard target yang sama dua malam berturut-turut.")
        if ability == "peek" and self.round < player.next_peek:
            raise ValueError("Peek hanya tersedia sekali setiap dua ronde.")
        self.actions[name] = {"ability": ability, "target": target_name}

    # VOTE: satu pilihan final; hanya Hostage/kematian yang mencabut suara, bukan Gag Order.
    def vote(self, name, target_name):
        player = self.actor(name)
        if self.phase != "tribunal" or player.hostage or name in self.votes:
            raise ValueError("Voting tidak tersedia atau pilihan sudah dikunci.")
        self.target(player, target_name)
        self.votes[name] = target_name

    # RESOLUSI MALAM: semua pilihan dibaca bersama, Guard diprioritaskan terhadap Hostage.
    def resolve_night(self):
        guards = set()
        for name, action in self.actions.items():
            player = self.players[name]
            target = action["target"]
            if action["ability"] == "guard":
                guards.add(target)
                player.last_guard = target
                player.last_guard_round = self.round
            elif action["ability"] == "peek":
                player.intel.append(
                    {"round": self.round, "name": target, "role": self.players[target].role}
                )
                player.next_peek = self.round + 2
        for action in self.actions.values():
            if action["ability"] == "hostage" and action["target"] not in guards:
                self.players[action["target"]].hostage = True
        # Rekap identik untuk semua hasil, termasuk kegagalan atau target yang sudah Hostage.
        self.events.append(
            "Malam selesai. Semua aksi telah diselesaikan; identitas dan target tidak diumumkan."
        )
        self.check_winner()

    # RESOLUSI TRIBUNAL: plurality; seri/tanpa suara tidak mengeksekusi siapa pun.
    def resolve_votes(self):
        counts = Counter(self.votes.values())
        leaders = (
            [name for name, count in counts.items() if count == max(counts.values())]
            if counts
            else []
        )
        if len(leaders) == 1:
            self.players[leaders[0]].alive = False
            self.events.append(
                f"Tribunal mengeksekusi {leaders[0]}. Role tetap dirahasiakan sampai permainan selesai."
            )
        else:
            self.events.append("Tribunal berakhir tanpa eksekusi: suara seri atau tidak ada suara.")
        self.check_winner()
        if not self.winner and self.round >= self.max_rounds:
            self.finish(
                "draw", "round_limit", f"Batas {self.max_rounds} ronde tercapai tanpa pemenang."
            )

    def finish(self, winner, reason, explanation):
        """Satu hasil final untuk semua pemain; tidak berubah oleh tick berikutnya."""
        if self.winner:
            return
        self.winner = winner
        self.winner_reason = reason
        self.phase = "finished"
        label = {
            "civilians": "Kubu warga menang.",
            "hitman": "Hitman menang.",
            "draw": "Permainan seri.",
        }[winner]
        self.events.append(f"{label} {explanation}")

    # GDD: warga menang dengan eksekusi Hitman; Hitman menang ketika suara warga bebas tidak melampaui satu.
    def check_winner(self):
        if self.winner:
            return
        hitman = next(player for player in self.players.values() if player.role == "hitman")
        survivors = [p for p in self.players.values() if p.role != "hitman" and p.alive]
        if not hitman.alive:
            self.finish("civilians", "hitman_executed", "Hitman dieksekusi oleh Tribunal.")
        elif not survivors:
            self.finish("hitman", "no_civilians_alive", "Tidak ada warga yang masih hidup.")
        elif all(p.hostage for p in survivors):
            self.finish(
                "hitman", "all_survivors_hostage", "Semua warga yang masih hidup telah disandera."
            )
        elif sum(not p.hostage for p in survivors) <= 1:
            self.finish(
                "hitman",
                "vote_control",
                "Suara warga yang masih hidup dan bebas tidak lagi melampaui suara Hitman.",
            )

    def result(self, viewer):
        """Ringkasan hanya setelah selesai; korban tetap bagian dari kubu warga."""
        if not self.winner:
            return None
        team = "hitman" if self.players[viewer].role == "hitman" else "civilians"
        civilians = [p for p in self.players.values() if p.role != "hitman"]
        return {
            "reason": self.winner_reason,
            "team": team,
            "outcome": (
                "draw" if self.winner == "draw" else "won" if team == self.winner else "lost"
            ),
            "civilians_alive": sum(p.alive for p in civilians),
            "civilians_hostage": sum(p.alive and p.hostage for p in civilians),
            "civilians_eliminated": sum(not p.alive for p in civilians),
            "civilians_voters": sum(p.alive and not p.hostage for p in civilians),
        }

    # BOT ATURAN: aksi/vote mengikuti validasi yang sama; tidak melihat role atau Hostage lawan.
    def run_bots(self):
        flag = {"day": "bot_day_done", "night": "bot_night_done", "tribunal": "bot_vote_done"}.get(
            self.phase
        )
        if not flag or getattr(self, flag):
            return
        setattr(self, flag, True)
        for player in self.players.values():
            if not player.bot or not player.alive or (player.hostage and self.phase != "night"):
                continue
            if (self.round, self.phase, player.name) in self.npc_decisions:
                continue
            targets = [
                other.name
                for other in self.players.values()
                if other.alive and other.name != player.name
            ]
            self.rng.shuffle(targets)
            if self.phase == "tribunal":
                # Stalker hanya memakai intel hasil Peek miliknya sendiri.
                known = [
                    item["name"]
                    for item in player.intel
                    if item["role"] == "hitman" and item["name"] in targets
                ]
                targets = known + [name for name in targets if name not in known]
            for target in targets:
                try:
                    if self.phase == "tribunal":
                        self.vote(player.name, target)
                    else:
                        ability = (
                            "gag"
                            if self.phase == "day"
                            else {"hitman": "hostage", "spy": "guard", "stalker": "peek"}.get(
                                player.role
                            )
                        )
                        self.act(player.name, ability, target)
                    break
                except ValueError:
                    continue

    # SKIP DISKUSI: hanya manusia hidup; status bungkam tidak memengaruhi hak persetujuan.
    def skip_discussion(self, name, *, now=None):
        player = self.players.get(name)
        if self.phase != "day" or not player or player.bot or not player.alive:
            raise ValueError("Persetujuan skip hanya untuk pemain manusia hidup saat siang.")
        self.skip_consents.add(name)
        required = {p.name for p in self.players.values() if not p.bot and p.alive}
        if required and required <= self.skip_consents:
            # Gunakan transisi yang sama dengan timer, termasuk kesempatan aksi bot.
            now = time.time() if now is None else now
            self.events.append("Semua pemain manusia menyetujui akhir diskusi.")
            self.deadline = now
            self.tick(now)

    # TIMER SERVER: maju satu fase saat deadline; tetap berjalan walaupun semua tab ditutup.
    def tick(self, now=None):
        now = time.time() if now is None else now
        # Scheduler LLM mendapat waktu memilih; fallback aturan hanya mengisi pilihan yang kosong di deadline.
        if self.phase != "finished" and now >= self.deadline:
            self.run_bots()
        if self.phase == "finished" or now < self.deadline:
            return
        if self.phase == "day":
            self.phase = "night"
            self.actions = {}
            self.events.append("Malam tiba. Chat dikunci; lakukan aksi secara rahasia.")
        elif self.phase == "night":
            self.resolve_night()
            if not self.winner:
                self.phase = "tribunal"
                self.votes = {}
        else:
            self.resolve_votes()
            if not self.winner:
                self.round += 1
                self.phase = "day"
                self.skip_consents.clear()
                self.bot_day_done = self.bot_night_done = self.bot_vote_done = False
                for player in self.players.values():
                    player.gagged = False
                self.events.append(f"Ronde {self.round}: diskusi siang dimulai.")
        if not self.winner:
            self.deadline = now + self.durations[self.phase]
        self.events = self.events[-40:]

    # PESAN PUBLIK: hanya dipanggil setelah pemeriksaan can_chat; ID mencegah duplikasi saat reconnect.
    def add_message(self, sender, message):
        record = {"id": uuid4().hex, "sender": sender, "message": message}
        self.messages.append(record)
        self.messages = self.messages[-100:]
        return record

    # SNAPSHOT PRIVAT: roster hanya mengandung alive; status diam orang lain tidak pernah dikirim.
    def snapshot(self, viewer):
        player = self.players[viewer]
        ability = (
            "gag"
            if self.phase == "day" and player.role == "hitman"
            else (
                {"hitman": "hostage", "spy": "guard", "stalker": "peek"}.get(player.role)
                if self.phase == "night"
                else None
            )
        )
        can_act = bool(ability and player.alive and not self.winner)
        if ability == "gag":
            can_act &= self.round >= player.next_gag
        elif ability:
            can_act &= viewer not in self.actions and (
                ability != "peek" or self.round >= player.next_peek
            )
        return {
            # Vote yang sudah dikirim terbuka saat Tribunal, tanpa daftar hak vote/status bungkam.
            "tribunal_votes": (
                [
                    {
                        "target": name,
                        "voters": [voter for voter, target in self.votes.items() if target == name],
                    }
                    for name in self.players
                ]
                if self.phase == "tribunal"
                else []
            ),
            "discussion_skip": {
                "agreed": len(self.skip_consents) if self.phase == "day" else 0,
                "required": sum(not p.bot and p.alive for p in self.players.values()),
                "consented": viewer in self.skip_consents if self.phase == "day" else False,
                "can_consent": self.phase == "day"
                and not player.bot
                and player.alive
                and viewer not in self.skip_consents,
            },
            "id": self.id,
            "phase": self.phase,
            "round": self.round,
            "max_rounds": self.max_rounds,
            "deadline": self.deadline,
            "server_time": time.time(),
            "winner": self.winner,
            "events": list(self.events),
            "result": self.result(viewer),
            "players": [
                {
                    "name": p.name,
                    "alive": p.alive,
                    **({"role": p.role, "hostage": p.hostage, "bot": p.bot} if self.winner else {}),
                }
                for p in self.players.values()
            ],
            "messages": list(self.messages),
            "me": {
                "name": viewer,
                "role": player.role,
                "alive": player.alive,
                "hostage": player.hostage,
                "gagged": player.gagged,
                "muted": player.hostage or player.gagged,
                "can_chat": self.can_chat(viewer),
                "can_vote": self.phase == "tribunal"
                and player.alive
                and not player.hostage
                and viewer not in self.votes,
                "vote": self.votes.get(viewer),
                "ability": ability,
                "can_act": bool(can_act),
                "action": self.actions.get(viewer) if self.phase == "night" else None,
                "next_gag": player.next_gag,
                "next_peek": player.next_peek,
                "last_guard": (
                    player.last_guard if player.last_guard_round == self.round - 1 else None
                ),
                "intel": list(player.intel),
            },
        }

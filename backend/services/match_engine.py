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

from services.skin_constants import ALL_SKINS, SKIN_BY_BOT


@dataclass
class Participant:
    name: str
    role: str
    bot: bool = False
    alive: bool = True
    hostage: bool = False
    gagged: bool = False
    next_peek: int = 1
    last_guard: str | None = None
    last_guard_round: int = 0
    intel: list[dict] = field(default_factory=list)
    skin_id: str = "dexter"


# Layar persiapan: minimal cukup untuk membaca panduan, maksimal agar model yang gagal dimuat tidak menahan room.
PREPARATION_MIN_SECONDS = 8
PREPARATION_MAX_SECONDS = 90

# Komposisi role per jumlah peserta: (hitman, spy, stalker); sisanya civilian.
# Dipilih lewat simulasi keseimbangan semua kursi bot metode campuran, dengan pengumuman jumlah Hitman tersisa
# (hitman_remaining); data dan alasannya ada di GAME_CONCEPT.md, bagian Ruangan dan role.
KOMPOSISI_PERAN = {
    4: (1, 1, 1),
    5: (1, 1, 1),
    6: (1, 1, 1),
    7: (1, 1, 1),
    8: (2, 2, 1),
    9: (2, 2, 1),
    10: (2, 2, 1),
}
NIGHT_ABILITY = {"hitman": "hostage", "spy": "guard", "stalker": "peek"}


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
    # Role mengikuti KOMPOSISI_PERAN; skin_map mempertahankan avatar manusia yang dipilih.
    # preparing=True menahan ronde 1 di layar persiapan sampai AI siap (lihat begin/mark_ai_ready).
    def __init__(
        self,
        humans,
        bots,
        *,
        quick=False,
        now=None,
        rng=None,
        preparing=False,
        skin_map: dict[str, str] | None = None,
    ):
        names = list(humans) + list(bots)
        if not 4 <= len(names) <= 10 or len(set(names)) != len(names):
            raise ValueError("Permainan membutuhkan 4–10 identitas berbeda.")
        self.rng = rng or random.SystemRandom()
        hitman, spy, stalker = KOMPOSISI_PERAN[len(names)]
        roles = ["hitman"] * hitman + ["spy"] * spy + ["stalker"] * stalker
        roles += ["civilian"] * (len(names) - len(roles))
        self.rng.shuffle(roles)
        self.players = {}
        for name, role in zip(names, roles):
            if name in bots:
                skin = SKIN_BY_BOT.get(name, self.rng.choice(ALL_SKINS))
            else:
                skin = skin_map.get(name, "dexter") if skin_map else "dexter"
            self.players[name] = Participant(name, role, name in bots, skin_id=skin)
        self.id = uuid4().hex
        self.round = 1
        self.ai_controlled = (
            False  # Diaktifkan RoomService; unit engine tetap dapat diuji tanpa jaringan.
        )
        self.npc_decisions = set()
        self.ai_grace_phase = None
        self.phase = "day"
        self.durations = phase_durations(len(names), quick)
        now = time.time() if now is None else now
        self.deadline = now + self.durations["day"]
        self.actions = {}
        self.votes = {}
        # Gag Order milik Syndicate: satu Gag per siang untuk seluruh tim, cooldown satu ronde penuh.
        self.next_gag = 1
        self.skip_consents = set()
        self.ready_consents = set()
        self.preparation = None
        self.events = ["Permainan dimulai. Diskusikan alibi tanpa membocorkan identitasmu."]
        if preparing:
            # Fase persiapan tidak menjalankan timer ronde; deadline = batas tunggu maksimal AI.
            self.phase = "preparing"
            self.deadline = now + PREPARATION_MAX_SECONDS
            self.preparation = {
                "ready": not bots,
                "detail": "Tidak ada bot di ruangan." if not bots else "Menyiapkan AI bot…",
                "progress": 1.0 if not bots else 0.0,
                "min_until": now + PREPARATION_MIN_SECONDS,
                "ready_at": now if not bots else None,
            }
            self.events = ["Menyiapkan pertandingan. Baca panduan singkat sambil menunggu AI siap."]
        self.messages = []
        self.winner = None
        self.winner_reason = None
        self.bot_day_done = False
        self.bot_night_done = False
        self.bot_vote_done = False

    # PERSIAPAN: progres pemuatan AI ditampilkan di layar persiapan semua pemain.
    def update_preparation(self, *, detail=None, progress=None):
        if self.phase != "preparing":
            return
        if detail is not None:
            self.preparation["detail"] = detail
        if progress is not None:
            self.preparation["progress"] = max(0.0, min(1.0, float(progress)))

    # PERSIAPAN: AI siap; ronde 1 dimulai setelah waktu baca minimal atau semua manusia menekan Siap.
    def mark_ai_ready(self, now=None, detail="AI siap."):
        if self.phase != "preparing":
            return
        now = time.time() if now is None else now
        self.preparation.update(ready=True, detail=detail, progress=1.0, ready_at=now)
        self.try_begin(now)

    # PERSIAPAN: persetujuan "Siap" hanya dari manusia; tidak berarti AI boleh dilewati.
    def ready_consent(self, name, now=None):
        player = self.players.get(name)
        if self.phase != "preparing" or not player or player.bot:
            raise ValueError("Tombol siap hanya tersedia untuk pemain manusia saat persiapan.")
        self.ready_consents.add(name)
        self.try_begin(time.time() if now is None else now)

    # Mulai jika AI siap dan (waktu baca minimal lewat atau semua manusia sudah siap).
    def try_begin(self, now=None):
        if self.phase != "preparing" or not self.preparation["ready"]:
            return False
        now = time.time() if now is None else now
        humans = {p.name for p in self.players.values() if not p.bot}
        if now >= self.preparation["min_until"] or (humans and humans <= self.ready_consents):
            self.begin(now)
            return True
        return False

    # Ronde 1 benar-benar dimulai: timer siang baru berjalan dari titik ini.
    def begin(self, now=None, event=None):
        if self.phase != "preparing":
            return
        now = time.time() if now is None else now
        self.phase = "day"
        self.deadline = now + self.durations["day"]
        self.ready_consents.clear()
        self.events.append(
            event or "Permainan dimulai. Diskusikan alibi tanpa membocorkan identitasmu."
        )

    def reserve_ai_reply(self, now=None):
        """At most one bounded extension per phase; manual skip still takes precedence."""
        now = time.time() if now is None else now
        phase = (self.round, self.phase)
        if self.phase in {"day", "tribunal"} and self.ai_grace_phase != phase:
            self.ai_grace_phase = phase
            self.deadline = max(self.deadline, now + 35)

    # GETTER: ambil skin_id pemain, aman dipanggil dari luar Match.
    def get_skin(self, name: str) -> str:
        player = self.players.get(name)
        return player.skin_id if player else "dexter"

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

    # Rekan Syndicate: Hitman lain dalam pertandingan (hidup atau sudah dieksekusi).
    def allies(self, name):
        if self.players[name].role != "hitman":
            return []
        return [p.name for p in self.players.values() if p.role == "hitman" and p.name != name]

    # AKSI PRIVAT: pilihan malam disimpan, belum diresolusikan sebelum deadline.
    def act(self, name, ability, target_name):
        player = self.actor(name)
        if ability == "gag":
            if self.phase != "day" or player.role != "hitman" or self.round < self.next_gag:
                raise ValueError("Gag Order belum tersedia.")
            target = self.target(player, target_name)
            if target.role == "hitman":
                raise ValueError("Tidak bisa menarget rekan Syndicate.")
            target.gagged = True
            self.next_gag = self.round + 2
            return
        expected = NIGHT_ABILITY.get(player.role)
        if expected is None or self.phase != "night" or ability != expected or name in self.actions:
            raise ValueError("Aksi malam tidak tersedia atau sudah dikunci.")
        target = self.target(player, target_name, allow_self=ability == "guard")
        if ability == "hostage" and target.role == "hitman":
            raise ValueError("Tidak bisa menarget rekan Syndicate.")
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

    # Satu korban per malam untuk Syndicate: pilihan terbanyak, seri → yang dipilih paling awal.
    def syndicate_target(self):
        choices = [
            action["target"] for action in self.actions.values() if action["ability"] == "hostage"
        ]
        if not choices:
            return None
        counts = Counter(choices)
        return next(target for target in choices if counts[target] == max(counts.values()))

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
        target = self.syndicate_target()
        if target is not None and target not in guards:
            self.players[target].hostage = True
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
            remaining = self.hitman_remaining()
            count = "" if remaining is None else f" Hitman tersisa: {remaining}."
            # Eksekusi Hitman terakhir langsung mengakhiri permainan dan membuka semua role.
            terakhir = not any(p.alive for p in self.players.values() if p.role == "hitman")
            rahasia = "" if terakhir else " Role tetap dirahasiakan sampai permainan selesai."
            self.events.append(f"Tribunal mengeksekusi {leaders[0]}.{count}{rahasia}")
        else:
            self.events.append("Tribunal berakhir tanpa eksekusi: suara seri atau tidak ada suara.")
        self.check_winner()

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
        }[winner]
        self.events.append(f"{label} {explanation}")

    # Warga menang jika semua Hitman dieksekusi; Syndicate menang ketika warga bebas tidak lagi
    # lebih banyak dari Hitman yang hidup (suara warga tidak bisa lagi mengalahkan suara Hitman).
    def check_winner(self):
        if self.winner:
            return
        hitmen = [p for p in self.players.values() if p.role == "hitman"]
        alive_hitmen = sum(p.alive for p in hitmen)
        survivors = [p for p in self.players.values() if p.role != "hitman" and p.alive]
        if not alive_hitmen:
            executed = "Semua Hitman" if len(hitmen) > 1 else "Hitman"
            self.finish("civilians", "hitman_executed", f"{executed} dieksekusi oleh Tribunal.")
        elif not survivors:
            self.finish("hitman", "no_civilians_alive", "Tidak ada warga yang masih hidup.")
        elif all(p.hostage for p in survivors):
            self.finish(
                "hitman", "all_survivors_hostage", "Semua warga yang masih hidup telah disandera."
            )
        elif sum(not p.hostage for p in survivors) <= alive_hitmen:
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
            "outcome": "won" if team == self.winner else "lost",
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
            if player.role == "hitman":
                # Syndicate: rekan tidak pernah ditarget, dan Hostage mengikuti target rekan bila ada.
                allies = set(self.allies(player.name))
                targets = [name for name in targets if name not in allies]
                leader = self.syndicate_target() if self.phase == "night" else None
                if leader in targets:
                    targets = [leader] + [name for name in targets if name != leader]
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
                        ability = "gag" if self.phase == "day" else NIGHT_ABILITY.get(player.role)
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
        if self.phase == "preparing":
            # Batas tunggu habis: mulai dengan cadangan bawaan daripada menahan pemain selamanya.
            if now >= self.deadline:
                self.begin(now, "AI belum siap penuh; permainan dimulai dengan bot cadangan.")
            else:
                self.try_begin(now)
            return
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

    # Data layar persiapan: progres AI, hitung mundur mulai, dan jumlah manusia yang sudah siap.
    def preparation_view(self, viewer):
        now = time.time()
        prep = self.preparation
        starts_at = max(prep["min_until"], prep["ready_at"]) if prep["ready"] else None
        return {
            "ready": prep["ready"],
            "detail": prep["detail"],
            "progress": round(prep["progress"], 2),
            "starts_in": max(0, ceil(starts_at - now)) if starts_at else None,
            "max_wait": max(0, ceil(self.deadline - now)),
            "agreed": len(self.ready_consents),
            "required": sum(not p.bot for p in self.players.values()),
            "consented": viewer in self.ready_consents,
            "bots": sum(p.bot for p in self.players.values()),
        }

    # Jumlah tiap role sejak awal pertandingan; publik untuk semua pemain (siapa pemegangnya tetap rahasia).
    def composition(self):
        counts = Counter(p.role for p in self.players.values())
        return {role: counts[role] for role in ("hitman", "spy", "stalker", "civilian")}

    # Room dengan ≥ 2 Hitman mengumumkan Hitman yang masih hidup (hanya berubah saat eksekusi Tribunal).
    # Room 1 Hitman: None, karena warga sudah tahu dari game yang selesai atau berlanjut.
    def hitman_remaining(self):
        hitmen = [p for p in self.players.values() if p.role == "hitman"]
        return sum(p.alive for p in hitmen) if len(hitmen) >= 2 else None

    # SNAPSHOT PRIVAT: roster hanya mengandung alive; status diam orang lain tidak pernah dikirim.
    def snapshot(self, viewer):
        player = self.players[viewer]
        hitman = player.role == "hitman"
        ability = None
        if self.phase == "day" and hitman:
            ability = "gag"
        elif self.phase == "night":
            ability = NIGHT_ABILITY.get(player.role)
        can_act = bool(ability and player.alive and not self.winner)
        if ability == "gag":
            can_act &= self.round >= self.next_gag
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
            "deadline": self.deadline,
            "server_time": time.time(),
            "winner": self.winner,
            "events": list(self.events),
            "result": self.result(viewer),
            "preparation": self.preparation_view(viewer) if self.phase == "preparing" else None,
            "composition": self.composition(),
            "hitman_remaining": self.hitman_remaining(),
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
                # Cooldown Gag bersama hanya untuk Syndicate; warga tidak boleh tahu kapan Gag dipakai.
                "next_gag": self.next_gag if hitman else 1,
                "next_peek": player.next_peek,
                "allies": self.allies(viewer),
                # Pilihan Hostage rekan malam ini agar Syndicate bisa sepakat satu target.
                "ally_actions": (
                    [
                        {"name": name, "target": action["target"]}
                        for name, action in self.actions.items()
                        if name != viewer and action["ability"] == "hostage"
                    ]
                    if hitman and self.phase == "night"
                    else []
                ),
                "last_guard": (
                    player.last_guard if player.last_guard_round == self.round - 1 else None
                ),
                "intel": list(player.intel),
            },
        }

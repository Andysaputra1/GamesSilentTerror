"""Engine aturan murni: tidak bergantung HTTP, Socket.IO, MySQL, atau LLM.

RoomService memegang lock ketika memanggil engine. Snapshot selalu dibuat
untuk satu pemain: role, Hostage, Gag, dan hasil Peek tidak masuk data publik.
"""

from math import ceil
from collections import Counter
import copy
from dataclasses import dataclass, field
import random
import time
from uuid import uuid4

from app.module.skin_constants import ALL_SKINS, SKIN_BY_BOT


@dataclass
class Participant:
    name: str
    role: str
    bot: bool = False
    alive: bool = True
    # Keluar di tengah pertandingan: tidak hidup seperti korban eksekusi, tetapi ditandai berbeda.
    left: bool = False
    hostage: bool = False
    gagged: bool = False
    next_peek: int = 1
    last_guard: str | None = None
    last_guard_round: int = 0
    intel: list[dict] = field(default_factory=list)
    skin_id: str = "dexter"


# Layar persiapan: minimal cukup untuk membaca panduan, maksimal agar model yang gagal dimuat tidak menahan room.
PREPARATION_MIN_SECONDS = 40
PREPARATION_MAX_SECONDS = 90
# AI yang terlambat siap tetap memberi countdown untuk membuka role, dibatasi maksimum tunggu.
PREPARATION_COUNTDOWN_SECONDS = 10

# Komposisi role per jumlah peserta: (hitman, spy, stalker); sisanya civilian.
# Dipilih lewat simulasi keseimbangan semua kursi bot metode campuran, dengan pengumuman jumlah Hitman tersisa
# (hitman_remaining); data dan alasannya ada di GAME_CONCEPT.md, bagian Ruangan dan role.
KOMPOSISI_PERAN = {
    4: (1, 1, 1),
    5: (1, 1, 1),
    6: (1, 1, 1),
    7: (2, 2, 1),
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
    # Tribunal +30 dtk: waktu tambahan untuk menimbang dan mengunci vote setelah diskusi siang.
    return {"day": count * 20, "night": count * 5, "tribunal": ceil(count * 7.5) + 30}


# Nama yang tampil di game = nama tampilan akun; username tetap ID engine. Nama yang bentrok (sesama
# pemain, beda huruf besar/kecil saja, atau sama dengan nama bot) diberi penanda "(username)".
def label_unik(nama_tampilan, bots=()):
    nama = {u: (d or "").strip() or u for u, d in nama_tampilan.items()}
    jumlah = Counter(d.casefold() for d in nama.values())
    nama_bot = {b.casefold() for b in bots}
    labels = {
        u: d if jumlah[d.casefold()] == 1 and d.casefold() not in nama_bot else f"{d} ({u})"
        for u, d in nama.items()
    }
    return labels | {b: b for b in bots}


# Salinan snapshot untuk otak bot: semua username diganti label, sehingga bot membaca dan menyebut nama yang
# sama dengan yang dilihat dan diketik pemain manusia. Target keputusan bot diterjemahkan balik lewat
# Match.username().
def snapshot_berlabel(snapshot, labels):
    def nama(n):
        return labels.get(n, n) if n else n

    s = copy.deepcopy(snapshot)
    for p in s["players"]:
        p["name"] = nama(p["name"])
    for m in s["messages"]:
        m["sender"] = nama(m["sender"])
    for v in s["tribunal_votes"]:
        v["target"], v["voters"] = nama(v["target"]), [nama(x) for x in v["voters"]]
    me = s["me"]
    me["name"], me["vote"], me["last_guard"] = (
        nama(me["name"]),
        nama(me["vote"]),
        nama(me["last_guard"]),
    )
    me["allies"] = [nama(x) for x in me["allies"]]
    me["ally_actions"] = [
        {**a, "name": nama(a["name"]), "target": nama(a["target"])} for a in me["ally_actions"]
    ]
    if me.get("action"):
        me["action"] = {**me["action"], "target": nama(me["action"]["target"])}
    me["intel"] = [{**x, "name": nama(x["name"])} for x in me["intel"]]
    me["syndicate_hostages"] = [{**x, "name": nama(x["name"])} for x in me["syndicate_hostages"]]
    return s


# Avatar pertandingan: manusia (urutan masuk ruangan) memakai skin pilihannya, bot memakai skin tetapnya.
# Skin yang sudah dipakai pemain sebelumnya diganti skin yang masih kosong; setelah keenam skin
# terpakai (lebih dari 6 peserta), skin boleh kembar.
def assign_skins(humans, bots, skin_map=None):
    taken = set()
    skins = {}
    for name in list(humans) + list(bots):
        if name in bots:
            wanted = SKIN_BY_BOT.get(name, ALL_SKINS[0])
        else:
            wanted = (skin_map or {}).get(name, "dexter")
        free = [skin for skin in ALL_SKINS if skin not in taken]
        skins[name] = free[0] if wanted in taken and free else wanted
        taken.add(skins[name])
    return skins


class Match:
    # Role mengikuti KOMPOSISI_PERAN; skin_map berisi avatar pilihan tiap manusia (lihat assign_skins).
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
        labels: dict[str, str] | None = None,
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
        skins = assign_skins(humans, bots, skin_map)
        for name, role in zip(names, roles):
            self.players[name] = Participant(name, role, name in bots, skin_id=skins[name])
        self.labels = {name: (labels or {}).get(name, name) for name in names}
        # Metode otak tiap bot (fuzzy/utility/bt/llm); diisi NPCService saat persiapan, tampil di samping nama.
        self.bot_methods: dict[str, str] = {}
        self.id = uuid4().hex
        self.round = 1
        self.ai_controlled = (
            False  # Diaktifkan RoomService; unit engine tetap dapat diuji tanpa jaringan.
        )
        self.npc_decisions = set()
        # Bot yang sedang menyusun chat (lantai bicara NPCService); tampil sebagai awan "berpikir".
        self.bot_berpikir: set[str] = set()
        # Tahap langkah terakhir tiap bot (NPCService): I input diterima, L logika berjalan, O output selesai.
        self.bot_tahap: dict[str, str] = {}
        self.phase = "day"
        self.durations = phase_durations(len(names), quick)
        now = time.time() if now is None else now
        self.deadline = now + self.durations["day"]
        self.actions = {}
        self.votes = {}
        # Gag Order milik Syndicate: satu Gag per siang untuk seluruh tim, cooldown satu ronde penuh.
        self.next_gag = 1
        # Hasil Hostage Syndicate per malam (berhasil = target tidak dijaga Guard); hanya dikirim ke Hitman.
        self.syndicate_log = []
        self.skip_consents = set()
        self.ready_consents = set()
        self.revealed = set()
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
                "started_at": now,
                "min_until": now + PREPARATION_MIN_SECONDS,
                "ready_at": now if not bots else None,
            }
            self.events = ["Menyiapkan pertandingan. Baca panduan singkat sambil menunggu AI siap."]
        self.messages = []
        self.jumlah_pesan = 0
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

    # PERSIAPAN: AI siap; ronde 1 tetap menunggu waktu baca minimal.
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

    # PERSIAPAN: catat kartu yang dibuka; pembukaan tidak mempercepat countdown.
    def reveal_role(self, name, now=None):
        player = self.players.get(name)
        if self.phase != "preparing" or not player or player.bot:
            raise ValueError("Kartu role dibuka hanya oleh pemain manusia saat persiapan.")
        self.revealed.add(name)
        self.try_begin(time.time() if now is None else now)

    # Manusia yang belum membuka kartu role (pemain yang sudah keluar tidak ditunggu).
    def unrevealed(self):
        return [
            p.name
            for p in self.players.values()
            if not p.bot and p.alive and p.name not in self.revealed
        ]

    # Jadwal bersama: minimal 40 detik, countdown AI siap, dan batas maksimum tunggu.
    def _start_at(self):
        prep = self.preparation
        if not prep["ready"]:
            return None
        return min(
            self.deadline,
            max(prep["min_until"], prep["ready_at"] + PREPARATION_COUNTDOWN_SECONDS),
        )

    # Mulai sesuai countdown; UI membuka kartu otomatis lima detik sebelum mulai.
    # Tombol Siap maupun pembukaan kartu terakhir tidak melewati waktu baca minimum.
    def try_begin(self, now=None):
        start_at = self._start_at() if self.phase == "preparing" else None
        if start_at is None:
            return False
        now = time.time() if now is None else now
        if now >= start_at:
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
        self.revealed.clear()
        self.events.append(
            event or "Permainan dimulai. Diskusikan alibi tanpa membocorkan identitasmu."
        )

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
        # Hostage kehilangan semua aksi: chat, vote, dan skill malam.
        if player.hostage:
            raise ValueError("Pemain yang disandera tidak dapat melakukan aksi.")
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

    # VOTE: satu pilihan per pemain; hanya Hostage/kematian yang mencabut suara, bukan Gag Order.
    def vote(self, name, target_name):
        player = self.actor(name)
        if self.phase != "tribunal" or player.hostage or name in self.votes:
            raise ValueError("Voting tidak tersedia atau pilihan sudah dikunci.")
        self.target(player, target_name)
        self.votes[name] = target_name

    # BATAL VOTE: selama Tribunal suara boleh ditarik lalu dipilih ulang; yang dihitung suara saat waktu habis.
    def cancel_vote(self, name):
        player = self.actor(name)
        if self.phase != "tribunal" or player.hostage or name not in self.votes:
            raise ValueError("Tidak ada suara yang bisa dibatalkan.")
        del self.votes[name]

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
        if target is not None:
            self.syndicate_log.append(
                {"round": self.round, "name": target, "success": target not in guards}
            )
            if target not in guards:
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
            self.events.append(
                f"Tribunal mengeksekusi {self.labels[leaders[0]]}.{self._catatan_tersingkir()}"
            )
        else:
            self.events.append("Tribunal berakhir tanpa eksekusi: suara seri atau tidak ada suara.")
        self.check_winner()

    # Akhiran pengumuman eksekusi/keluar: Hitman tersisa (room ≥ 2 Hitman) dan kerahasiaan role.
    def _catatan_tersingkir(self):
        remaining = self.hitman_remaining()
        count = "" if remaining is None else f" Hitman tersisa: {remaining}."
        # Hitman terakhir yang tersingkir langsung mengakhiri permainan dan membuka semua role.
        terakhir = not any(p.alive for p in self.players.values() if p.role == "hitman")
        rahasia = "" if terakhir else " Role tetap dirahasiakan sampai permainan selesai."
        return count + rahasia

    # KELUAR DI TENGAH PERTANDINGAN: sama dengan dieksekusi (tidak hidup, tanpa chat/vote/aksi,
    # hasil tetap mengikuti kubu), tetapi ditandai `left` agar roster dan catatan membedakannya.
    # Role tetap rahasia seperti eksekusi. Pemain yang sudah mati atau match selesai tidak berubah.
    def leave(self, name, now=None):
        player = self.players.get(name)
        if not player or player.bot:
            raise ValueError("Hanya pemain manusia di pertandingan ini yang dapat keluar.")
        if not player.alive or self.winner:
            return False
        player.alive, player.left = False, True
        # Suara dan aksi milik pemain ini dibuang. Pilihan orang lain yang menargetkannya juga
        # dibuang karena target harus hidup (sama seperti korban eksekusi); mereka boleh memilih ulang.
        self.votes = {v: t for v, t in self.votes.items() if name not in (v, t)}
        self.actions = {a: x for a, x in self.actions.items() if name not in (a, x["target"])}
        self.skip_consents.discard(name)
        self.ready_consents.discard(name)
        self.events.append(
            f"{self.labels[name]} meninggalkan permainan.{self._catatan_tersingkir()}"
        )
        self.check_winner()
        # Fase tidak menunggu pemain yang keluar: persiapan dan skip diskusi dicek ulang.
        now = time.time() if now is None else now
        if self.phase == "preparing":
            self.try_begin(now)
        elif self.phase == "day":
            self._skip_jika_lengkap(now)
        return True

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
            # Hitman yang keluar tersingkir seperti dieksekusi; alasan hasil tetap hitman_executed.
            cara = "dieksekusi oleh Tribunal"
            if any(p.left for p in hitmen):
                cara = "keluar dari permainan" if all(p.left for p in hitmen) else "tersingkir"
            self.finish("civilians", "hitman_executed", f"{executed} {cara}.")
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
            if not player.bot or not player.alive or player.hostage:
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
        self._skip_jika_lengkap(now)

    # Siang berakhir bila semua manusia hidup sudah setuju (dicek ulang saat ada pemain keluar).
    def _skip_jika_lengkap(self, now=None):
        required = {p.name for p in self.players.values() if not p.bot and p.alive}
        if self.phase == "day" and required and required <= self.skip_consents:
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
                cadangan = "AI belum siap penuh; permainan dimulai dengan bot cadangan."
                self.begin(now, None if self.preparation["ready"] else cadangan)
            else:
                self.try_begin(now)
            return
        # Scheduler LLM mendapat waktu memilih; fallback aturan hanya mengisi pilihan yang kosong di deadline.
        if self.phase != "finished" and now >= self.deadline:
            self.run_bots()
        if self.phase == "finished" or now < self.deadline:
            return
        # URUTAN: ronde 1 siang → malam (belum ada bahan untuk vote); ronde berikutnya siang → Tribunal → malam.
        if self.phase == "day" and self.round > 1:
            self.phase = "tribunal"
            self.votes = {}
            self.events.append("Diskusi selesai. Tribunal dimulai: pilih tersangka.")
        elif self.phase in {"day", "tribunal"}:
            if self.phase == "tribunal":
                self.resolve_votes()
            if not self.winner:
                self.phase = "night"
                self.actions = {}
                self.events.append("Malam tiba. Chat dikunci; lakukan aksi secara rahasia.")
        else:
            self.resolve_night()
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
        # ID diawali nomor urut: otak bot mengurutkan chat dengan waktu terima lalu ID, jadi chat yang
        # terbaca dalam satu langkah tetap kronologis (UUID murni membuat urutannya acak).
        self.jumlah_pesan += 1
        record = {
            "id": f"{self.jumlah_pesan:06d}{uuid4().hex[:10]}",
            "sender": sender,
            "message": message,
        }
        self.messages.append(record)
        self.messages = self.messages[-100:]
        return record

    # Data layar persiapan: progres AI, hitung mundur mulai, jumlah manusia yang sudah siap dan sudah membuka kartu.
    def preparation_view(self, viewer):
        now = time.time()
        prep = self.preparation
        unrevealed = self.unrevealed()
        starts_at = self._start_at()
        return {
            "ready": prep["ready"],
            "detail": prep["detail"],
            "progress": round(prep["progress"], 2),
            "starts_in": max(0, ceil(starts_at - now)) if starts_at else None,
            "max_wait": max(0, ceil(self.deadline - now)),
            "agreed": len(self.ready_consents),
            "required": sum(not p.bot and p.alive for p in self.players.values()),
            "consented": viewer in self.ready_consents,
            "bots": sum(p.bot for p in self.players.values()),
            "elapsed": max(0, int(now - prep["started_at"])),
            "revealed": viewer in self.revealed,
            "unrevealed": len(unrevealed),
        }

    # Username dari label (target keputusan bot); nama yang bukan label dikembalikan apa adanya.
    def username(self, label):
        return next((u for u, nama in self.labels.items() if nama == label), label)

    # Jumlah tiap role sejak awal pertandingan; publik untuk semua pemain (siapa pemegangnya tetap rahasia).
    def composition(self):
        counts = Counter(p.role for p in self.players.values())
        return {role: counts[role] for role in ("hitman", "spy", "stalker", "civilian")}

    # Room dengan ≥ 2 Hitman mengumumkan Hitman yang masih hidup (berubah saat eksekusi/keluar).
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
        can_act = bool(ability and player.alive and not player.hostage and not self.winner)
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
                    "label": self.labels[p.name],
                    "alive": p.alive,
                    "skin_id": p.skin_id,
                    # Keluar sudah diumumkan di catatan, jadi tandanya publik (hanya bila benar).
                    **({"left": True} if p.left else {}),
                    **({"metode": self.bot_methods[p.name]} if p.name in self.bot_methods else {}),
                    **({"thinking": True} if p.name in self.bot_berpikir else {}),
                    **({"tahap": self.bot_tahap[p.name]} if p.name in self.bot_tahap else {}),
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
                "can_cancel_vote": self.phase == "tribunal"
                and player.alive
                and not player.hostage
                and viewer in self.votes,
                "vote": self.votes.get(viewer),
                "ability": ability,
                "can_act": bool(can_act),
                "action": self.actions.get(viewer) if self.phase == "night" else None,
                # Cooldown Gag bersama hanya untuk Syndicate; warga tidak boleh tahu kapan Gag dipakai.
                "next_gag": self.next_gag if hitman else 1,
                "next_peek": player.next_peek,
                "allies": self.allies(viewer),
                # Korban Hostage tim malam ini (pilihan terbanyak, seri → yang paling awal), hanya untuk Syndicate.
                "syndicate_target": (
                    self.syndicate_target() if hitman and self.phase == "night" else None
                ),
                # Hasil Hostage tim tiap malam (gagal = dijaga Guard), hanya untuk Syndicate.
                "syndicate_hostages": list(self.syndicate_log) if hitman else [],
                # Target Gag ronde ini (Gag dipakai bersama Syndicate); warga hanya tahu status dirinya sendiri.
                "ally_gags": [p.name for p in self.players.values() if p.gagged] if hitman else [],
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

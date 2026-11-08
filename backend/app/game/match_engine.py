"""Engine aturan murni: tidak bergantung HTTP, Socket.IO, MySQL, atau LLM.

RoomService memegang lock ketika memanggil engine. Snapshot selalu dibuat
untuk satu pemain: role, Gag, dan hasil Peek tidak masuk data publik. Hostage yang berhasil
diumumkan ke semua pemain dan tetap tampil di roster sampai permainan selesai.
"""

from math import ceil
from collections import Counter
import copy
from dataclasses import dataclass, field
import random
import time
from uuid import uuid4

from app.config.skins import ALL_SKINS, SKIN_BY_BOT


@dataclass
class Participant:
    name: str
    role: str
    bot: bool = False
    alive: bool = True
    # Keluar di tengah pertandingan: tidak hidup seperti korban eksekusi, tetapi ditandai berbeda.
    left: bool = False
    hostage: bool = False
    # Malam saat pemain disandera (publik bersama tanda hostage); 0 = belum pernah disandera.
    hostage_round: int = 0
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

# Seri di Tribunal menambah waktu sekali per Tribunal (detik); durasi normal tetap di phase_durations.
TRIBUNAL_EXTRA_SECONDS = 30
TRIBUNAL_EXTRA_QUICK_SECONDS = 10
# Pesan chat tim yang disimpan per kanal.
TEAM_CHAT_LIMIT = 100

# Komposisi role per jumlah peserta: (hitman, spy, stalker); sisanya civilian.
# Diukur ulang dengan Fuzzy saja (7 Nov 2026, 200 game per ukuran, semua kursi bot, dengan pengumuman
# hitman_remaining). Warga menang 4–10 pemain: 47,0 / 47,0 / 46,0 / 60,5 / 52,5 / 56,0 / 59,5%; 7 pemain diukur
# ulang 1000 game: 55,1 ± 3,1%, jadi semua di target 40–60%. Data dan alasannya ada di GAME_CONCEPT.md, bagian
# Ruangan dan role.
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
    nama_bersih = {
        username: (nama or "").strip() or username for username, nama in nama_tampilan.items()
    }
    jumlah_nama = Counter(nama.casefold() for nama in nama_bersih.values())
    nama_bot = {bot.casefold() for bot in bots}
    labels = {
        username: (
            nama
            if jumlah_nama[nama.casefold()] == 1 and nama.casefold() not in nama_bot
            else f"{nama} ({username})"
        )
        for username, nama in nama_bersih.items()
    }
    return labels | {bot: bot for bot in bots}


# Salinan snapshot untuk otak bot: semua username diganti label, sehingga bot membaca dan menyebut nama yang
# sama dengan yang dilihat dan diketik pemain manusia. Target keputusan bot diterjemahkan balik lewat
# Match.username().
def snapshot_berlabel(snapshot, labels):
    def ke_label(nama):
        return labels.get(nama, nama) if nama else nama

    salinan = copy.deepcopy(snapshot)
    for pemain in salinan["players"]:
        pemain["name"] = ke_label(pemain["name"])
    for pesan in salinan["messages"]:
        pesan["sender"] = ke_label(pesan["sender"])
    for suara in salinan["tribunal_votes"]:
        suara["target"] = ke_label(suara["target"])
        suara["voters"] = [ke_label(nama) for nama in suara["voters"]]
    saya = salinan["me"]
    saya["name"] = ke_label(saya["name"])
    saya["vote"] = ke_label(saya["vote"])
    saya["last_guard"] = ke_label(saya["last_guard"])
    saya["allies"] = [ke_label(nama) for nama in saya["allies"]]
    saya["ally_actions"] = [
        {**aksi, "name": ke_label(aksi["name"]), "target": ke_label(aksi["target"])}
        for aksi in saya["ally_actions"]
    ]
    saya["spy_allies"] = [ke_label(nama) for nama in saya["spy_allies"]]
    saya["spy_actions"] = [
        {**aksi, "name": ke_label(aksi["name"]), "target": ke_label(aksi["target"])}
        for aksi in saya["spy_actions"]
    ]
    if saya.get("action"):
        saya["action"] = {**saya["action"], "target": ke_label(saya["action"]["target"])}
    saya["intel"] = [{**data, "name": ke_label(data["name"])} for data in saya["intel"]]
    saya["syndicate_hostages"] = [
        {**data, "name": ke_label(data["name"])} for data in saya["syndicate_hostages"]
    ]
    saya["ally_gags"] = [ke_label(nama) for nama in saya["ally_gags"]]
    saya["team_messages"] = [
        {**pesan, "sender": ke_label(pesan["sender"])} for pesan in saya["team_messages"]
    ]
    saya["team_humans"] = [ke_label(nama) for nama in saya["team_humans"]]
    return salinan


# Avatar pertandingan: manusia (urutan masuk ruangan) memakai skin pilihannya, bot memakai skin tetapnya.
# Skin yang sudah dipakai pemain sebelumnya diganti skin yang masih kosong; setelah keenam skin
# terpakai (lebih dari 6 peserta), skin boleh kembar.
def assign_skins(humans, bots, skin_map=None):
    skin_terpakai = set()
    skin_peserta = {}
    for nama in list(humans) + list(bots):
        if nama in bots:
            skin_diminta = SKIN_BY_BOT.get(nama, ALL_SKINS[0])
        else:
            skin_diminta = (skin_map or {}).get(nama, "dexter")
        skin_kosong = [skin for skin in ALL_SKINS if skin not in skin_terpakai]
        skin_peserta[nama] = (
            skin_kosong[0] if skin_diminta in skin_terpakai and skin_kosong else skin_diminta
        )
        skin_terpakai.add(skin_peserta[nama])
    return skin_peserta


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
        semua_nama = list(humans) + list(bots)
        if not 4 <= len(semua_nama) <= 10 or len(set(semua_nama)) != len(semua_nama):
            raise ValueError("Permainan membutuhkan 4–10 identitas berbeda.")
        self.rng = rng or random.SystemRandom()
        jumlah_hitman, jumlah_spy, jumlah_stalker = KOMPOSISI_PERAN[len(semua_nama)]
        daftar_role = (
            ["hitman"] * jumlah_hitman + ["spy"] * jumlah_spy + ["stalker"] * jumlah_stalker
        )
        daftar_role += ["civilian"] * (len(semua_nama) - len(daftar_role))
        self.rng.shuffle(daftar_role)
        self.players = {}
        skin_peserta = assign_skins(humans, bots, skin_map)
        for nama, role in zip(semua_nama, daftar_role):
            self.players[nama] = Participant(nama, role, nama in bots, skin_id=skin_peserta[nama])
        self.labels = {nama: (labels or {}).get(nama, nama) for nama in semua_nama}
        self.id = uuid4().hex
        self.round = 1
        # Diaktifkan RoomService; unit engine tetap dapat diuji tanpa jaringan.
        self.ai_controlled = False
        self.npc_decisions = set()
        # Bot yang sedang menyusun chat (lantai bicara NPCService); tampil sebagai awan "berpikir".
        self.bot_berpikir: set[str] = set()
        # Tahap langkah terakhir tiap bot (NPCService): I input diterima, L logika berjalan, O output selesai.
        self.bot_tahap: dict[str, str] = {}
        self.phase = "day"
        self.durations = phase_durations(len(semua_nama), quick)
        self.tribunal_extra_seconds = (
            TRIBUNAL_EXTRA_QUICK_SECONDS if quick else TRIBUNAL_EXTRA_SECONDS
        )
        now = time.time() if now is None else now
        self.deadline = now + self.durations["day"]
        self.actions = {}
        self.votes = {}
        # Waktu tambahan seri sudah dipakai pada Tribunal ini (publik); direset tiap Tribunal.
        self.tribunal_extra = False
        # Chat tim malam per kanal: rahasia, hanya di memori ini (bukan messages, events, atau database).
        self.team_messages = {"hitman": [], "spy": []}
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
        pemain = self.players.get(name)
        if self.phase != "preparing" or not pemain or pemain.bot:
            raise ValueError("Tombol siap hanya tersedia untuk pemain manusia saat persiapan.")
        self.ready_consents.add(name)
        self.try_begin(time.time() if now is None else now)

    # PERSIAPAN: catat kartu yang dibuka; pembukaan tidak mempercepat countdown.
    def reveal_role(self, name, now=None):
        pemain = self.players.get(name)
        if self.phase != "preparing" or not pemain or pemain.bot:
            raise ValueError("Kartu role dibuka hanya oleh pemain manusia saat persiapan.")
        self.revealed.add(name)
        self.try_begin(time.time() if now is None else now)

    # Jadwal bersama: minimal waktu baca, countdown setelah AI siap, dan batas maksimum tunggu.
    def _hitung_waktu_mulai(self):
        persiapan = self.preparation
        if not persiapan["ready"]:
            return None
        return min(
            self.deadline,
            max(persiapan["min_until"], persiapan["ready_at"] + PREPARATION_COUNTDOWN_SECONDS),
        )

    # Mulai sesuai countdown; UI membuka kartu otomatis lima detik sebelum mulai.
    # Tombol Siap maupun pembukaan kartu terakhir tidak melewati waktu baca minimum.
    def try_begin(self, now=None):
        waktu_mulai = self._hitung_waktu_mulai() if self.phase == "preparing" else None
        if waktu_mulai is None:
            return False
        now = time.time() if now is None else now
        if now >= waktu_mulai:
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

    # HELPER: pemain yang masih bisa bertindak (hidup, pertandingan belum selesai); Hostage dicek per aksi.
    def actor(self, name):
        pemain = self.players.get(name)
        if not pemain or not pemain.alive or self.phase == "finished":
            raise ValueError("Kamu tidak dapat melakukan aksi ini.")
        return pemain

    # VALIDASI CHAT: Gag/Hostage/kematian dan fase malam ditegakkan di backend.
    def can_chat(self, name):
        pemain = self.players.get(name)
        return bool(
            pemain
            and pemain.alive
            and not pemain.hostage
            and not pemain.gagged
            and self.phase in {"day", "tribunal"}
        )

    # VALIDASI TARGET: tidak boleh memilih pemain mati atau identitas di luar pertandingan.
    def target(self, actor, name, *, allow_self=False):
        pemain_target = self.players.get(name)
        if not pemain_target or not pemain_target.alive or (name == actor.name and not allow_self):
            raise ValueError("Target tidak valid.")
        return pemain_target

    # Rekan Syndicate: Hitman lain dalam pertandingan (hidup atau sudah dieksekusi).
    def allies(self, name):
        if self.players[name].role != "hitman":
            return []
        return [
            peserta.name
            for peserta in self.players.values()
            if peserta.role == "hitman" and peserta.name != name
        ]

    # Rekan Spy: Spy lain dalam pertandingan (hidup atau tidak); terisi di room yang sejak awal ≥ 2 Spy.
    # Terpisah dari allies, karena kode bot membaca allies sebagai rekan Syndicate.
    def spy_allies(self, name):
        if self.players[name].role != "spy":
            return []
        return [
            peserta.name
            for peserta in self.players.values()
            if peserta.role == "spy" and peserta.name != name
        ]

    # Kanal chat tim: Hitman atau Spy di room yang sejak awal punya ≥ 2 pemain role itu; selain itu None.
    def team_channel(self, name):
        role = self.players[name].role
        return role if role in self.team_messages and self.composition()[role] >= 2 else None

    # Hak chat tim: hanya saat malam, untuk pemain hidup yang tidak disandera (Hitman tidak bisa disandera).
    # Gag tidak berpengaruh karena hanya membatasi chat publik. Bot punya hak yang sama dengan manusia.
    def can_team_chat(self, name):
        pemain = self.players.get(name)
        return bool(
            pemain
            and pemain.alive
            and not pemain.hostage
            and self.phase == "night"
            and self.team_channel(name)
        )

    # PESAN TIM: hanya untuk rekan setim lewat snapshot; sengaja tidak memakai nomor urut pesan publik,
    # karena lompatan nomor pada ID chat publik akan memberi tahu warga bahwa ada pesan rahasia.
    def add_team_message(self, sender, message):
        if not self.can_team_chat(sender):
            raise ValueError("Chat tim tidak tersedia untukmu saat ini.")
        message = message.strip()
        if not message or len(message) > 1000:
            raise ValueError("Pesan chat harus berisi 1–1000 karakter.")
        kanal = self.team_channel(sender)
        pesan_tim = {"id": uuid4().hex, "sender": sender, "message": message}
        self.team_messages[kanal] = (self.team_messages[kanal] + [pesan_tim])[-TEAM_CHAT_LIMIT:]
        return pesan_tim

    # AKSI PRIVAT: pilihan malam disimpan, belum diresolusikan sebelum deadline.
    def act(self, name, ability, target_name):
        pemain = self.actor(name)
        # Hostage kehilangan semua aksi: chat, vote, dan skill malam.
        if pemain.hostage:
            raise ValueError("Pemain yang disandera tidak dapat melakukan aksi.")
        if ability == "gag":
            if self.phase != "day" or pemain.role != "hitman" or self.round < self.next_gag:
                raise ValueError("Gag Order belum tersedia.")
            pemain_target = self.target(pemain, target_name)
            if pemain_target.role == "hitman":
                raise ValueError("Tidak bisa menarget rekan Syndicate.")
            if pemain_target.hostage:
                raise ValueError("Pemain itu sudah disandera.")
            pemain_target.gagged = True
            self.next_gag = self.round + 2
            return
        kemampuan_malam = NIGHT_ABILITY.get(pemain.role)
        if (
            kemampuan_malam is None
            or self.phase != "night"
            or ability != kemampuan_malam
            or name in self.actions
        ):
            raise ValueError("Aksi malam tidak tersedia atau sudah dikunci.")
        pemain_target = self.target(pemain, target_name, allow_self=ability == "guard")
        if ability == "hostage" and pemain_target.role == "hitman":
            raise ValueError("Tidak bisa menarget rekan Syndicate.")
        # Status Hostage publik: korban lama tidak bisa disandera lagi, jadi malam Syndicate tidak terbuang.
        if ability == "hostage" and pemain_target.hostage:
            raise ValueError("Pemain itu sudah disandera.")
        if ability == "peek" and self.round < pemain.next_peek:
            raise ValueError("Peek hanya tersedia sekali setiap dua ronde.")
        self.actions[name] = {"ability": ability, "target": target_name}

    # VOTE: satu pilihan per pemain; hanya Hostage/kematian yang mencabut suara, bukan Gag Order.
    def vote(self, name, target_name):
        pemain = self.actor(name)
        if self.phase != "tribunal" or pemain.hostage or name in self.votes:
            raise ValueError("Voting tidak tersedia atau pilihan sudah dikunci.")
        self.target(pemain, target_name)
        self.votes[name] = target_name

    # BATAL VOTE: selama Tribunal suara boleh ditarik lalu dipilih ulang; yang dihitung suara saat waktu habis.
    def cancel_vote(self, name):
        pemain = self.actor(name)
        if self.phase != "tribunal" or pemain.hostage or name not in self.votes:
            raise ValueError("Tidak ada suara yang bisa dibatalkan.")
        del self.votes[name]

    # BATAL AKSI MALAM: Hostage/Guard/Peek boleh ditarik lalu dipilih ulang selama malam; yang diresolusikan
    # pilihan saat waktu habis. Gag Order tidak ikut: efeknya langsung (target dibungkam, cooldown jalan).
    def cancel_action(self, name):
        pemain = self.actor(name)
        if self.phase != "night" or pemain.hostage or name not in self.actions:
            raise ValueError("Tidak ada aksi malam yang bisa dibatalkan.")
        del self.actions[name]

    # Satu korban per malam untuk Syndicate: pilihan terbanyak. Seri manusia lawan bot → pilihan manusia;
    # sesama manusia atau sesama bot → yang dipilih paling awal.
    def syndicate_target(self):
        pilihan_hostage = [
            (aksi["target"], self.players[nama].bot)
            for nama, aksi in self.actions.items()
            if aksi["ability"] == "hostage"
        ]
        if not pilihan_hostage:
            return None
        jumlah_pilihan = Counter(target for target, _ in pilihan_hostage)
        pilihan_teratas = [
            pilihan
            for pilihan in pilihan_hostage
            if jumlah_pilihan[pilihan[0]] == max(jumlah_pilihan.values())
        ]
        return next(
            (target for target, dari_bot in pilihan_teratas if not dari_bot),
            pilihan_teratas[0][0],
        )

    # RESOLUSI MALAM: semua pilihan dibaca bersama, Guard diprioritaskan terhadap Hostage. Korban yang
    # berhasil diumumkan ke semua pemain; Hostage gagal (dijaga Guard) atau tanpa pilihan diumumkan sama:
    # tidak ada yang disandera. Target Hostage yang gagal, Guard, dan Peek tetap rahasia.
    def resolve_night(self):
        target_dijaga = set()
        for nama, aksi in self.actions.items():
            pemain = self.players[nama]
            nama_target = aksi["target"]
            if aksi["ability"] == "guard":
                target_dijaga.add(nama_target)
                pemain.last_guard = nama_target
                pemain.last_guard_round = self.round
            elif aksi["ability"] == "peek":
                pemain.intel.append(
                    {
                        "round": self.round,
                        "name": nama_target,
                        "role": self.players[nama_target].role,
                    }
                )
                pemain.next_peek = self.round + 2
        target_hostage = self.syndicate_target()
        korban = None
        if target_hostage is not None:
            self.syndicate_log.append(
                {
                    "round": self.round,
                    "name": target_hostage,
                    "success": target_hostage not in target_dijaga,
                }
            )
            if target_hostage not in target_dijaga:
                korban = self.players[target_hostage]
                korban.hostage, korban.hostage_round = True, self.round
        if korban:
            self.events.append(
                f"Malam selesai. {self.labels[korban.name]} disandera: tidak bisa chat, vote, atau "
                "memakai skill sampai permainan selesai."
            )
        else:
            self.events.append("Malam selesai. Malam ini tidak ada yang disandera.")
        self.check_winner()

    # Pemimpin suara Tribunal: lebih dari satu berarti seri; kosong berarti tanpa suara.
    def vote_leaders(self):
        jumlah_suara = Counter(self.votes.values())
        return [nama for nama, suara in jumlah_suara.items() if suara == max(jumlah_suara.values())]

    # Lama fase berjalan termasuk waktu tambahan seri. Dipakai jadwal bot dan simulasi panel, yang menghitung
    # waktu dari deadline: dengan durasi saja, deadline yang bertambah membuat fase tampak mundur.
    def phase_length(self):
        waktu_tambahan = (
            self.tribunal_extra_seconds if self.phase == "tribunal" and self.tribunal_extra else 0
        )
        return self.durations.get(self.phase, 0) + waktu_tambahan

    # RESOLUSI TRIBUNAL: plurality; seri/tanpa suara tidak mengeksekusi siapa pun.
    def resolve_votes(self):
        pemimpin_suara = self.vote_leaders()
        if len(pemimpin_suara) == 1:
            self.players[pemimpin_suara[0]].alive = False
            self.events.append(
                f"Tribunal mengeksekusi {self.labels[pemimpin_suara[0]]}.{self._catatan_tersingkir()}"
            )
        else:
            self.events.append("Tribunal berakhir tanpa eksekusi: suara seri atau tidak ada suara.")
        self.check_winner()

    # Akhiran pengumuman eksekusi/keluar: Hitman tersisa (room ≥ 2 Hitman) dan kerahasiaan role.
    def _catatan_tersingkir(self):
        hitman_tersisa = self.hitman_remaining()
        catatan_jumlah = "" if hitman_tersisa is None else f" Hitman tersisa: {hitman_tersisa}."
        # Hitman terakhir yang tersingkir langsung mengakhiri permainan dan membuka semua role.
        hitman_habis = not any(
            peserta.alive for peserta in self.players.values() if peserta.role == "hitman"
        )
        catatan_rahasia = (
            "" if hitman_habis else " Role tetap dirahasiakan sampai permainan selesai."
        )
        return catatan_jumlah + catatan_rahasia

    # KELUAR DI TENGAH PERTANDINGAN: sama dengan dieksekusi (tidak hidup, tanpa chat/vote/aksi,
    # hasil tetap mengikuti kubu), tetapi ditandai `left` agar roster dan catatan membedakannya.
    # Role tetap rahasia seperti eksekusi. Pemain yang sudah mati atau match selesai tidak berubah.
    def leave(self, name, now=None):
        pemain = self.players.get(name)
        if not pemain or pemain.bot:
            raise ValueError("Hanya pemain manusia di pertandingan ini yang dapat keluar.")
        if not pemain.alive or self.winner:
            return False
        pemain.alive, pemain.left = False, True
        # Suara dan aksi milik pemain ini dibuang. Pilihan orang lain yang menargetkannya juga
        # dibuang karena target harus hidup (sama seperti korban eksekusi); mereka boleh memilih ulang.
        self.votes = {
            pemilih: target
            for pemilih, target in self.votes.items()
            if name not in (pemilih, target)
        }
        self.actions = {
            pelaku: aksi
            for pelaku, aksi in self.actions.items()
            if name not in (pelaku, aksi["target"])
        }
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
        pengumuman_kubu = {
            "civilians": "Kubu warga menang.",
            "hitman": "Hitman menang.",
        }[winner]
        self.events.append(f"{pengumuman_kubu} {explanation}")

    # Warga menang jika semua Hitman dieksekusi; Syndicate menang ketika warga bebas tidak lagi
    # lebih banyak dari Hitman yang hidup (suara warga tidak bisa lagi mengalahkan suara Hitman).
    def check_winner(self):
        if self.winner:
            return
        semua_hitman = [peserta for peserta in self.players.values() if peserta.role == "hitman"]
        jumlah_hitman_hidup = sum(peserta.alive for peserta in semua_hitman)
        warga_hidup = [
            peserta
            for peserta in self.players.values()
            if peserta.role != "hitman" and peserta.alive
        ]
        if not jumlah_hitman_hidup:
            sebutan_hitman = "Semua Hitman" if len(semua_hitman) > 1 else "Hitman"
            # Hitman yang keluar tersingkir seperti dieksekusi; alasan hasil tetap hitman_executed.
            cara_tersingkir = "dieksekusi oleh Tribunal"
            if any(peserta.left for peserta in semua_hitman):
                cara_tersingkir = (
                    "keluar dari permainan"
                    if all(peserta.left for peserta in semua_hitman)
                    else "tersingkir"
                )
            self.finish("civilians", "hitman_executed", f"{sebutan_hitman} {cara_tersingkir}.")
        elif not warga_hidup:
            self.finish("hitman", "no_civilians_alive", "Tidak ada warga yang masih hidup.")
        elif all(peserta.hostage for peserta in warga_hidup):
            self.finish(
                "hitman", "all_survivors_hostage", "Semua warga yang masih hidup telah disandera."
            )
        elif sum(not peserta.hostage for peserta in warga_hidup) <= jumlah_hitman_hidup:
            self.finish(
                "hitman",
                "vote_control",
                "Suara warga yang masih hidup dan bebas tidak lagi melampaui suara Hitman.",
            )

    def result(self, viewer):
        """Ringkasan hanya setelah selesai; korban tetap bagian dari kubu warga."""
        if not self.winner:
            return None
        kubu = "hitman" if self.players[viewer].role == "hitman" else "civilians"
        semua_warga = [peserta for peserta in self.players.values() if peserta.role != "hitman"]
        return {
            "reason": self.winner_reason,
            "team": kubu,
            "outcome": "won" if kubu == self.winner else "lost",
            "civilians_alive": sum(warga.alive for warga in semua_warga),
            "civilians_hostage": sum(warga.alive and warga.hostage for warga in semua_warga),
            "civilians_eliminated": sum(not warga.alive for warga in semua_warga),
            "civilians_voters": sum(warga.alive and not warga.hostage for warga in semua_warga),
        }

    # BOT ATURAN: aksi/vote mengikuti validasi yang sama; tidak melihat role lawan. Korban Hostage (publik)
    # tidak pernah ditarget: pasti warga dan tidak bisa disandera lagi.
    def run_bots(self):
        # INPUT: fase yang punya aksi bot; tiap fase hanya dijalankan sekali per ronde.
        penanda_selesai = {
            "day": "bot_day_done",
            "night": "bot_night_done",
            "tribunal": "bot_vote_done",
        }.get(self.phase)
        if not penanda_selesai or getattr(self, penanda_selesai):
            return
        setattr(self, penanda_selesai, True)
        for pemain in self.players.values():
            if not pemain.bot or not pemain.alive or pemain.hostage:
                continue
            if (self.round, self.phase, pemain.name) in self.npc_decisions:
                continue

            # PROSES: susun urutan target. Pengacakan ini memakai rng pertandingan, jadi urutannya
            # menentukan hasil simulasi ber-seed.
            daftar_target = [
                peserta.name
                for peserta in self.players.values()
                if peserta.alive and not peserta.hostage and peserta.name != pemain.name
            ]
            self.rng.shuffle(daftar_target)
            if pemain.role == "hitman":
                # Syndicate: rekan tidak pernah ditarget, dan Hostage mengikuti target rekan bila ada.
                rekan = set(self.allies(pemain.name))
                daftar_target = [nama for nama in daftar_target if nama not in rekan]
                target_tim = self.syndicate_target() if self.phase == "night" else None
                if target_tim in daftar_target:
                    daftar_target = [target_tim] + [
                        nama for nama in daftar_target if nama != target_tim
                    ]
            if self.phase == "tribunal":
                # Stalker hanya memakai intel hasil Peek miliknya sendiri.
                hitman_diketahui = [
                    data["name"]
                    for data in pemain.intel
                    if data["role"] == "hitman" and data["name"] in daftar_target
                ]
                daftar_target = hitman_diketahui + [
                    nama for nama in daftar_target if nama not in hitman_diketahui
                ]

            # OUTPUT: target pertama yang lolos validasi engine menjadi aksi atau vote bot.
            for nama_target in daftar_target:
                try:
                    if self.phase == "tribunal":
                        self.vote(pemain.name, nama_target)
                    else:
                        kemampuan = "gag" if self.phase == "day" else NIGHT_ABILITY.get(pemain.role)
                        self.act(pemain.name, kemampuan, nama_target)
                    break
                except ValueError:
                    continue

    # SKIP DISKUSI: hanya manusia hidup; status bungkam tidak memengaruhi hak persetujuan.
    def skip_discussion(self, name, *, now=None):
        pemain = self.players.get(name)
        if self.phase != "day" or not pemain or pemain.bot or not pemain.alive:
            raise ValueError("Persetujuan skip hanya untuk pemain manusia hidup saat siang.")
        self.skip_consents.add(name)
        self._skip_jika_lengkap(now)

    # Siang berakhir bila semua manusia hidup sudah setuju (dicek ulang saat ada pemain keluar).
    def _skip_jika_lengkap(self, waktu_sekarang=None):
        manusia_hidup = {
            peserta.name for peserta in self.players.values() if not peserta.bot and peserta.alive
        }
        if self.phase == "day" and manusia_hidup and manusia_hidup <= self.skip_consents:
            # Gunakan transisi yang sama dengan timer, termasuk kesempatan aksi bot.
            waktu_sekarang = time.time() if waktu_sekarang is None else waktu_sekarang
            self.events.append("Semua pemain manusia menyetujui akhir diskusi.")
            self.deadline = waktu_sekarang
            self.tick(waktu_sekarang)

    # TIMER SERVER: maju satu fase saat deadline; tetap berjalan walaupun semua tab ditutup.
    def tick(self, now=None):
        now = time.time() if now is None else now
        if self.phase == "preparing":
            # Batas tunggu habis: mulai dengan cadangan bawaan daripada menahan pemain selamanya.
            if now >= self.deadline:
                pesan_cadangan = "AI belum siap penuh; permainan dimulai dengan bot cadangan."
                self.begin(now, None if self.preparation["ready"] else pesan_cadangan)
            else:
                self.try_begin(now)
            return
        # Scheduler LLM mendapat waktu memilih; fallback aturan hanya mengisi pilihan yang kosong di deadline.
        if self.phase != "finished" and now >= self.deadline:
            self.run_bots()
        if self.phase == "finished" or now < self.deadline:
            return
        # SERI DI TRIBUNAL: waktu ditambah sekali untuk saling meyakinkan; suara lama tetap berlaku dan fase
        # tidak berganti. Masih seri sesudahnya = tanpa eksekusi. Tanpa suara sama sekali bukan seri.
        if self.phase == "tribunal" and not self.tribunal_extra and len(self.vote_leaders()) >= 2:
            self.tribunal_extra = True
            self.deadline = now + self.tribunal_extra_seconds
            self.events.append(
                f"Suara seri. Tribunal ditambah {self.tribunal_extra_seconds} detik; "
                "suara yang sudah masuk tetap berlaku."
            )
            self.events = self.events[-40:]
            return
        # URUTAN: ronde 1 siang → malam (belum ada bahan untuk vote); ronde berikutnya siang → Tribunal → malam.
        if self.phase == "day" and self.round > 1:
            self.phase = "tribunal"
            self.votes = {}
            self.tribunal_extra = False
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
                for peserta in self.players.values():
                    peserta.gagged = False
                self.events.append(f"Ronde {self.round}: diskusi siang dimulai.")
        if not self.winner:
            self.deadline = now + self.durations[self.phase]
        self.events = self.events[-40:]

    # PESAN PUBLIK: hanya dipanggil setelah pemeriksaan can_chat; ID mencegah duplikasi saat reconnect.
    # now hanya diisi simulasi yang memakai jam buatan.
    def add_message(self, sender, message, now=None):
        # ID diawali nomor urut: otak bot mengurutkan chat dengan waktu lalu ID, jadi chat dengan
        # waktu yang sama tetap kronologis (UUID murni membuat urutannya acak).
        self.jumlah_pesan += 1
        pesan = {
            "id": f"{self.jumlah_pesan:06d}{uuid4().hex[:10]}",
            "sender": sender,
            "message": message,
            "time": time.time() if now is None else now,
        }
        self.messages.append(pesan)
        self.messages = self.messages[-100:]
        return pesan

    # Data layar persiapan: progres AI, hitung mundur mulai, jumlah manusia yang sudah siap, kartu sudah dibuka atau belum.
    def preparation_view(self, viewer):
        waktu_sekarang = time.time()
        persiapan = self.preparation
        waktu_mulai = self._hitung_waktu_mulai()
        return {
            "ready": persiapan["ready"],
            "detail": persiapan["detail"],
            "progress": round(persiapan["progress"], 2),
            "starts_in": max(0, ceil(waktu_mulai - waktu_sekarang)) if waktu_mulai else None,
            "max_wait": max(0, ceil(self.deadline - waktu_sekarang)),
            "agreed": len(self.ready_consents),
            "required": sum(not peserta.bot and peserta.alive for peserta in self.players.values()),
            "consented": viewer in self.ready_consents,
            "revealed": viewer in self.revealed,
        }

    # Username dari label (target keputusan bot); nama yang bukan label dikembalikan apa adanya.
    def username(self, label):
        return next((username for username, nama in self.labels.items() if nama == label), label)

    # Jumlah tiap role sejak awal pertandingan; publik untuk semua pemain (siapa pemegangnya tetap rahasia).
    def composition(self):
        jumlah_role = Counter(peserta.role for peserta in self.players.values())
        return {role: jumlah_role[role] for role in ("hitman", "spy", "stalker", "civilian")}

    # Room dengan ≥ 2 Hitman mengumumkan Hitman yang masih hidup (berubah saat eksekusi/keluar).
    # Room 1 Hitman: None, karena warga sudah tahu dari game yang selesai atau berlanjut.
    def hitman_remaining(self):
        semua_hitman = [peserta for peserta in self.players.values() if peserta.role == "hitman"]
        return sum(peserta.alive for peserta in semua_hitman) if len(semua_hitman) >= 2 else None

    # SNAPSHOT PRIVAT: roster publik berisi status hidup, keluar, dan Hostage; Gag orang lain tidak pernah dikirim.
    def snapshot(self, viewer):
        # INPUT: role dan hak aksi pemain yang meminta snapshot.
        pemain = self.players[viewer]
        adalah_hitman = pemain.role == "hitman"
        adalah_spy = pemain.role == "spy"
        boleh_chat_tim = self.can_team_chat(viewer)
        kemampuan = None
        if self.phase == "day" and adalah_hitman:
            kemampuan = "gag"
        elif self.phase == "night":
            kemampuan = NIGHT_ABILITY.get(pemain.role)
        bisa_beraksi = bool(kemampuan and pemain.alive and not pemain.hostage and not self.winner)
        if kemampuan == "gag":
            bisa_beraksi &= self.round >= self.next_gag
        elif kemampuan:
            bisa_beraksi &= viewer not in self.actions and (
                kemampuan != "peek" or self.round >= pemain.next_peek
            )

        # OUTPUT: data publik pertandingan, lalu data privat pemain ini di `me`.
        return {
            # Vote yang sudah dikirim terbuka saat Tribunal, tanpa daftar hak vote/status bungkam.
            "tribunal_votes": (
                [
                    {
                        "target": nama,
                        "voters": [
                            pemilih for pemilih, target in self.votes.items() if target == nama
                        ],
                    }
                    for nama in self.players
                ]
                if self.phase == "tribunal"
                else []
            ),
            "discussion_skip": {
                "agreed": len(self.skip_consents) if self.phase == "day" else 0,
                "required": sum(
                    not peserta.bot and peserta.alive for peserta in self.players.values()
                ),
                "consented": viewer in self.skip_consents if self.phase == "day" else False,
                "can_consent": self.phase == "day"
                and not pemain.bot
                and pemain.alive
                and viewer not in self.skip_consents,
            },
            "id": self.id,
            "phase": self.phase,
            "round": self.round,
            "deadline": self.deadline,
            "tribunal_extra": self.phase == "tribunal" and self.tribunal_extra,
            "server_time": time.time(),
            "winner": self.winner,
            "events": list(self.events),
            "result": self.result(viewer),
            "preparation": self.preparation_view(viewer) if self.phase == "preparing" else None,
            "composition": self.composition(),
            "hitman_remaining": self.hitman_remaining(),
            "players": [
                {
                    "name": peserta.name,
                    "label": self.labels[peserta.name],
                    "alive": peserta.alive,
                    "skin_id": peserta.skin_id,
                    # Keluar sudah diumumkan di catatan, jadi tandanya publik (hanya bila benar).
                    **({"left": True} if peserta.left else {}),
                    # Hostage diumumkan saat malam selesai, jadi status dan malamnya publik (hanya bila benar).
                    **(
                        {"hostage": True, "hostage_round": peserta.hostage_round}
                        if peserta.hostage
                        else {}
                    ),
                    **({"thinking": True} if peserta.name in self.bot_berpikir else {}),
                    **(
                        {"tahap": self.bot_tahap[peserta.name]}
                        if peserta.name in self.bot_tahap
                        else {}
                    ),
                    **({"role": peserta.role, "bot": peserta.bot} if self.winner else {}),
                }
                for peserta in self.players.values()
            ],
            "messages": list(self.messages),
            "me": {
                "name": viewer,
                "role": pemain.role,
                "alive": pemain.alive,
                "hostage": pemain.hostage,
                "gagged": pemain.gagged,
                "muted": pemain.hostage or pemain.gagged,
                "can_chat": self.can_chat(viewer),
                "can_vote": self.phase == "tribunal"
                and pemain.alive
                and not pemain.hostage
                and viewer not in self.votes,
                "can_cancel_vote": self.phase == "tribunal"
                and pemain.alive
                and not pemain.hostage
                and viewer in self.votes,
                "vote": self.votes.get(viewer),
                "ability": kemampuan,
                "can_act": bool(bisa_beraksi),
                "action": self.actions.get(viewer) if self.phase == "night" else None,
                "can_cancel_action": self.phase == "night"
                and pemain.alive
                and not pemain.hostage
                and viewer in self.actions,
                # Cooldown Gag bersama hanya untuk Syndicate; warga tidak boleh tahu kapan Gag dipakai.
                "next_gag": self.next_gag if adalah_hitman else 1,
                "next_peek": pemain.next_peek,
                "allies": self.allies(viewer),
                # Korban Hostage tim malam ini (aturan seri: lihat syndicate_target), hanya untuk Syndicate.
                "syndicate_target": (
                    self.syndicate_target() if adalah_hitman and self.phase == "night" else None
                ),
                # Hasil Hostage tim tiap malam (gagal = dijaga Guard), hanya untuk Syndicate.
                "syndicate_hostages": list(self.syndicate_log) if adalah_hitman else [],
                # Target Gag ronde ini (Gag dipakai bersama Syndicate); warga hanya tahu status dirinya sendiri.
                "ally_gags": (
                    [peserta.name for peserta in self.players.values() if peserta.gagged]
                    if adalah_hitman
                    else []
                ),
                # Pilihan Hostage rekan malam ini agar Syndicate bisa sepakat satu target.
                "ally_actions": (
                    [
                        {"name": nama, "target": aksi["target"]}
                        for nama, aksi in self.actions.items()
                        if nama != viewer and aksi["ability"] == "hostage"
                    ]
                    if adalah_hitman and self.phase == "night"
                    else []
                ),
                # Rekan Spy dan pilihan Guard mereka malam ini; kosong untuk selain Spy dan di room satu Spy.
                "spy_allies": self.spy_allies(viewer),
                "spy_actions": (
                    [
                        {"name": nama, "target": aksi["target"]}
                        for nama, aksi in self.actions.items()
                        if nama != viewer and aksi["ability"] == "guard"
                    ]
                    if adalah_spy and self.phase == "night"
                    else []
                ),
                # Chat tim malam ini: hanya pemain yang berhak, dan hanya kanal timnya sendiri.
                "can_team_chat": boleh_chat_tim,
                "team_messages": (
                    list(self.team_messages[self.team_channel(viewer)]) if boleh_chat_tim else []
                ),
                # Rekan setim manusia yang masih hidup, hanya untuk penonton bot: pemain manusia tidak boleh
                # tahu siapa bot.
                "team_humans": (
                    [
                        nama
                        for nama in self.allies(viewer) + self.spy_allies(viewer)
                        if not self.players[nama].bot and self.players[nama].alive
                    ]
                    if pemain.bot
                    else []
                ),
                "last_guard": (
                    pemain.last_guard if pemain.last_guard_round == self.round - 1 else None
                ),
                "intel": list(pemain.intel),
            },
        }

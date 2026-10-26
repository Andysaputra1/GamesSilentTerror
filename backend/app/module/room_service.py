"""Live lobby registry for a single backend process. Restart clears active rooms."""

import logging
from dataclasses import dataclass, field
from sqlalchemy import text
import secrets
import threading
from threading import RLock
from app.module.mysql_connector import SessionLocal
from app.module.match_engine import Match, label_unik, phase_durations
from app.module.activity_service import activity, traced

logger = logging.getLogger("shadow_heist.rooms")

# Nama NPC; juga dicadangkan agar tidak bisa dipakai sebagai username akun.
BOT_NAMES = ("NOX", "ECHO", "VEIL", "RAVEN", "ASH", "DUSK", "IRIS", "SAGE", "ONYX", "LARK")


@dataclass
class Room:
    code: str
    owner: str
    members: list[str] = field(default_factory=list)
    members_skin: dict[str, str] = field(default_factory=dict)
    members_label: dict[str, str] = field(default_factory=dict)  # username → nama tampilan
    bot_enabled: bool = False
    match: Match | None = None
    capacity: int = 6
    peserta_tercatat: bool = False  # peserta pertandingan selesai sudah dikirim ke arsip survei


class RoomService:
    # CONSTRUCTOR: siapkan registry ruangan di memori dan lock untuk operasi dari beberapa thread.
    def __init__(self):
        self.rooms: dict[str, Room] = {}
        self.lock = RLock()

    # HELPER: skin_id dan nama tampilan dari user_accounts; akun yang tidak ditemukan memakai bawaan.
    def _fetch_profiles(self, usernames: list[str]) -> dict[str, tuple[str, str]]:
        if not usernames:
            return {}
        database = SessionLocal()
        try:
            placeholders = ", ".join([f":u{i}" for i in range(len(usernames))])
            params = {f"u{i}": name for i, name in enumerate(usernames)}
            sql = text(f"""
                SELECT username, skin_id, display_name FROM user_accounts
                WHERE username IN ({placeholders})
            """)
            rows = {
                row.username: (row.skin_id, row.display_name)
                for row in database.execute(sql, params)
            }
            return {name: rows.get(name, ("dexter", name)) for name in usernames}
        finally:
            database.close()

    # Simpan skin dan nama tampilan anggota baru ke ruangan.
    def _ingat_profil(self, room, usernames):
        for name, (skin_id, display_name) in self._fetch_profiles(usernames).items():
            room.members_skin[name], room.members_label[name] = skin_id, display_name

    # SERVICE LOBBY: buat kode unik 6 karakter, tetapkan pemilik sebagai anggota pertama, dan batasi jumlah ruangan.
    @traced
    def create(self, username: str, capacity=6) -> Room:
        if capacity not in range(4, 11):
            raise ValueError("Room membutuhkan 4–10 kursi.")
        with self.lock:
            if self.active(username):
                raise ValueError("Selesaikan pertandingan aktif sebelum membuat ruangan lain.")
            self._lepas_room_selesai(username)
            if self.current(username):
                raise ValueError("Keluar dari ruangan sebelumnya sebelum membuat ruangan baru.")
            if len(self.rooms) >= 500:
                raise ValueError("Batas ruangan aktif tercapai. Hubungi pengelola.")
            code = secrets.token_hex(3).upper()
            while code in self.rooms:
                code = secrets.token_hex(3).upper()
            room = Room(code, username, [username], capacity=capacity)
            self._ingat_profil(room, [username])
            self.rooms[code] = room
            return room

    # SERVICE AKSES: ambil ruangan berdasarkan kode serta pastikan pengguna merupakan anggotanya.
    def get(self, code: str, username: str) -> Room:
        with self.lock:
            room = self.rooms.get(code.strip().upper())
            if room is None:
                raise ValueError("Ruangan tidak ditemukan atau server sudah dimulai ulang.")
            if username not in room.members:
                if room.match is not None:
                    raise ValueError("Pertandingan sudah dimulai; tunggu ruangan baru.")
                raise ValueError("Gabung ke ruangan ini terlebih dahulu.")
            return room

    # SERVICE LOBBY: tambahkan anggota tanpa duplikasi; tolak ruangan hilang atau kapasitas pilihan host penuh.
    @traced
    def join(self, code: str, username: str) -> Room:
        with self.lock:
            active = self.active(username)
            if active and active["code"] != code.strip().upper():
                raise ValueError("Kembali ke pertandingan aktifmu terlebih dahulu.")
            self._lepas_room_selesai(username, kecuali=code.strip().upper())
            current = self.current(username)
            if current and current.code != code.strip().upper():
                raise ValueError(
                    "Keluar dari ruangan sebelumnya sebelum bergabung ke ruangan lain."
                )
            room = self.rooms.get(code.strip().upper())
            if room is None:
                raise ValueError("Kode ruangan tidak ditemukan.")
            if username not in room.members:
                if room.match is not None:
                    raise ValueError("Pertandingan sudah dimulai; buat atau gabung ruangan lain.")
                if len(room.members) >= room.capacity:
                    raise ValueError(f"Ruangan sudah penuh (maksimal {room.capacity} pemain).")
                room.members.append(username)
                self._ingat_profil(room, [username])
            return room

    # SERVICE LOBBY: periksa kepemilikan lalu aktifkan/nonaktifkan NOX pada ruangan.
    @traced
    def set_bot(self, code: str, username: str, enabled: bool) -> Room:
        with self.lock:
            room = self.get(code, username)
            if room.owner != username:
                raise ValueError("Hanya pembuat ruangan yang dapat mengatur bot.")
            if room.match is not None:
                raise ValueError("Bot tidak dapat diubah setelah pertandingan dimulai.")
            if enabled and len(room.members) >= room.capacity:
                raise ValueError("Kursi penuh. Bot membutuhkan satu kursi kosong.")
            room.bot_enabled = enabled
            return room

    # METHOD SERIALISASI: salin data publik ruangan dan roster untuk respons API/socket.
    def snapshot(self, room: Room):
        with self.lock:
            members_with_skin = [
                {
                    "name": name,
                    "label": room.members_label.get(name, name),
                    "skin_id": room.members_skin.get(name, "dexter"),
                }
                for name in room.members
            ]
            return {
                "code": room.code,
                "owner": room.owner,
                "members": members_with_skin,
                "bot_enabled": room.bot_enabled,
                "bots": self.bot_names(room),
                "phase": room.match.phase if room.match else "lobby",
                "capacity": room.capacity,
                "match_durations": dict(room.match.durations) if room.match else None,
                "phase_durations": {
                    "standard": phase_durations(
                        max(4, len(room.members) + len(self.bot_names(room)))
                    ),
                    "quick": phase_durations(
                        max(4, len(room.members) + len(self.bot_names(room))), True
                    ),
                },
            }

    # NPC mengisi sisa kapasitas yang dipilih host; manusia yang bergabung menggantikan kursi NPC.
    def bot_names(self, room):
        if room.match:
            return [p.name for p in room.match.players.values() if p.bot]
        if not room.bot_enabled:
            return []
        count = room.capacity - len(room.members)
        return [name for name in BOT_NAMES if name not in room.members][:count]

    # START: hanya host; role tidak pernah dikembalikan lewat snapshot lobby.
    @traced
    def start(self, code, username, quick=False):
        with self.lock:
            room = self.get(code, username)
            if room.owner != username:
                raise ValueError("Hanya pembuat ruangan yang dapat memulai.")
            if room.match:
                raise ValueError(
                    "Pertandingan sudah dimulai. Buat ruangan baru untuk bermain lagi."
                )
            if any(self.active(name) for name in room.members):
                raise ValueError("Ada anggota yang masih mengikuti pertandingan lain.")
            self._ingat_profil(room, room.members)
            bots = self.bot_names(room)
            # Ronde 1 ditahan di layar persiapan sampai otak bot siap (NPCService.prepare).
            room.match = Match(
                room.members,
                bots,
                skin_map=room.members_skin,
                labels=label_unik({u: room.members_label.get(u, u) for u in room.members}, bots),
                quick=quick,
                preparing=True,
            )
            room.match.ai_controlled = True
            return self.snapshot(room)

    # SIAP: manusia boleh mempercepat layar persiapan setelah membaca panduan; AI tetap harus siap.
    @traced
    def ready(self, code, username, *, match_id):
        with self.lock:
            room = self.get(code, username)
            match = room.match
            if not match or match.id != match_id:
                raise ValueError("Pertandingan sudah berganti. Perbarui halaman.")
            match.tick()
            if match.phase == "preparing":
                match.ready_consent(username)
            return self.state(code, username)

    # BUKA KARTU: ronde 1 menunggu semua manusia melihat role-nya (paling lama REVEAL_WAIT_SECONDS).
    @traced
    def reveal(self, code, username, *, match_id):
        with self.lock:
            room = self.get(code, username)
            match = room.match
            if not match or match.id != match_id:
                raise ValueError("Pertandingan sudah berganti. Perbarui halaman.")
            match.tick()
            if match.phase == "preparing":
                match.reveal_role(username)
            return self.state(code, username)

    # PEMULIHAN: cari pertandingan akun dari server, bukan mengandalkan sessionStorage tab.
    def current(self, username):
        """Pulihkan lobby/hasil setelah login ulang, tanpa data role privat."""
        with self.lock:
            return next((room for room in self.rooms.values() if username in room.members), None)

    # Pertandingan yang baru selesai (lewat timer atau pemain keluar): peserta manusianya dicatat sekali ke
    # arsip survei di thread latar, jadi jam permainan tidak menunggu database.
    def _catat_selesai(self, room):
        if room.peserta_tercatat or not room.match or not room.match.winner:
            return
        room.peserta_tercatat = True
        # Impor lambat: survey_service mengimpor modul ini.
        from app.module.survey_service import survey_service

        baris = survey_service.baris_peserta(room)
        threading.Thread(target=survey_service.catat_peserta, args=(baris,), daemon=True).start()

    # Room yang pertandingannya sudah selesai tidak menahan pemain: keanggotaannya dilepas sebelum membuat atau
    # bergabung ke room lain (survei pertandingan itu tetap bisa dikirim lewat registri pertandingan selesai).
    def _lepas_room_selesai(self, username, kecuali=None):
        with self.lock:
            room = self.current(username)
            if room and room.code != kecuali and room.match and room.match.winner:
                self.leave(room.code, username)

    # Cari pertandingan yang belum selesai untuk mencegah pengguna bermain di dua ruangan.
    def active(self, username):
        with self.lock:
            for room in self.rooms.values():
                if username in room.members and room.match:
                    room.match.tick()
                    if not room.match.winner:
                        return {"code": room.code, "match_id": room.match.id}
            return None

    # SKIP: token fase menolak persetujuan basi dari tab lain atau ronde sebelumnya.
    @traced
    def skip(self, code, username, *, match_id, round_number, phase):
        with self.lock:
            room = self.get(code, username)
            match = room.match
            if not match:
                raise ValueError("Pertandingan belum dimulai.")
            match.tick()
            if (match.id, match.round, match.phase) != (match_id, round_number, phase):
                raise ValueError("Fase sudah berubah. Perbarui halaman sebelum menyetujui.")
            match.skip_discussion(username)
            return self.state(code, username)

    # BATAL VOTE: token fase yang sama dengan play, agar klik basi tidak menarik suara ronde lain.
    @traced
    def cancel_vote(self, code, username, *, match_id, round_number, phase):
        with self.lock:
            room = self.get(code, username)
            match = room.match
            if not match:
                raise ValueError("Pertandingan belum dimulai.")
            match.tick()
            if (match.id, match.round, match.phase) != (match_id, round_number, phase):
                raise ValueError("Fase sudah berubah. Perbarui halaman sebelum membatalkan.")
            match.cancel_vote(username)
            return self.state(code, username)

    # Semua operasi engine memakai lock yang sama agar request bersamaan tidak menggandakan aksi.
    def state(self, code, username):
        with self.lock:
            room = self.get(code, username)
            if not room.match:
                raise ValueError("Host belum memulai pertandingan.")
            room.match.tick()
            return {"room": self.snapshot(room), "game": room.match.snapshot(username)}

    # COMMAND: validasi token pertandingan/fase sebelum mengunci aksi atau vote.
    @traced
    def play(self, code, username, *, match_id, round_number, phase, target, ability=None):
        with self.lock:
            room = self.get(code, username)
            match = room.match
            if not match:
                raise ValueError("Pertandingan belum dimulai.")
            match.tick()
            if (match.id, match.round, match.phase) != (match_id, round_number, phase):
                raise ValueError("Fase sudah berubah. Perbarui halaman sebelum memilih lagi.")
            if ability:
                match.act(username, ability, target)
            else:
                match.vote(username, target)
            return self.state(code, username)

    # CLOCK: dipanggil background task, bukan bergantung pada request browser.
    def tick_all(self):
        with self.lock:
            for room in self.rooms.values():
                if room.match:
                    before = (room.match.phase, room.match.round)
                    try:
                        room.match.tick()
                        self._catat_selesai(room)
                    except Exception:
                        # Satu pertandingan rusak tidak boleh menghentikan timer room lain.
                        logger.exception("Timer room %s gagal.", room.code)
                        continue
                    if before != (room.match.phase, room.match.round):
                        activity.record(
                            room.code,
                            "Match.tick",
                            {"phase_before": before[0], "round_before": before[1]},
                            result={
                                "phase": room.match.phase,
                                "round": room.match.round,
                                "winner": room.match.winner,
                            },
                        )

    # LEAVE: dari lobby/hasil keluar biasa. Dari pertandingan aktif, pemain dianggap tereliminasi
    # seperti dieksekusi (Match.leave) lalu keanggotaannya dicabut, jadi tidak bisa kembali ke
    # pertandingan itu. Room tanpa anggota manusia dibersihkan; keluar dua kali tidak mengubah apa pun.
    @traced
    def leave(self, code, username):
        with self.lock:
            room = self.rooms.get(code.strip().upper())
            match = room.match if room else None
            if match and username in match.players and username not in room.members:
                return  # sudah keluar dari pertandingan ini
            room = self.get(code, username)
            if room.match and not room.match.winner:
                room.match.tick()
                room.match.leave(username)
            if room.match:
                # Survei akhir tetap bisa dikirim setelah keluar (room mungkin segera dibersihkan).
                # Impor lambat: survey_service mengimpor modul ini.
                from app.module.survey_service import survey_service

                survey_service.ingat_pertandingan(room)
                self._catat_selesai(
                    room
                )  # room bisa dihapus di bawah sebelum timer sempat mencatat
            room.members.remove(username)
            room.members_skin.pop(username, None)
            room.members_label.pop(username, None)
            if not room.members:
                del self.rooms[room.code]
            elif username == room.owner:
                room.owner = room.members[0]


room_service = RoomService()

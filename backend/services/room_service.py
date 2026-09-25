"""Live lobby registry for a single backend process. Restart clears active rooms."""

from dataclasses import dataclass, field
from sqlalchemy import text
import secrets
from threading import RLock
from module.mysql_connector import SessionLocal
from services.match_engine import Match, phase_durations
from services.activity_service import activity, traced


@dataclass
class Room:
    code: str
    owner: str
    members: list[str] = field(default_factory=list)
    members_skin: dict[str, str] = field(default_factory=dict)
    bot_enabled: bool = False
    match: Match | None = None
    capacity: int = 6


class RoomService:
    # CONSTRUCTOR: siapkan registry ruangan di memori dan lock untuk operasi dari beberapa thread.
    def __init__(self):
        self.rooms: dict[str, Room] = {}
        self.lock = RLock()

    # HELPER: ambil skin_id dari user_accounts untuk daftar username.
    def _fetch_skin_ids(self, usernames: list[str]) -> dict[str, str]:
        if not usernames:
            return {}
        database = SessionLocal()
        try:
            placeholders = ', '.join([f':u{i}' for i in range(len(usernames))])
            params = {f'u{i}': name for i, name in enumerate(usernames)}
            sql = text(f"""
                SELECT username, skin_id FROM user_accounts
                WHERE username IN ({placeholders})
            """)
            result = database.execute(sql, params)
            skin_map = {row.username: row.skin_id for row in result}
            for name in usernames:
                if name not in skin_map:
                    skin_map[name] = "dexter"
            return skin_map
        finally:
            database.close()

    # SERVICE LOBBY: buat kode unik 6 karakter, tetapkan pemilik sebagai anggota pertama, dan batasi jumlah ruangan.
    @traced
    def create(self, username: str, capacity=6) -> Room:
        if capacity not in range(4, 11):
            raise ValueError("Room membutuhkan 4–10 kursi.")
        with self.lock:
            if self.active(username):
                raise ValueError("Selesaikan pertandingan aktif sebelum membuat ruangan lain.")
            if self.current(username):
                raise ValueError("Keluar dari ruangan sebelumnya sebelum membuat ruangan baru.")
            if len(self.rooms) >= 500:
                raise ValueError("Batas ruangan aktif tercapai. Hubungi pengelola.")
            code = secrets.token_hex(3).upper()
            while code in self.rooms:
                code = secrets.token_hex(3).upper()
            room = Room(code, username, [username], capacity=capacity)
            room.members_skin = self._fetch_skin_ids([username])
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
                room.members_skin[username] = self._fetch_skin_ids([username]).get(username, "dexter")
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
                {"name": name, "skin_id": room.members_skin.get(name, "dexter")}
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
        return [
            name
            for name in [
                "NOX",
                "ECHO",
                "VEIL",
                "RAVEN",
                "ASH",
                "DUSK",
                "IRIS",
                "SAGE",
                "ONYX",
                "LARK",
            ]
            if name not in room.members
        ][:count]

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
            room.members_skin = self._fetch_skin_ids(room.members)
            room.match = Match(room.members, self.bot_names(room),
                             skin_map=room.members_skin, quick=quick)
            room.match.ai_controlled = True
            return self.snapshot(room)

    # PEMULIHAN: cari pertandingan akun dari server, bukan mengandalkan sessionStorage tab.
    def current(self, username):
        """Pulihkan lobby/hasil setelah login ulang, tanpa data role privat."""
        with self.lock:
            return next((room for room in self.rooms.values() if username in room.members), None)

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
                    room.match.tick()
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

    # LEAVE: pertandingan aktif tidak boleh berubah roster; lobby kosong dibersihkan.
    @traced
    def leave(self, code, username):
        with self.lock:
            room = self.get(code, username)
            if room.match and not room.match.winner:
                raise ValueError(
                    "Tidak dapat keluar dari pertandingan aktif. Kamu bisa menyambung kembali setelah menutup tab."
                )
            room.members.remove(username)
            room.members_skin.pop(username, None)
            if not room.members:
                del self.rooms[room.code]
            elif username == room.owner:
                room.owner = room.members[0]


room_service = RoomService()

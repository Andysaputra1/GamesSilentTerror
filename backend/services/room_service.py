"""Live lobby registry for a single backend process. Restart clears active rooms."""

from dataclasses import dataclass, field
import secrets
from threading import RLock


@dataclass
class Room:
    code: str
    owner: str
    members: list[str] = field(default_factory=list)
    bot_enabled: bool = False


class RoomService:
    # CONSTRUCTOR: siapkan registry ruangan di memori dan lock untuk operasi dari beberapa thread.
    def __init__(self):
        self.rooms: dict[str, Room] = {}
        self.lock = RLock()

    # SERVICE LOBBY: buat kode unik 6 karakter, tetapkan pemilik sebagai anggota pertama, dan batasi jumlah ruangan.
    def create(self, username: str) -> Room:
        with self.lock:
            if len(self.rooms) >= 500:
                raise ValueError("Batas ruangan aktif tercapai. Hubungi pengelola.")
            code = secrets.token_hex(3).upper()
            while code in self.rooms:
                code = secrets.token_hex(3).upper()
            room = Room(code, username, [username])
            self.rooms[code] = room
            return room

    # SERVICE AKSES: ambil ruangan berdasarkan kode serta pastikan pengguna merupakan anggotanya.
    def get(self, code: str, username: str) -> Room:
        with self.lock:
            room = self.rooms.get(code.strip().upper())
            if room is None:
                raise ValueError("Ruangan tidak ditemukan atau server sudah dimulai ulang.")
            if username not in room.members:
                raise ValueError("Gabung ke ruangan ini terlebih dahulu.")
            return room

    # SERVICE LOBBY: tambahkan anggota tanpa duplikasi; tolak ruangan hilang atau kapasitas enam pemain penuh.
    def join(self, code: str, username: str) -> Room:
        with self.lock:
            room = self.rooms.get(code.strip().upper())
            if room is None:
                raise ValueError("Kode ruangan tidak ditemukan.")
            if username not in room.members:
                if len(room.members) >= 6:
                    raise ValueError("Ruangan sudah penuh (maksimal 6 pemain).")
                room.members.append(username)
            return room

    # SERVICE LOBBY: periksa kepemilikan lalu aktifkan/nonaktifkan NOX pada ruangan.
    def set_bot(self, code: str, username: str, enabled: bool) -> Room:
        with self.lock:
            room = self.get(code, username)
            if room.owner != username:
                raise ValueError("Hanya pembuat ruangan yang dapat mengatur bot.")
            room.bot_enabled = enabled
            return room

    # METHOD SERIALISASI: salin data publik ruangan dan roster untuk respons API/socket.
    def snapshot(self, room: Room):
        with self.lock:
            return {"code": room.code, "owner": room.owner, "members": list(room.members),
                    "bot_enabled": room.bot_enabled}


room_service = RoomService()

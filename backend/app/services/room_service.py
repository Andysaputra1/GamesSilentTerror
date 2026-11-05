"""Daftar lobby aktif untuk satu proses backend. Restart menghapus semua room aktif.

Alurnya di lobby
1. Host membuat room (create), pemain lain bergabung dengan kodenya (join), host boleh menyalakan bot pengisi kursi kosong (set_bot)
2. Host memulai (start): pertandingan dibuat, tetapi ronde 1 ditahan di layar persiapan sampai otak bot siap

Alurnya saat pemain bertindak (play, skip, cancel_vote, cancel_action, team_chat)
1. Majukan fase sesuai timer
2. Cocokkan token fase. Kalau berbeda, klik itu basi dari tab lain atau ronde sebelumnya, jadi ditolak
3. Teruskan ke Match dan kembalikan state terbaru

Alurnya tiap detak jam (perbarui_fase_semua_room, dipanggil main.py tiap 0,5 detik)
1. Untuk tiap room yang bertanding, panggil Match.tick: kalau waktu fase habis, fase berganti
2. Pertandingan yang baru selesai: peserta manusianya dicatat sekali ke arsip survei lewat thread latar
3. Fase yang berganti dicatat ke jejak aktivitas panel
4. Satu room gagal: dicatat di log, room lain tetap jalan
"""

import logging
from dataclasses import dataclass, field
from sqlalchemy import text
import secrets
import threading
from app.config.database import SessionLocal
from app.module.match_engine import Match, label_unik, phase_durations
from app.services.activity_service import activity, traced

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
        self.lock = threading.RLock()

    # HELPER: skin_id dan nama tampilan dari user_accounts; akun yang tidak ditemukan memakai bawaan.
    def _ambil_profil_akun(self, daftar_username: list[str]) -> dict[str, tuple[str, str]]:
        if not daftar_username:
            return {}
        database = SessionLocal()
        try:
            penanda_sql = ", ".join([f":u{urutan}" for urutan in range(len(daftar_username))])
            nilai_sql = {f"u{urutan}": username for urutan, username in enumerate(daftar_username)}
            perintah_sql = text(f"""
                SELECT username, skin_id, display_name FROM user_accounts
                WHERE username IN ({penanda_sql})
            """)
            profil_tersimpan = {
                baris.username: (baris.skin_id, baris.display_name)
                for baris in database.execute(perintah_sql, nilai_sql)
            }
            return {
                username: profil_tersimpan.get(username, ("dexter", username))
                for username in daftar_username
            }
        finally:
            database.close()

    # Simpan skin dan nama tampilan anggota baru ke ruangan.
    def _ingat_profil(self, room, daftar_username):
        for username, (skin_id, nama_tampilan) in self._ambil_profil_akun(daftar_username).items():
            room.members_skin[username], room.members_label[username] = skin_id, nama_tampilan

    # Mengambil room dari kodenya, sekaligus memastikan pemain itu anggotanya.
    # Room hanya ada di memori: tidak ada query DB di sini, dan semua room hilang saat server restart.
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

    # PEMULIHAN: cari room akun dari server, bukan sessionStorage tab; tanpa data role privat.
    def current(self, username):
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

    # Pertandingan yang baru selesai (lewat timer atau pemain keluar): peserta manusianya dicatat sekali ke
    # arsip survei di thread latar, jadi jam permainan tidak menunggu database.
    def _catat_peserta_pertandingan_selesai(self, room):
        if room.peserta_tercatat or not room.match or not room.match.winner:
            return
        room.peserta_tercatat = True
        # Impor lambat: survey_service mengimpor modul ini.
        from app.services.survey_service import survey_service

        baris_peserta = survey_service.baris_peserta(room)
        threading.Thread(
            target=survey_service.catat_peserta, args=(baris_peserta,), daemon=True
        ).start()

    # LEAVE: dari lobby/hasil keluar biasa. Dari pertandingan aktif, pemain dianggap tereliminasi
    # seperti dieksekusi (Match.leave) lalu keanggotaannya dicabut, jadi tidak bisa kembali ke
    # pertandingan itu. Room tanpa anggota manusia dibersihkan; keluar dua kali tidak mengubah apa pun.
    @traced
    def leave(self, code, username):
        with self.lock:
            room = self.rooms.get(code.strip().upper())
            pertandingan = room.match if room else None
            if pertandingan and username in pertandingan.players and username not in room.members:
                return  # sudah keluar dari pertandingan ini
            room = self.get(code, username)
            if room.match and not room.match.winner:
                room.match.tick()
                room.match.leave(username)
            if room.match:
                # Survei akhir tetap bisa dikirim setelah keluar (room mungkin segera dibersihkan).
                # Impor lambat: survey_service mengimpor modul ini.
                from app.services.survey_service import survey_service

                survey_service.ingat_pertandingan(room)
                # Room bisa dihapus di bawah sebelum timer sempat mencatat.
                self._catat_peserta_pertandingan_selesai(room)
            room.members.remove(username)
            room.members_skin.pop(username, None)
            room.members_label.pop(username, None)
            if not room.members:
                del self.rooms[room.code]
            elif username == room.owner:
                room.owner = room.members[0]

    # Room yang pertandingannya sudah selesai tidak menahan pemain: keanggotaannya dilepas sebelum membuat atau
    # bergabung ke room lain (survei pertandingan itu tetap bisa dikirim lewat registri pertandingan selesai).
    def _lepas_room_selesai(self, username, kecuali=None):
        with self.lock:
            room = self.current(username)
            if room and room.code != kecuali and room.match and room.match.winner:
                self.leave(room.code, username)

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
            kode_room = secrets.token_hex(3).upper()
            while kode_room in self.rooms:
                kode_room = secrets.token_hex(3).upper()
            room = Room(kode_room, username, [username], capacity=capacity)
            self._ingat_profil(room, [username])
            self.rooms[kode_room] = room
            return room

    # SERVICE LOBBY: tambahkan anggota tanpa duplikasi; tolak ruangan hilang atau kapasitas pilihan host penuh.
    @traced
    def join(self, code: str, username: str) -> Room:
        with self.lock:
            kode_room = code.strip().upper()
            pertandingan_aktif = self.active(username)
            if pertandingan_aktif and pertandingan_aktif["code"] != kode_room:
                raise ValueError("Kembali ke pertandingan aktifmu terlebih dahulu.")
            self._lepas_room_selesai(username, kecuali=kode_room)
            room_sekarang = self.current(username)
            if room_sekarang and room_sekarang.code != kode_room:
                raise ValueError(
                    "Keluar dari ruangan sebelumnya sebelum bergabung ke ruangan lain."
                )
            room = self.rooms.get(kode_room)
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

    # SERVICE LOBBY: periksa kepemilikan lalu aktifkan/nonaktifkan bot pengisi kursi pada ruangan.
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

    # NPC mengisi sisa kapasitas yang dipilih host; manusia yang bergabung menggantikan kursi NPC.
    def bot_names(self, room):
        if room.match:
            return [peserta.name for peserta in room.match.players.values() if peserta.bot]
        if not room.bot_enabled:
            return []
        jumlah_kursi_kosong = room.capacity - len(room.members)
        return [nama for nama in BOT_NAMES if nama not in room.members][:jumlah_kursi_kosong]

    # METHOD SERIALISASI: salin data publik ruangan dan roster untuk respons API/socket.
    def snapshot(self, room: Room):
        with self.lock:
            anggota_dengan_skin = [
                {
                    "name": username,
                    "label": room.members_label.get(username, username),
                    "skin_id": room.members_skin.get(username, "dexter"),
                }
                for username in room.members
            ]
            nama_bot = self.bot_names(room)
            # Pratinjau durasi di lobby: anggota yang masih sedikit tetap dihitung 4 peserta, ukuran room terkecil.
            jumlah_peserta = max(4, len(room.members) + len(nama_bot))
            return {
                "code": room.code,
                "owner": room.owner,
                "members": anggota_dengan_skin,
                "bot_enabled": room.bot_enabled,
                "bots": nama_bot,
                "phase": room.match.phase if room.match else "lobby",
                "capacity": room.capacity,
                "match_durations": dict(room.match.durations) if room.match else None,
                "phase_durations": {
                    "standard": phase_durations(jumlah_peserta),
                    "quick": phase_durations(jumlah_peserta, True),
                },
            }

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
            if any(self.active(anggota) for anggota in room.members):
                raise ValueError("Ada anggota yang masih mengikuti pertandingan lain.")
            # Baca ulang: skin dan nama tampilan boleh diganti selama anggota menunggu di lobby.
            self._ingat_profil(room, room.members)
            nama_bot = self.bot_names(room)
            nama_tampilan = {
                anggota: room.members_label.get(anggota, anggota) for anggota in room.members
            }
            # Ronde 1 ditahan di layar persiapan sampai otak bot siap (NPCService.prepare).
            room.match = Match(
                room.members,
                nama_bot,
                skin_map=room.members_skin,
                labels=label_unik(nama_tampilan, nama_bot),
                quick=quick,
                preparing=True,
            )
            # Tanpa tanda ini NPCService melewati pertandingan, jadi bot tidak pernah melangkah.
            room.match.ai_controlled = True
            return self.snapshot(room)

    # Semua operasi engine memakai lock yang sama agar request bersamaan tidak menggandakan aksi.
    def state(self, code, username):
        with self.lock:
            room = self.get(code, username)
            if not room.match:
                raise ValueError("Host belum memulai pertandingan.")
            room.match.tick()
            return {"room": self.snapshot(room), "game": room.match.snapshot(username)}

    # SIAP: manusia boleh mempercepat layar persiapan setelah membaca panduan; AI tetap harus siap.
    @traced
    def ready(self, code, username, *, match_id):
        with self.lock:
            pertandingan = self.get(code, username).match
            if not pertandingan or pertandingan.id != match_id:
                raise ValueError("Pertandingan sudah berganti. Perbarui halaman.")
            pertandingan.tick()
            if pertandingan.phase == "preparing":
                pertandingan.ready_consent(username)
            return self.state(code, username)

    # BUKA KARTU: catat manusia yang sudah melihat role-nya; ronde 1 tetap mengikuti hitung mundur.
    @traced
    def reveal(self, code, username, *, match_id):
        with self.lock:
            pertandingan = self.get(code, username).match
            if not pertandingan or pertandingan.id != match_id:
                raise ValueError("Pertandingan sudah berganti. Perbarui halaman.")
            pertandingan.tick()
            if pertandingan.phase == "preparing":
                pertandingan.reveal_role(username)
            return self.state(code, username)

    # Perintah pemain saat bermain: maju sesuai timer dulu, lalu cocokkan token fase agar klik basi dari
    # tab lain atau ronde sebelumnya ditolak. Dipanggil di dalam lock oleh pemanggilnya.
    def _ambil_pertandingan_sesuai_token(self, code, username, token_fase, pesan_fase_berubah):
        pertandingan = self.get(code, username).match
        if not pertandingan:
            raise ValueError("Pertandingan belum dimulai.")
        pertandingan.tick()
        if (pertandingan.id, pertandingan.round, pertandingan.phase) != token_fase:
            raise ValueError(pesan_fase_berubah)
        return pertandingan

    # SKIP: token fase menolak persetujuan basi dari tab lain atau ronde sebelumnya.
    @traced
    def skip(self, code, username, *, match_id, round_number, phase):
        with self.lock:
            pertandingan = self._ambil_pertandingan_sesuai_token(
                code,
                username,
                (match_id, round_number, phase),
                "Fase sudah berubah sebelum persetujuanmu terkirim.",
            )
            pertandingan.skip_discussion(username)
            return self.state(code, username)

    # BATAL VOTE: token fase yang sama dengan play, agar klik basi tidak menarik suara ronde lain.
    @traced
    def cancel_vote(self, code, username, *, match_id, round_number, phase):
        with self.lock:
            pertandingan = self._ambil_pertandingan_sesuai_token(
                code,
                username,
                (match_id, round_number, phase),
                "Fase sudah berubah sebelum pembatalan terkirim.",
            )
            pertandingan.cancel_vote(username)
            return self.state(code, username)

    # BATAL AKSI MALAM: token fase malam yang sama, agar klik basi tidak menarik aksi malam lain.
    @traced
    def cancel_action(self, code, username, *, match_id, round_number, phase):
        with self.lock:
            pertandingan = self._ambil_pertandingan_sesuai_token(
                code,
                username,
                (match_id, round_number, phase),
                "Fase sudah berubah sebelum pembatalan terkirim.",
            )
            pertandingan.cancel_action(username)
            return self.state(code, username)

    # CHAT TIM: token fase yang sama dengan play. Sengaja tanpa @traced: jejak aktivitas panel mencatat parameter,
    # jadi isi pesan rahasia akan ikut tersimpan. Pesan hanya di memori Match, tanpa database, socket, atau NLU.
    def team_chat(self, code, username, *, match_id, round_number, phase, message):
        with self.lock:
            pertandingan = self._ambil_pertandingan_sesuai_token(
                code,
                username,
                (match_id, round_number, phase),
                "Fase sudah berubah sebelum pesanmu terkirim.",
            )
            pertandingan.add_team_message(username, message)
            return self.state(code, username)

    # COMMAND: validasi token pertandingan/fase sebelum mengunci aksi atau vote.
    @traced
    def play(self, code, username, *, match_id, round_number, phase, target, ability=None):
        with self.lock:
            pertandingan = self._ambil_pertandingan_sesuai_token(
                code,
                username,
                (match_id, round_number, phase),
                "Fase sudah berubah sebelum pilihanmu terkirim.",
            )
            if ability:
                pertandingan.act(username, ability, target)
            else:
                pertandingan.vote(username, target)
            return self.state(code, username)

    # JAM: dipanggil tiap 0,5 detik oleh game_clock, bukan oleh request browser. Untuk tiap room,
    # panggil Match.tick(): kalau waktu fase habis, fase berganti. Pergantian fase dicatat untuk panel.
    def perbarui_fase_semua_room(self):
        with self.lock:
            for room in self.rooms.values():
                pertandingan = room.match
                if not pertandingan:
                    continue
                fase_sebelum, ronde_sebelum = pertandingan.phase, pertandingan.round
                try:
                    pertandingan.tick()
                    self._catat_peserta_pertandingan_selesai(room)
                except Exception:
                    # Satu pertandingan rusak tidak boleh menghentikan timer room lain.
                    logger.exception("Timer room %s gagal.", room.code)
                    continue
                if (fase_sebelum, ronde_sebelum) != (pertandingan.phase, pertandingan.round):
                    activity.record(
                        room.code,
                        "Match.tick",
                        {"phase_before": fase_sebelum, "round_before": ronde_sebelum},
                        result={
                            "phase": pertandingan.phase,
                            "round": pertandingan.round,
                            "winner": pertandingan.winner,
                        },
                    )


room_service = RoomService()

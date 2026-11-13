"""Daftar lobby aktif untuk satu proses backend. Restart menghapus semua room aktif.

Alurnya di lobby
1. Host membuat room (create), pemain lain bergabung dengan kodenya (join), host boleh menyalakan bot pengisi kursi kosong (set_bot)
2. Host memulai (start): pertandingan dibuat, tetapi ronde 1 ditahan di layar persiapan sampai otak bot siap

Alurnya saat pemain bertindak (play, skip, cancel_vote, cancel_action, team_chat)
1. Majukan fase sesuai timer
2. Cocokkan token fase. Kalau berbeda, klik itu basi dari tab lain atau ronde sebelumnya, jadi ditolak
3. Teruskan ke Match dan kembalikan state terbaru

Alurnya saat bot bertindak (dipanggil bot/bot_controller.py; bot adalah pemain tanpa browser)
1. progres_persiapan_ai dan ai_siap: layar persiapan mengikuti pemuatan otak bot
2. lihat_untuk_bot: snapshot milik bot dan token fase yang ia lihat
3. pilihan_bot, chat_tim_bot, chat_bot: tindakan diterapkan hanya bila fase yang dilihat bot belum berganti
4. Status di kartu bot (tahap I/L/O dan awan berpikir) juga diubah lewat sini

Alurnya tiap detak jam (perbarui_fase_semua_room, dipanggil main.py tiap 0,5 detik)
1. Untuk tiap room yang bertanding, panggil Match.tick: kalau waktu fase habis, fase berganti
2. Pertandingan yang baru selesai: peserta manusianya dicatat sekali ke arsip survei lewat thread latar
3. Fase yang berganti dicatat ke jejak aktivitas panel
4. Satu room gagal: dicatat di log, room lain tetap jalan
"""

import logging
from dataclasses import dataclass, field
import secrets
import threading
import time
from app.config.database import SessionLocal
from app.models import auth_queries
from app.game.match_engine import Match, label_unik, phase_durations, snapshot_berlabel
from app.services.activity_service import activity, traced
from app.services.persistence_service import PersistenceError, PersistenceService

logger = logging.getLogger("shadow_heist.rooms")

# Nama NPC; juga dicadangkan agar tidak bisa dipakai sebagai username akun.
BOT_NAMES = ("NOX", "ECHO", "VEIL", "RAVEN", "ASH", "DUSK", "IRIS", "SAGE", "ONYX", "LARK")


# Aksi rahasia yang bisa dipilih otak bot lewat Match.act.
AKSI_RAHASIA = {"gag", "hostage", "guard", "peek"}


# Pindah pilihan malam: batal lalu pilih ulang, dalam lock pemanggil. Bila pilihan baru ditolak engine, pilihan lama
# kembali utuh beserta urutannya, dan penolakan diteruskan ke pemanggil.
def pindahkan_aksi_malam(match, nama, kemampuan, target):
    sebelum = dict(match.actions)
    match.cancel_action(nama)
    try:
        match.act(nama, kemampuan, target)
    except ValueError:
        match.actions = sebelum
        raise


# Pindah suara saat waktu tambahan. Pemanggil memegang kunci room. Bila suara baru ditolak, suara lama dikembalikan,
# supaya bot tidak kehilangan suaranya.
def pindahkan_vote(match, nama, target):
    lama = match.votes.get(nama)
    match.cancel_vote(nama)
    try:
        match.vote(nama, target)
    except ValueError:
        match.vote(nama, lama)
        raise


# Vote atau aksi rahasia keputusan bot ke engine; target keputusan berupa label dan diubah ke username. Dipakai room
# asli (RoomService.pilihan_bot) dan simulasi panel. Pemanggil memegang kunci. ValueError = ditolak engine.
# Alur: 1 vote: pindah suara atau vote baru -> 2 aksi rahasia: pindah pilihan atau aksi baru -> 3 lainnya: tidak ada
def terapkan_pilihan_bot(match, nama, keputusan):
    if keputusan["action"] == "vote":
        if keputusan.get("pindah"):
            pindahkan_vote(match, nama, match.username(keputusan["target"]))
        else:
            match.vote(nama, match.username(keputusan["target"]))
    elif keputusan["action"] in AKSI_RAHASIA:
        aksi = keputusan["action"]
        target = match.username(keputusan["target"])
        if keputusan.get("pindah"):
            pindahkan_aksi_malam(match, nama, aksi, target)
        else:
            match.act(nama, aksi, target)


class RoomBelumTersimpan(RuntimeError):
    """Ruangan baru gagal dicatat di arsip, jadi tidak jadi dibuat."""


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
            profil_tersimpan = {
                baris.username: (baris.skin_id, baris.display_name)
                for baris in auth_queries.account_profiles(database, daftar_username)
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
    # pertandingan itu. Room tanpa anggota manusia dibersihkan. Keluar ulang oleh peserta pertandingan yang sudah
    # keluar diabaikan selama room masih ada; selain itu (lobby, atau room sudah dihapus) ditolak lewat get.
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

    # Buat ruangan yang sudah tercatat di arsip. Gagal mencatat berarti ruangannya tidak jadi dibuat.
    def buat_room_terarsip(self, username, capacity=6):
        with self.lock:
            # Kode acak bisa sudah terpakai di arsip lama: buang room itu lalu coba kode lain.
            for _ in range(10):
                room = self.create(username, capacity=capacity)
                try:
                    if PersistenceService(room.code).archive_new_room(username):
                        return room
                except PersistenceError as error:
                    self.rooms.pop(room.code, None)
                    raise RoomBelumTersimpan("Ruangan gagal disimpan. Coba lagi.") from error
                self.rooms.pop(room.code, None)
            raise RoomBelumTersimpan("Kode ruangan belum tersedia. Coba lagi.")

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

    # Snapshot ruangan milik pengguna, termasuk lobby dan pertandingan selesai; None bila tidak ada.
    def snapshot_room_saat_ini(self, username):
        with self.lock:
            room = self.current(username)
            return self.snapshot(room) if room else None

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

    # SIAP: manusia menandai sudah membaca panduan. Tanda ini hanya ditampilkan sebagai jumlah yang setuju;
    # jadwal mulai ronde 1 tetap mengikuti waktu baca, kesiapan AI, dan hitung mundur (Match._hitung_waktu_mulai).
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

    # Keputusan bot masih berlaku bila room, pertandingan, dan fasenya sama dengan saat bot melihat, dan deadline belum
    # lewat. Berbeda dengan token fase pemain, tick tidak dipanggil di sini: jam permainan yang memajukan fase.
    # Dipanggil di dalam lock oleh pemanggilnya.
    def _keputusan_bot_berlaku(self, code, match, token):
        room = self.rooms.get(code)
        return bool(
            room
            and room.match is match
            and not match.winner
            and token == (match.id, match.round, match.phase)
            and time.time() < match.deadline
        )

    # Layar persiapan mengikuti progres pemuatan otak bot. Hasil False bila pertandingan sudah selesai.
    def progres_persiapan_ai(self, match, detail, progres):
        with self.lock:
            if match.winner:
                return False
            match.update_preparation(detail=detail, progress=progres)
            return True

    # Otak bot siap atau gagal dimuat: ronde 1 boleh mulai (bot tanpa otak memakai aksi cadangan engine).
    def ai_siap(self, match, detail):
        with self.lock:
            match.mark_ai_ready(detail=detail)

    # Bot melihat permainan: token fase, snapshot berlabel miliknya, dan id chat terakhir yang ia lihat. None bila bot
    # tidak bisa melangkah: room atau pertandingan berganti, permainan selesai, masih persiapan, atau bot tersingkir.
    def lihat_untuk_bot(self, code, match, nama):
        with self.lock:
            room = self.rooms.get(code)
            if (
                not room
                or room.match is not match
                or match.winner
                or match.phase == "preparing"
                or not match.players[nama].alive
            ):
                return None
            token = (match.id, match.round, match.phase)
            snapshot = snapshot_berlabel(match.snapshot(nama), match.labels)
            id_chat_terakhir = match.messages[-1]["id"] if match.messages else None
            # Huruf kecil di kartu bot untuk pemantauan: I terima input, L logika, O output.
            match.bot_tahap[nama] = "I"
            return token, snapshot, id_chat_terakhir

    # Tahap langkah bot di kartu pemantauan (I input, L logika, O output).
    def tandai_tahap_bot(self, match, nama, tahap):
        with self.lock:
            match.bot_tahap[nama] = tahap

    # Vote atau aksi rahasia keputusan bot diterapkan segera. Hasil: (masih berlaku, pesan penolakan engine atau None).
    # Alur: 1 fase sudah berganti: buang -> 2 tandai bot sudah memutuskan fase ini -> 3 terapkan ke engine
    #                                                                              \> 3.2 ditolak engine: kembalikan alasannya
    def pilihan_bot(self, code, match, token, nama, keputusan):
        with self.lock:
            if not self._keputusan_bot_berlaku(code, match, token):
                return False, None
            # Otak sudah memutuskan fase ini: tunggu/abstain miliknya dihormati, bukan diganti aksi acak engine. Ditandai
            # setelah keputusan ada, sehingga langkah yang error/timeout sebelum pernah memutuskan apa pun tetap mendapat
            # aksi cadangan engine di akhir fase.
            match.npc_decisions.add((token[1], token[2], nama))
            try:
                terapkan_pilihan_bot(match, nama, keputusan)
            except ValueError as error:
                return True, str(error)
            return True, None

    # Chat tim bot: rahasia, jadi tanpa database, siaran, NLU, atau @traced (lihat team_chat). Penerima membacanya lewat
    # snapshot. Hasil: True bila pesan masuk kanal tim.
    def chat_tim_bot(self, code, match, token, nama, teks):
        with self.lock:
            if teks and self._keputusan_bot_berlaku(code, match, token) and match.can_team_chat(nama):
                match.add_team_message(nama, teks)
                return True
            return False

    # Bot mulai menyusun kalimat: pemain melihat awan berpikir di kartunya selama kalimat disusun.
    def mulai_berpikir_bot(self, match, nama):
        with self.lock:
            match.bot_berpikir.add(nama)

    # Chat publik bot disimpan lalu masuk pertandingan, hanya bila fase masih sama dan bot masih boleh bicara. Pesan yang
    # gagal disimpan tidak masuk pertandingan, jadi tidak pernah disiarkan. Hasil: (pesan, id pesan) atau (None, None).
    # Alur: 1 cek fase dan izin chat -> 2 simpan ke MySQL -> 3 masuk chat pertandingan -> 4 awan berpikir hilang
    #                                   \> 2.2 gagal simpan: catat di log, tidak dikirim
    def chat_bot(self, code, match, token, nama, teks):
        with self.lock:
            if not (teks and self._keputusan_bot_berlaku(code, match, token) and match.can_chat(nama)):
                return None, None
            try:
                id_pesan = PersistenceService(code).record_bot_message(
                    username=nama,
                    message=teks,
                    context={"match_id": match.id, "round_number": match.round,
                             "phase": match.phase},
                )  # fmt: skip
            except PersistenceError:
                logger.warning("Chat bot %s tidak tersimpan; tidak disiarkan.", nama)
                return None, None
            pesan = match.add_message(nama, teks)
            # Kalimat sudah tampil; awan berpikir hilang bersama pesan.
            match.bot_berpikir.discard(nama)
            return pesan, id_pesan

    # Langkah bot selesai, juga saat error: awan berpikir hilang. Tahap L menjadi O hanya bila langkah berhasil;
    # langkah yang gagal atau timeout tetap di L agar terlihat macet sampai langkah berikutnya.
    def selesai_langkah_bot(self, match, nama, gagal):
        with self.lock:
            match.bot_berpikir.discard(nama)
            if not gagal and match.bot_tahap.get(nama) == "L":
                match.bot_tahap[nama] = "O"

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

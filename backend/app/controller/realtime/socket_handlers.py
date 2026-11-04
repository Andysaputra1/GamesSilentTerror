"""
Menerima event Socket.IO dari browser pemain, lalu mengirim hasilnya ke room.

Alurnya
1. main.py memanggil register_socket_handlers (buat controller, daftarkan event)
2. connect: Cek token login dan room, catat socket ini milik siapa, masuk kanal room
3. send_chat: Cek pesan dan identitas, cek boleh chat atau tidak, simpan ke MySQL, kirim ke room, IndoBERT membaca pesan
4. disconnect: Hapus catatan socket (keanggotaan lobby dan data MySQL tetap)

Chat bot tidak lewat send_chat. Bot hanya memakai emit_room untuk mengirim pesannya ke room.
"""

from __future__ import annotations

import logging
from time import perf_counter
from typing import Any

import socketio
from app.module.room_service import room_service
from app.module.checker_service import checker_service
from app.module.activity_service import activity
from app.module.ai_diagnostics import measure
from app.module.npc_service import catat_nlu

from app.module.auth_service import (
    AuthenticationPersistenceError,
    SessionValidationError,
    auth_service,
)
from app.module.persistence_service import PersistenceError, PersistenceService

logger = logging.getLogger("shadow_heist.socket")


class SocketGameController:
    """Chat per ruangan; engine di memori, pesan dicatat ke MySQL. `sid` = ID koneksi Socket.IO."""

    # CONSTRUCTOR: simpan dependensi dan pemetaan socket → akun, ruangan, dan token login.
    def __init__(self, sio: socketio.AsyncServer) -> None:
        self.sio = sio
        self.socket_players: dict[str, str] = {}
        self.socket_rooms: dict[str, str] = {}
        self.socket_tokens: dict[str, str] = {}

    async def emit_room(self, event, data, *, to):
        """Cabut penerima lama sebelum broadcast, termasuk socket pasif setelah logout/leave."""
        for sid, kode_room in list(self.socket_rooms.items()):
            if kode_room != to:
                continue
            username = self.socket_players.get(sid)
            try:
                room_service.get(kode_room, username)
                if sid in self.socket_tokens:
                    akun = auth_service.user_for_token(self.socket_tokens[sid])
                    if akun.username != username:
                        raise ValueError("Identitas sesi berubah.")
            except (ValueError, SessionValidationError, AuthenticationPersistenceError):
                await self.sio.leave_room(sid, kode_room)
        await self.sio.emit(event, data, to=to)

    # Cocokkan identitas dengan sesi login socket dan pastikan masih anggota ruangan. Hasil: kode ruangan.
    def _verifikasi_socket(self, sid: str, username: str) -> str:
        username_sesi = self.socket_players.get(sid)
        username_dikirim = username.strip()
        if username_sesi is None:
            raise ValueError("Login diperlukan sebelum masuk ke game.")
        if username_dikirim != username_sesi:
            raise ValueError("Identitas pemain tidak sesuai dengan sesi login.")

        # Token handshake diperiksa lagi supaya logout/expiry mencabut akses chat.
        if sid in self.socket_tokens:
            try:
                akun = auth_service.user_for_token(self.socket_tokens[sid])
                if akun.username != username_sesi:
                    raise ValueError("Sesi login berubah. Silakan sambungkan ulang.")
            except (SessionValidationError, AuthenticationPersistenceError) as error:
                raise ValueError("Sesi login berakhir. Silakan login ulang.") from error

        kode_room = self.socket_rooms[sid]
        room_service.get(kode_room, username_sesi)
        return kode_room

    # EVENT CONNECT: periksa token login dan akses ruangan sebelum mencatat identitas socket.
    async def connect(self, sid: str, environ: dict[str, Any], auth: Any = None) -> None:
        token = str(auth.get("token", "")) if isinstance(auth, dict) else ""
        try:
            akun = auth_service.user_for_token(token)
        except (SessionValidationError, AuthenticationPersistenceError) as error:
            raise socketio.exceptions.ConnectionRefusedError("Login diperlukan.") from error
        try:
            kode_room = str(auth.get("room_code", ""))
            room_service.get(kode_room, akun.username)
        except (SessionValidationError, AuthenticationPersistenceError, ValueError) as error:
            logger.info("Koneksi Socket ditolak untuk %s: %s", sid, error)
            raise socketio.exceptions.ConnectionRefusedError("Ruangan tidak valid.") from error

        self.socket_players[sid] = akun.username
        self.socket_tokens[sid] = token
        self.socket_rooms[sid] = kode_room.strip().upper()
        await self.sio.enter_room(sid, self.socket_rooms[sid])
        logger.info("Pemain terkoneksi ke Socket: %s", sid)
        await self.sio.emit(
            "server_ready",
            {"message": f"Python game server siap, {akun.display_name}."},
            to=sid,
        )

    # EVENT DISCONNECT: hapus pemetaan socket yang keluar; tidak menghapus keanggotaan lobby atau data MySQL.
    async def disconnect(self, sid: str) -> None:
        self.socket_players.pop(sid, None)
        self.socket_rooms.pop(sid, None)
        self.socket_tokens.pop(sid, None)
        logger.info("Pemain keluar dari Socket: %s", sid)

    # Validasi sesi dan hak chat, simpan pesan, lalu broadcast. Setelah itu IndoBERT membaca pesan sekali
    # (tahap 5) untuk checker dan riwayat chat; hasilnya masuk memo NLU sehingga bot memakainya di langkah
    # NPCService berikutnya tanpa menghitung ulang. Handler ini tidak membalas pesan.
    async def _send_chat(self, sid: str, data: dict[str, Any], wadah_jejak) -> None:
        # TAHAP 1: terima event send_chat; validasi isi pesan dan identitas sesi.
        try:
            if not isinstance(data, dict) or not isinstance(data.get("message"), str):
                raise ValueError("Format pesan tidak valid.")
            pengirim = str(data.get("username", "")).strip()
            pesan = str(data.get("message", "")).strip()
            if not pesan or len(pesan) > 1000:
                raise ValueError("Pesan chat harus berisi 1–1000 karakter.")
            # Socket sudah masuk kanal ruangan saat connect; pemain dicatat di transaksi pesan (tahap 3).
            self._verifikasi_socket(sid, pengirim)
        except ValueError as error:
            await self.sio.emit("system_alert", {"msg": str(error)}, to=sid)
            return

        kode_room = self.socket_rooms[sid]
        room = room_service.get(kode_room, pengirim)
        # TAHAP 2: engine mengotorisasi pesan sebelum disimpan atau ditampilkan.
        chat_terkunci = False
        with room_service.lock:
            pertandingan = room.match
            if pertandingan:
                # tick dulu: jam baru berdetak tiap 0,5 detik, jadi fase bisa belum terbarui.
                pertandingan.tick()
                chat_terkunci = not pertandingan.can_chat(pengirim)
                # Penanda fase ini; dibandingkan lagi di tahap 3 untuk tahu fase sudah berubah atau belum.
                token_fase = (pertandingan.id, pertandingan.round, pertandingan.phase)
            else:
                token_fase = None
        if chat_terkunci:
            activity.record(
                kode_room,
                "Match.can_chat",
                {"username": pengirim},
                status="rejected",
                result={"allowed": False},
            )
            await self.sio.emit(
                "system_alert", {"msg": "Chat terkunci untukmu pada fase ini."}, to=sid
            )
            return
        # Jejak debugging pesan (tahap dan durasi) untuk checker di panel.
        jejak = checker_service.begin(kode_room, pengirim, pesan)
        wadah_jejak["trace"] = jejak
        jejak["match_id"] = token_fase[0] if token_fase else None
        activity.record(
            kode_room,
            "SocketGameController.send_chat",
            {"username": pengirim, "message": pesan},
            status="received",
            call_id=jejak["id"],
        )

        konteks = (
            {"match_id": token_fase[0], "round_number": token_fase[1], "phase": token_fase[2]}
            if token_fase
            else {"phase": "lobby"}
        )
        pesan_diterima = {"sender": pengirim, "message": pesan}
        try:
            # TAHAP 3: simpan pesan. Aksi/skip HTTP bisa berjalan bersamaan, jadi periksa ulang dan
            # commit di lock yang sama supaya Gag atau fase baru tidak diterobos.
            with measure(jejak, "persistence_ms"), room_service.lock:
                room_terkini = room_service.get(kode_room, pengirim)
                if room_terkini is not room or room_terkini.match is not pertandingan:
                    raise ValueError("Ruangan sudah berubah. Kirim ulang pada fase yang sesuai.")
                if pertandingan:
                    pertandingan.tick()
                    if token_fase != (
                        pertandingan.id,
                        pertandingan.round,
                        pertandingan.phase,
                    ) or not pertandingan.can_chat(pengirim):
                        raise ValueError(
                            "Chat terkunci atau fase sudah berubah. Pesan tidak dikirim."
                        )
                jejak["message_id"] = PersistenceService(kode_room).record_player_message(
                    username=pengirim,
                    message=pesan,
                    status="active",  # Gag/Hostage ditegakkan Match.can_chat, bukan status arsip
                    context=konteks,
                )
                if pertandingan:
                    pesan_diterima = pertandingan.add_message(pengirim, pesan)
            activity.record(
                kode_room,
                "PersistenceService.record_player_message",
                {"username": pengirim},
                result={"message_id": jejak["message_id"]},
                call_id=jejak["id"],
            )
        except ValueError as error:
            jejak.update(stage="discarded_state_changed", error=str(error))
            await self.sio.emit("system_alert", {"msg": str(error)}, to=sid)
            return
        except PersistenceError as error:
            jejak.update(stage="persistence_error", error=str(error))
            await self.sio.emit("system_alert", {"msg": str(error)}, to=sid)
            return
        # TAHAP 4: kirim pesan ke semua anggota ruangan.
        with measure(jejak, "broadcast_ms"):
            await self.emit_room("receive_chat", pesan_diterima, to=kode_room)
        jejak["stage"] = "delivered"
        # TAHAP 5: catat bacaan IndoBERT (intent, target) untuk checker dan riwayat chat panel.
        if pertandingan:
            with measure(jejak, "nlu_ms"):
                jejak["nlu"] = await catat_nlu(
                    pertandingan, pengirim, pesan, jejak["message_id"], room_code=kode_room
                )

    # EVENT CHAT ASYNC: validasi pesan, catat checker dan MySQL, lalu kirim hanya ke ruangan terkait.
    async def send_chat(self, sid: str, data: dict[str, Any]) -> None:
        waktu_mulai = perf_counter()
        # Wadah agar jejak tetap terbaca di finally walaupun _send_chat berhenti di tengah jalan.
        wadah_jejak = {}
        try:
            await self._send_chat(sid, data, wadah_jejak)
        finally:
            jejak = wadah_jejak.get("trace")
            if jejak:
                jejak["duration_ms"] = round((perf_counter() - waktu_mulai) * 1000, 2)
                try:
                    PersistenceService(jejak["room_code"]).record_trace(jejak)
                except PersistenceError:
                    logger.error(
                        "Checker archive could not be saved for room %s", jejak["room_code"]
                    )


# FUNCTION WIRING: buat controller dan daftarkan method-nya sebagai handler event Socket.IO.
def register_socket_handlers(sio: socketio.AsyncServer) -> SocketGameController:
    pengendali = SocketGameController(sio)
    sio.on("connect", pengendali.connect)
    sio.on("disconnect", pengendali.disconnect)
    sio.on("send_chat", pengendali.send_chat)
    return pengendali

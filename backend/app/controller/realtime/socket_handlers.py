"""
Menerima event Socket.IO dari browser pemain, lalu mengirim hasilnya ke room.

Alurnya
1. main.py membuat SocketGameController dan mendaftarkan event connect, disconnect, send_chat
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

    # CONSTRUCTOR: simpan dependensi dan catatan tiap socket: akun, ruangan, dan token login.
    def __init__(self, sio: socketio.AsyncServer) -> None:
        self.sio = sio
        self.sockets: dict[str, dict[str, str]] = {}

    # Cocokkan identitas dengan sesi login socket dan pastikan masih anggota ruangan. Hasil: kode ruangan.
    def _verifikasi_socket(self, sid: str, username: str) -> str:
        socket = self.sockets.get(sid)
        if socket is None:
            raise ValueError("Login diperlukan sebelum masuk ke game.")
        if username != socket["username"]:
            raise ValueError("Identitas pemain tidak sesuai dengan sesi login.")

        # Token handshake diperiksa lagi supaya logout/expiry mencabut akses chat.
        if "token" in socket:
            try:
                akun = auth_service.user_for_token(socket["token"])
                if akun.username != socket["username"]:
                    raise ValueError("Sesi login berubah. Silakan sambungkan ulang.")
            except (SessionValidationError, AuthenticationPersistenceError) as error:
                raise ValueError("Sesi login berakhir. Silakan login ulang.") from error

        room_service.get(socket["room"], socket["username"])
        return socket["room"]

    async def emit_room(self, event, data, *, to):
        """Cabut penerima lama sebelum broadcast, termasuk socket pasif setelah logout/leave."""
        for sid, socket in list(self.sockets.items()):
            if socket["room"] != to:
                continue
            try:
                self._verifikasi_socket(sid, socket["username"])
            except ValueError:
                await self.sio.leave_room(sid, to)
        await self.sio.emit(event, data, to=to)

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
        except ValueError as error:
            logger.info("Koneksi Socket ditolak untuk %s: %s", sid, error)
            raise socketio.exceptions.ConnectionRefusedError("Ruangan tidak valid.") from error

        kode_room = kode_room.strip().upper()
        self.sockets[sid] = {"username": akun.username, "token": token, "room": kode_room}
        await self.sio.enter_room(sid, kode_room)
        logger.info("Pemain terkoneksi ke Socket: %s", sid)

    # EVENT DISCONNECT: hapus pemetaan socket yang keluar; tidak menghapus keanggotaan lobby atau data MySQL.
    async def disconnect(self, sid: str) -> None:
        self.sockets.pop(sid, None)
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
            kode_room = self._verifikasi_socket(sid, pengirim)
        except ValueError as error:
            await self.sio.emit("system_alert", {"msg": str(error)}, to=sid)
            return

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

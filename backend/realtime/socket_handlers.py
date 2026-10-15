"""Socket.IO event controllers and their short-lived game state."""

from __future__ import annotations

import logging
from time import perf_counter
from typing import Any

import socketio
from services.room_service import room_service
from services.checker_service import checker_service
from services.activity_service import activity
from services.ai_diagnostics import measure

from services.auth_service import (
    AuthenticationPersistenceError,
    SessionValidationError,
    auth_service,
)
from services.persistence_service import PersistenceError, PersistenceService

logger = logging.getLogger("shadow_heist.socket")

PlayerState = dict[str, int | float | str]


class SocketGameController:
    """Chat room-scoped; engine di memori, pesan dicatat ke MySQL."""

    # CONSTRUCTOR: simpan dependensi dan siapkan state socket serta pemain per ruangan.
    def __init__(
        self,
        sio: socketio.AsyncServer,
        persistence: PersistenceService,
    ) -> None:
        self.sio = sio
        self.persistence = persistence
        self.game_state: dict[str, Any] = {"phase": "day", "players": {}}
        self.socket_players: dict[str, str] = {}
        self.socket_rooms: dict[str, str] = {}
        self.socket_tokens: dict[str, str] = {}
        self.room_players = {}

    async def emit_room(self, event, data, *, to):
        """Cabut penerima lama sebelum broadcast, termasuk socket pasif setelah logout/leave."""
        for sid, code in list(self.socket_rooms.items()):
            if code != to:
                continue
            username = self.socket_players.get(sid)
            try:
                room_service.get(code, username)
                if sid in self.socket_tokens:
                    user = auth_service.user_for_token(self.socket_tokens[sid])
                    if user.username != username:
                        raise ValueError("Identitas sesi berubah.")
            except (ValueError, SessionValidationError, AuthenticationPersistenceError):
                await self.sio.leave_room(sid, code)
        await self.sio.emit(event, data, to=to)

    # HELPER STATE: ambil/buat state pemain dalam satu ruangan setelah memastikan username tidak kosong.
    def get_player(self, username: str, room_code: str) -> PlayerState:
        normalized_name = username.strip()
        if not normalized_name:
            raise ValueError("Username pemain wajib diisi.")

        players: dict[str, PlayerState] = self.room_players.setdefault(room_code, {})
        if normalized_name not in players:
            players[normalized_name] = {
                "role": "civilian",
                "status": "active",
            }
        return players[normalized_name]

    # METHOD ASYNC: cocokkan identitas sesi, cek keanggotaan, pastikan data pemain, lalu gabungkan socket ke kanal ruangan.
    async def register_player_socket(self, sid: str, username: str) -> PlayerState:
        authenticated_username = self.socket_players.get(sid)
        normalized_username = username.strip()
        if authenticated_username is None:
            raise ValueError("Login diperlukan sebelum masuk ke game.")
        if normalized_username != authenticated_username:
            raise ValueError("Identitas pemain tidak sesuai dengan sesi login.")

        # Token handshake diperiksa lagi supaya logout/expiry mencabut akses chat.
        if sid in self.socket_tokens:
            try:
                user = auth_service.user_for_token(self.socket_tokens[sid])
                if user.username != authenticated_username:
                    raise ValueError("Sesi login berubah. Silakan sambungkan ulang.")
            except (SessionValidationError, AuthenticationPersistenceError) as error:
                raise ValueError("Sesi login berakhir. Silakan login ulang.") from error

        code = self.socket_rooms[sid]
        room_service.get(code, authenticated_username)
        player = self.get_player(authenticated_username, code)
        PersistenceService(code).ensure_player(authenticated_username)
        await self.sio.enter_room(sid, code)
        await self.emit_room(
            "room_state",
            room_service.snapshot(room_service.get(code, authenticated_username)),
            to=code,
        )
        return player

    # EVENT CONNECT: periksa token login dan akses ruangan sebelum mencatat identitas socket.
    async def connect(self, sid: str, environ: dict[str, Any], auth: Any = None) -> None:
        token = str(auth.get("token", "")) if isinstance(auth, dict) else ""
        try:
            user = auth_service.user_for_token(token)
        except (SessionValidationError, AuthenticationPersistenceError) as error:
            raise socketio.exceptions.ConnectionRefusedError("Login diperlukan.") from error
        try:
            code = str(auth.get("room_code", ""))
            room_service.get(code, user.username)
        except (SessionValidationError, AuthenticationPersistenceError, ValueError) as error:
            logger.info("Koneksi Socket ditolak untuk %s: %s", sid, error)
            raise socketio.exceptions.ConnectionRefusedError("Ruangan tidak valid.") from error

        self.socket_players[sid] = user.username
        self.socket_tokens[sid] = token
        self.socket_rooms[sid] = code.strip().upper()
        await self.sio.enter_room(sid, self.socket_rooms[sid])
        logger.info("Pemain terkoneksi ke Socket: %s", sid)
        await self.sio.emit(
            "server_ready",
            {"message": f"Python game server siap, {user.display_name}."},
            to=sid,
        )

    # EVENT DISCONNECT: hapus pemetaan socket yang keluar; tidak menghapus keanggotaan lobby atau data MySQL.
    async def disconnect(self, sid: str) -> None:
        self.socket_players.pop(sid, None)
        self.socket_rooms.pop(sid, None)
        self.socket_tokens.pop(sid, None)
        logger.info("Pemain keluar dari Socket: %s", sid)

    # EVENT REGISTER: daftarkan socket pemain melalui helper dan kirim pemberitahuan jika validasi/penyimpanan gagal.
    async def register_player(self, sid: str, data: dict[str, Any]) -> None:
        try:
            if not isinstance(data, dict):
                raise ValueError("Format registrasi tidak valid.")
            await self.register_player_socket(sid, str(data.get("username", "")))
        except (ValueError, PersistenceError) as error:
            await self.sio.emit("system_alert", {"msg": str(error)}, to=sid)

    # EVENT CHAT ASYNC: validasi pesan, catat checker dan MySQL, lalu kirim hanya ke ruangan terkait.
    async def send_chat(self, sid: str, data: dict[str, Any]) -> None:
        started = perf_counter()
        holder = {}
        try:
            await self._send_chat(sid, data, holder)
        finally:
            trace = holder.get("trace")
            if trace:
                trace["duration_ms"] = round((perf_counter() - started) * 1000, 2)
                try:
                    PersistenceService(trace["room_code"]).record_trace(trace)
                except PersistenceError:
                    logger.error(
                        "Checker archive could not be saved for room %s", trace["room_code"]
                    )

    # Validasi sesi dan hak chat, simpan pesan, lalu broadcast. Bot membaca chat ini sendiri di langkah
    # NPCService berikutnya (IndoBERT), jadi handler ini tidak menganalisis atau membalas pesan.
    async def _send_chat(self, sid: str, data: dict[str, Any], holder) -> None:
        # TAHAP 1: terima event send_chat; validasi isi pesan dan identitas sesi.
        try:
            if not isinstance(data, dict) or not isinstance(data.get("message"), str):
                raise ValueError("Format pesan tidak valid.")
            sender = str(data.get("username", "")).strip()
            message = str(data.get("message", "")).strip()
            if not message or len(message) > 1000:
                raise ValueError("Pesan chat harus berisi 1–1000 karakter.")
            player = await self.register_player_socket(sid, sender)
        except (ValueError, PersistenceError) as error:
            await self.sio.emit("system_alert", {"msg": str(error)}, to=sid)
            return

        if player["status"] in {"hostage", "gagged"}:
            await self.sio.emit("system_alert", {"msg": "Suara Anda hilang..."}, to=sid)
            return

        code = self.socket_rooms[sid]
        room = room_service.get(code, sender)
        # TAHAP 2: engine mengotorisasi pesan sebelum disimpan atau ditampilkan.
        blocked = False
        with room_service.lock:
            match = room.match
            if match:
                match.tick()
                blocked = not match.can_chat(sender)
                phase_token = (match.id, match.round, match.phase)
            else:
                phase_token = None
        if blocked:
            activity.record(
                code,
                "Match.can_chat",
                {"username": sender},
                status="rejected",
                result={"allowed": False},
            )
            await self.sio.emit(
                "system_alert", {"msg": "Chat terkunci untukmu pada fase ini."}, to=sid
            )
            return
        trace = checker_service.begin(code, sender, message)
        holder["trace"] = trace
        trace["match_id"] = phase_token[0] if phase_token else None
        activity.record(
            code,
            "SocketGameController.send_chat",
            {"username": sender, "message": message},
            status="received",
            call_id=trace["id"],
        )

        context = (
            {"match_id": phase_token[0], "round_number": phase_token[1], "phase": phase_token[2]}
            if phase_token
            else {"phase": "lobby"}
        )
        accepted = {"sender": sender, "message": message}
        try:
            # TAHAP 3: simpan pesan. Aksi/skip HTTP bisa berjalan bersamaan, jadi periksa ulang dan
            # commit di lock yang sama supaya Gag atau fase baru tidak diterobos.
            with measure(trace, "persistence_ms"), room_service.lock:
                current_room = room_service.get(code, sender)
                if current_room is not room or current_room.match is not match:
                    raise ValueError("Ruangan sudah berubah. Kirim ulang pada fase yang sesuai.")
                if match:
                    match.tick()
                    if phase_token != (match.id, match.round, match.phase) or not match.can_chat(
                        sender
                    ):
                        raise ValueError(
                            "Chat terkunci atau fase sudah berubah. Pesan tidak dikirim."
                        )
                trace["message_id"] = PersistenceService(code).record_player_message(
                    username=sender,
                    message=message,
                    status=str(player["status"]),
                    context=context,
                )
                if match:
                    accepted = match.add_message(sender, message)
            activity.record(
                code,
                "PersistenceService.record_player_message",
                {"username": sender},
                result={"message_id": trace["message_id"]},
                call_id=trace["id"],
            )
        except ValueError as error:
            trace.update(stage="discarded_state_changed", error=str(error))
            await self.sio.emit("system_alert", {"msg": str(error)}, to=sid)
            return
        except PersistenceError as error:
            trace.update(stage="persistence_error", error=str(error))
            await self.sio.emit("system_alert", {"msg": str(error)}, to=sid)
            return
        # TAHAP 4: kirim pesan ke semua anggota ruangan.
        with measure(trace, "broadcast_ms"):
            await self.emit_room("receive_chat", accepted, to=code)
        trace["stage"] = "delivered"

    # KOMPATIBILITAS: aksi memakai endpoint terautentikasi dengan token fase, bukan event lama.
    async def use_gag_order(self, sid: str, data: dict[str, Any]) -> None:
        await self.sio.emit("system_alert", {"msg": "Gunakan tombol aksi di halaman game."}, to=sid)

    # KOMPATIBILITAS: client tidak boleh memaksa server mengubah fase.
    async def start_tribunal(self, sid: str) -> None:
        await self.sio.emit(
            "system_alert", {"msg": "Fase berganti otomatis mengikuti timer server."}, to=sid
        )


# FUNCTION WIRING: buat controller dan daftarkan method-nya sebagai handler event Socket.IO.
def register_socket_handlers(
    sio: socketio.AsyncServer,
    persistence: PersistenceService,
) -> SocketGameController:
    """Attach event handlers and return the controller for application wiring."""
    controller = SocketGameController(sio, persistence)
    sio.on("connect", controller.connect)
    sio.on("disconnect", controller.disconnect)
    sio.on("register_player", controller.register_player)
    sio.on("send_chat", controller.send_chat)
    sio.on("use_gag_order", controller.use_gag_order)
    sio.on("start_tribunal", controller.start_tribunal)
    return controller

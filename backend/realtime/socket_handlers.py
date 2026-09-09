"""Socket.IO event controllers and their short-lived game state."""

from __future__ import annotations

import logging
from typing import Any

import socketio
from services.room_service import room_service
from services.checker_service import checker_service

from services.analysis_service import AnalysisService, IntentModelNotReadyError
from services.auth_service import (
    AuthenticationPersistenceError,
    SessionValidationError,
    auth_service,
)
from services.fuzzy_service import calculate_suspicion, status_for_score
from services.persistence_service import PersistenceError, PersistenceService


logger = logging.getLogger("shadow_heist.socket")

PlayerState = dict[str, int | float | str]


class SocketGameController:
    """Keeps live state in memory and mirrors every mutation into MySQL."""

    # CONSTRUCTOR: simpan dependensi dan siapkan state socket, pemain, analisis per ruangan, serta request AI yang berjalan.
    def __init__(
        self,
        sio: socketio.AsyncServer,
        analysis: AnalysisService,
        persistence: PersistenceService,
    ) -> None:
        self.sio = sio
        self.analysis = analysis
        self.persistence = persistence
        self.game_state: dict[str, Any] = {"phase": "day", "players": {}}
        self.socket_players: dict[str, str] = {}
        self.socket_rooms: dict[str, str] = {}
        self.room_players = {}
        self.room_analysis = {}
        self.ai_pending: set[str] = set()


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
                "sus_score": 0.0,
                "aggressiveness": 0,
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

        code = self.socket_rooms[sid]
        room_service.get(code, authenticated_username)
        player = self.get_player(authenticated_username, code)
        PersistenceService(code).ensure_player(authenticated_username)
        await self.sio.enter_room(sid, code)
        await self.sio.emit("room_state", room_service.snapshot(room_service.get(code, authenticated_username)), to=code)
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
        self.socket_rooms[sid] = code.strip().upper()
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
        logger.info("Pemain keluar dari Socket: %s", sid)

    # EVENT REGISTER: daftarkan socket pemain melalui helper dan kirim pemberitahuan jika validasi/penyimpanan gagal.
    async def register_player(self, sid: str, data: dict[str, Any]) -> None:
        try:
            await self.register_player_socket(sid, str(data.get("username", "")))
        except (ValueError, PersistenceError) as error:
            await self.sio.emit("system_alert", {"msg": str(error)}, to=sid)

    # EVENT CHAT ASYNC: validasi pesan, jalankan SVM/fuzzy/LLM, catat checker dan MySQL, lalu kirim balasan hanya ke ruangan terkait.
    async def send_chat(self, sid: str, data: dict[str, Any]) -> None:
        if sid in self.ai_pending:
            await self.sio.emit("system_alert", {"msg": "NOX masih memproses pesan sebelumnya. Tunggu sebentar."}, to=sid)
            return
        # TAHAP 1: terima event send_chat; validasi isi pesan dan identitas sesi.
        try:
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
        trace = checker_service.begin(code, sender, message)
        trace["aggressiveness_before"] = int(player["aggressiveness"])
        if code not in self.room_analysis:
            local_analysis = AnalysisService()
            local_analysis._model = self.analysis._model
            self.room_analysis[code] = local_analysis
        analysis = self.room_analysis[code]
        intent: str | None = None
        host_response: str | None = None
        try:
            # TAHAP 2: pesan diprediksi oleh SVM menjadi label intent.
            intent = analysis.predict_intent(message)
            trace["intent"] = intent
            trace["intent_weight"] = analysis.aggressiveness_for_intent(intent)
            # TAHAP 3: tambahkan bobot intent ke agresivitas pemain, maksimal 100.
            player["aggressiveness"] = min(
                100,
                int(player["aggressiveness"]) + analysis.aggressiveness_for_intent(intent),
            )
        except IntentModelNotReadyError:
            # Messages can still be relayed if the optional classifier is loading.
            pass

        # TAHAP 4: hitung fuzzy. Persentase diam masih tetap 20%, belum diukur.
        suspicion_score = calculate_suspicion(int(player["aggressiveness"]), 20)
        player["sus_score"] = round(suspicion_score, 2)
        trace.update(aggressiveness=int(player["aggressiveness"]),
                     suspicion_score=player["sus_score"], suspicion_status=status_for_score(suspicion_score),
                     stage="analyzed")

        # TAHAP 5: kirim echo pesan pemain ke browser sebelum menunggu LLM.
        await self.sio.emit("receive_chat", {"sender": sender, "message": message}, to=code)

        if not room.bot_enabled:
            trace["stage"] = "skipped_no_bot"
            await self.sio.emit("system_alert", {"msg": "NOX belum ditambahkan. Kembali ke lobby dan pilih + Bot untuk mendapat balasan AI."}, to=sid)
        elif intent is None:
            trace["stage"] = "skipped_no_svm"
            await self.sio.emit("system_alert", {"msg": "NOX belum bisa menjawab karena model SVM belum siap. Periksa model backend lalu mulai ulang backend."}, to=sid)

        # TAHAP 6-7: susun prompt dan panggil provider LLM terpilih.
        # Jika SVM belum siap (intent=None), jalur ini belum memanggil LLM.
        if intent is not None and room.bot_enabled:
            self.ai_pending.add(sid)
            await self.sio.emit("ai_status", {"pending": True}, to=sid)
            try:
                host_response = await analysis.create_host_response(
                    player_name=sender,
                    message=message,
                    intent=intent,
                    aggressiveness=int(player["aggressiveness"]),
                    suspicion_score=suspicion_score,
                    suspicion_status=status_for_score(suspicion_score),
                    trace=trace,
                )
                trace["output"] = host_response
                trace["stage"] = "llm_error" if trace["llm_error"] else "llm_complete"
            except Exception:
                trace.update(stage="error", error="Respons AI gagal diproses")
                logger.exception("Gagal memproses respons AI di ruangan %s", code)
                await self.sio.emit("system_alert", {"msg": "Respons AI gagal diproses. Coba kirim ulang; jika berulang, periksa log backend."}, to=sid)
            finally:
                self.ai_pending.discard(sid)
                await self.sio.emit("ai_status", {"pending": False}, to=sid)
        try:
            # TAHAP 8: simpan pesan, hasil analisis, dan respons LLM dalam MySQL.
            trace["message_id"] = PersistenceService(code).record_player_message(
                username=sender,
                message=message,
                intent=intent,
                aggressiveness=int(player["aggressiveness"]),
                suspicion_score=suspicion_score,
                status=str(player["status"]),
                llm_response=host_response,
            )
        except PersistenceError as error:
            trace.update(stage="persistence_error", error=str(error))
            await self.sio.emit("system_alert", {"msg": str(error)}, to=sid)
            return
        # TAHAP 9: kirim receive_chat dengan sender NOX; browser menampilkan balasan.
        # Jika penyimpanan gagal, kode di atas mengirim system_alert lalu berhenti.
        if host_response is not None:
            await self.sio.emit(
                "receive_chat", {"sender": "NOX", "message": host_response}, to=code
            )
            if not trace["llm_error"]:
                trace["stage"] = "delivered"

    # EVENT PLACEHOLDER: beri tahu bahwa aksi role belum tersedia; tidak membungkam pemain.
    async def use_gag_order(self, sid: str, data: dict[str, Any]) -> None:
        await self.sio.emit("system_alert", {"msg": "Aksi peran belum tersedia."}, to=sid)

    # EVENT PLACEHOLDER: beri tahu bahwa pergantian fase belum tersedia; tidak menjalankan voting.
    async def start_tribunal(self, sid: str) -> None:
        await self.sio.emit("system_alert", {"msg": "Pergantian fase belum tersedia."}, to=sid)


# FUNCTION WIRING: buat controller dan daftarkan method-nya sebagai handler event Socket.IO.
def register_socket_handlers(
    sio: socketio.AsyncServer,
    analysis: AnalysisService,
    persistence: PersistenceService,
) -> SocketGameController:
    """Attach event handlers and return the controller for application wiring."""
    controller = SocketGameController(sio, analysis, persistence)
    sio.on("connect", controller.connect)
    sio.on("disconnect", controller.disconnect)
    sio.on("register_player", controller.register_player)
    sio.on("send_chat", controller.send_chat)
    sio.on("use_gag_order", controller.use_gag_order)
    sio.on("start_tribunal", controller.start_tribunal)
    return controller

"""Socket.IO event controllers and their short-lived game state."""

from __future__ import annotations

import logging
from typing import Any

import socketio
from services.room_service import room_service
from services.checker_service import checker_service
from services.activity_service import activity

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
    """Chat room-scoped; engine di memori, pesan/analisis dicatat ke MySQL."""

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
        self.socket_tokens: dict[str, str] = {}
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
        await self.sio.emit(
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

    # EVENT CHAT ASYNC: validasi pesan, jalankan SVM/fuzzy/LLM, catat checker dan MySQL, lalu kirim balasan hanya ke ruangan terkait.
    async def send_chat(self, sid: str, data: dict[str, Any]) -> None:
        holder = {}
        try:
            await self._send_chat(sid, data, holder)
        finally:
            trace = holder.get("trace")
            if trace:
                try:
                    PersistenceService(trace["room_code"]).record_trace(trace)
                except PersistenceError:
                    logger.error(
                        "Checker archive could not be saved for room %s", trace["room_code"]
                    )

    # Validasi sesi dan hak chat, simpan pesan, lalu proses analisis serta balasan NOX.
    async def _send_chat(self, sid: str, data: dict[str, Any], holder) -> None:
        if sid in self.ai_pending:
            await self.sio.emit(
                "system_alert",
                {"msg": "NOX masih memproses pesan sebelumnya. Tunggu sebentar."},
                to=sid,
            )
            return
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
        # Engine mengotorisasi pesan sebelum ditampilkan atau dikirim ke AI.
        blocked = False
        with room_service.lock:
            match = room.match
            if match:
                match.tick()
                if not match.can_chat(sender):
                    blocked = True
                else:
                    accepted = {"sender": sender, "message": message}
                    phase_token = (match.id, match.round, match.phase)
                    candidates = [
                        p for p in match.players.values() if p.bot and match.can_chat(p.name)
                    ]
                    bot_player = match.rng.choice(candidates) if candidates else None
            else:
                accepted = {"sender": sender, "message": message}
                bot_player = None
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
        bot_name = bot_player.name if bot_player else "NOX"
        bot_role = bot_player.role if bot_player else "hitman"
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
            activity.record(
                code,
                "AnalysisService.predict_intent",
                {"message": message},
                result={"intent": intent},
                call_id=trace["id"],
            )
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
        activity.record(
            code,
            "calculate_suspicion",
            {"aggressiveness": int(player["aggressiveness"]), "silence_percentage": 20},
            result={"suspicion_score": player["sus_score"]},
            call_id=trace["id"],
        )
        trace.update(
            aggressiveness=int(player["aggressiveness"]),
            suspicion_score=player["sus_score"],
            suspicion_status=status_for_score(suspicion_score),
            stage="analyzed",
        )

        context = (
            {"match_id": phase_token[0], "round_number": phase_token[1], "phase": phase_token[2]}
            if phase_token
            else {"phase": "lobby"}
        )
        try:
            # Commit pesan sebelum echo atau menunggu provider AI.
            trace["message_id"] = PersistenceService(code).record_player_message(
                username=sender,
                message=message,
                intent=intent,
                aggressiveness=int(player["aggressiveness"]),
                suspicion_score=suspicion_score,
                status=str(player["status"]),
                llm_response=None,
                context=context,
            )
            activity.record(
                code,
                "PersistenceService.record_player_message",
                {"username": sender, "intent": intent},
                result={"message_id": trace["message_id"]},
                call_id=trace["id"],
            )
        except PersistenceError as error:
            trace.update(stage="persistence_error", error=str(error))
            await self.sio.emit("system_alert", {"msg": str(error)}, to=sid)
            return
        if match:
            with room_service.lock:
                accepted = match.add_message(sender, message)
        # TAHAP 5: kirim echo pesan pemain ke browser sebelum menunggu LLM.
        await self.sio.emit("receive_chat", accepted, to=code)

        # Pertandingan GDD memakai scheduler NPC independen; jangan gandakan reply lama per pesan manusia.
        if match and match.ai_controlled:
            trace["stage"] = "analyzed_for_npc_game"
            return

        if not room.bot_enabled:
            trace["stage"] = "skipped_no_bot"
            await self.sio.emit(
                "system_alert",
                {
                    "msg": "NOX belum ditambahkan. Kembali ke lobby dan pilih + Bot untuk mendapat balasan AI."
                },
                to=sid,
            )
        elif intent is None:
            trace["stage"] = "skipped_no_svm"
            await self.sio.emit(
                "system_alert",
                {
                    "msg": "NOX belum bisa menjawab karena model SVM belum siap. Periksa model backend lalu mulai ulang backend."
                },
                to=sid,
            )

        if intent is not None and match and room.bot_enabled and not bot_player:
            trace["stage"] = "skipped_no_eligible_bot"

        # TAHAP 6-7: susun prompt dan panggil provider LLM terpilih.
        # Jika SVM belum siap (intent=None), jalur ini belum memanggil LLM.
        if intent is not None and room.bot_enabled and (not match or bot_player):
            if match:
                with room_service.lock:
                    match.reserve_ai_reply()
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
                    bot_name=bot_name,
                    bot_role=bot_role,
                )
                trace["output"] = host_response
                trace["stage"] = "llm_error" if trace["llm_error"] else "llm_complete"
                activity.record(
                    code,
                    "AnalysisService._request_host_response",
                    {"provider": trace["provider"], "model": trace["model"]},
                    status=trace["stage"],
                    result={"output": host_response},
                    call_id=trace["id"],
                )
            except Exception:
                trace.update(stage="error", error="Respons AI gagal diproses")
                logger.exception("Gagal memproses respons AI di ruangan %s", code)
                await self.sio.emit(
                    "system_alert",
                    {
                        "msg": "Respons AI gagal diproses. Coba kirim ulang; jika berulang, periksa log backend."
                    },
                    to=sid,
                )
            finally:
                self.ai_pending.discard(sid)
                await self.sio.emit("ai_status", {"pending": False}, to=sid)
        # TAHAP 9: kirim receive_chat dengan identitas bot terpilih.
        # Jika penyimpanan gagal, kode di atas mengirim system_alert lalu berhenti.
        if host_response is not None:
            if trace["llm_error"]:
                await self.sio.emit(
                    "system_alert",
                    {"msg": "Layanan AI sedang tidak tersedia; permainan tetap berjalan."},
                    to=sid,
                )
                return
            # Jawaban lambat tidak boleh menerobos fase malam, Gag, Hostage, atau game over.
            with room_service.lock:
                if match:
                    match.tick()
                    if phase_token != (match.id, match.round, match.phase) or not match.can_chat(
                        bot_name
                    ):
                        trace["stage"] = "discarded_phase_changed"
                        activity.record(
                            code,
                            "Match.can_chat",
                            {"sender": bot_name},
                            status="discarded_phase_changed",
                            call_id=trace["id"],
                        )
                        return
                    try:
                        PersistenceService(code).record_bot_message(
                            username=bot_name,
                            message=host_response,
                            context=context,
                            reply_to_id=trace["message_id"],
                            intent=intent,
                            aggressiveness=int(player["aggressiveness"]),
                            suspicion_score=suspicion_score,
                        )
                    except PersistenceError as error:
                        trace.update(stage="persistence_error", error=str(error))
                        reply = None
                    else:
                        reply = match.add_message(bot_name, host_response)
                else:
                    try:
                        PersistenceService(code).record_bot_message(
                            username=bot_name,
                            message=host_response,
                            context=context,
                            reply_to_id=trace["message_id"],
                            intent=intent,
                            aggressiveness=int(player["aggressiveness"]),
                            suspicion_score=suspicion_score,
                        )
                    except PersistenceError as error:
                        trace.update(stage="persistence_error", error=str(error))
                        reply = None
                    else:
                        reply = {"sender": bot_name, "message": host_response}
            if reply is None:
                await self.sio.emit(
                    "system_alert", {"msg": "Balasan bot gagal disimpan. Coba lagi."}, to=sid
                )
                return
            await self.sio.emit("receive_chat", reply, to=code)
            if not trace["llm_error"]:
                trace["stage"] = "delivered"
                activity.record(
                    code,
                    "SocketGameController.receive_chat",
                    {"sender": bot_name},
                    result={"message": host_response},
                    status="delivered",
                    call_id=trace["id"],
                )

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

"""Socket.IO event controllers and their short-lived game state."""

from __future__ import annotations

import logging
from typing import Any

import socketio

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

    def get_player(self, username: str) -> PlayerState:
        normalized_name = username.strip()
        if not normalized_name:
            raise ValueError("Username pemain wajib diisi.")

        players: dict[str, PlayerState] = self.game_state["players"]
        if normalized_name not in players:
            players[normalized_name] = {
                "role": "civilian",
                "status": "active",
                "sus_score": 0.0,
                "aggressiveness": 0,
            }
        return players[normalized_name]

    async def register_player_socket(self, sid: str, username: str) -> PlayerState:
        authenticated_username = self.socket_players.get(sid)
        normalized_username = username.strip()
        if authenticated_username is None:
            raise ValueError("Login diperlukan sebelum masuk ke game.")
        if normalized_username != authenticated_username:
            raise ValueError("Identitas pemain tidak sesuai dengan sesi login.")

        player = self.get_player(authenticated_username)
        self.persistence.ensure_player(authenticated_username)
        await self.sio.enter_room(sid, authenticated_username)
        return player

    async def connect(self, sid: str, environ: dict[str, Any], auth: Any = None) -> None:
        token = str(auth.get("token", "")) if isinstance(auth, dict) else ""
        try:
            user = auth_service.user_for_token(token)
        except (SessionValidationError, AuthenticationPersistenceError) as error:
            logger.info("Koneksi Socket ditolak untuk %s: %s", sid, error)
            raise ConnectionRefusedError("Login diperlukan.") from error

        self.socket_players[sid] = user.username
        logger.info("Pemain terkoneksi ke Socket: %s", sid)
        await self.sio.emit(
            "server_ready",
            {"message": f"Python game server siap, {user.display_name}."},
            to=sid,
        )

    async def disconnect(self, sid: str) -> None:
        self.socket_players.pop(sid, None)
        logger.info("Pemain keluar dari Socket: %s", sid)

    async def register_player(self, sid: str, data: dict[str, Any]) -> None:
        try:
            await self.register_player_socket(sid, str(data.get("username", "")))
        except (ValueError, PersistenceError) as error:
            await self.sio.emit("system_alert", {"msg": str(error)}, to=sid)

    async def send_chat(self, sid: str, data: dict[str, Any]) -> None:
        try:
            sender = str(data.get("username", "")).strip()
            message = str(data.get("message", "")).strip()
            if not message:
                raise ValueError("Pesan chat tidak boleh kosong.")
            player = await self.register_player_socket(sid, sender)
        except (ValueError, PersistenceError) as error:
            await self.sio.emit("system_alert", {"msg": str(error)}, to=sid)
            return

        if player["status"] in {"hostage", "gagged"}:
            await self.sio.emit("system_alert", {"msg": "Suara Anda hilang..."}, to=sid)
            return

        intent: str | None = None
        host_response: str | None = None
        try:
            intent = self.analysis.predict_intent(message)
            player["aggressiveness"] = min(
                100,
                int(player["aggressiveness"]) + self.analysis.aggressiveness_for_intent(intent),
            )
        except IntentModelNotReadyError:
            # Messages can still be relayed if the optional classifier is loading.
            pass

        suspicion_score = calculate_suspicion(int(player["aggressiveness"]), 20)
        player["sus_score"] = round(suspicion_score, 2)

        # Relay the player's message immediately. OpenAI can take a few seconds,
        # and a player must never feel that their message disappeared while it
        # is being analysed.
        await self.sio.emit("receive_chat", {"sender": sender, "message": message})

        if intent is not None:
            host_response = await self.analysis.create_host_response(
                player_name=sender,
                message=message,
                intent=intent,
                aggressiveness=int(player["aggressiveness"]),
                suspicion_score=suspicion_score,
                suspicion_status=status_for_score(suspicion_score),
            )
        try:
            self.persistence.record_player_message(
                username=sender,
                message=message,
                intent=intent,
                aggressiveness=int(player["aggressiveness"]),
                suspicion_score=suspicion_score,
                status=str(player["status"]),
                llm_response=host_response,
            )
        except PersistenceError as error:
            await self.sio.emit("system_alert", {"msg": str(error)}, to=sid)
            return
        if host_response is not None:
            await self.sio.emit(
                "receive_chat", {"sender": "NOX", "message": host_response}
            )

    async def use_gag_order(self, sid: str, data: dict[str, Any]) -> None:
        target = str(data.get("target", "")).strip()
        players: dict[str, PlayerState] = self.game_state["players"]
        if not target or target not in players:
            await self.sio.emit("system_alert", {"msg": "Target pemain tidak ditemukan."}, to=sid)
            return

        players[target]["status"] = "gagged"
        try:
            self.persistence.update_player_status(username=target, status="gagged")
        except PersistenceError as error:
            players[target]["status"] = "active"
            await self.sio.emit("system_alert", {"msg": str(error)}, to=sid)
            return
        await self.sio.emit("status_changed", {"status": "gagged"}, to=target)

    async def start_tribunal(self, sid: str) -> None:
        players: dict[str, PlayerState] = self.game_state["players"]
        try:
            self.persistence.set_phase("tribunal")
            self.game_state["phase"] = "tribunal"
            for username, stats in players.items():
                silence_percentage = 80 if stats["status"] == "gagged" else 20
                suspicion_score = calculate_suspicion(
                    int(stats["aggressiveness"]), silence_percentage
                )
                stats["sus_score"] = round(suspicion_score, 2)
                self.persistence.update_player_scores(
                    username=username,
                    aggressiveness=int(stats["aggressiveness"]),
                    suspicion_score=suspicion_score,
                )
        except PersistenceError as error:
            await self.sio.emit("system_alert", {"msg": str(error)}, to=sid)
            return
        await self.sio.emit("tribunal_data", players)


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

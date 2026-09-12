"""Authenticated create/join/inspect lobby endpoints."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from typing import Literal
from controller.middleware.auth import require_authenticated_user
from services.room_service import room_service
from services.checker_service import checker_service

router = APIRouter(prefix="/api/rooms", tags=["rooms"])


class JoinRoom(BaseModel):
    code: str = Field(min_length=6, max_length=6, pattern=r"^[a-fA-F0-9]{6}$")


class BotOption(BaseModel):
    enabled: bool


class StartOption(BaseModel):
    quick: bool = False


class SkipOption(BaseModel):
    match_id: str = Field(min_length=1, max_length=40)
    round_number: int = Field(ge=1)
    phase: Literal["day"]


class PlayOption(BaseModel):
    match_id: str = Field(max_length=40)
    round_number: int = Field(ge=1)
    phase: Literal["day", "night", "tribunal"]
    target: str = Field(min_length=1, max_length=100)
    ability: Literal["gag", "hostage", "guard", "peek"] | None = None


# Adapter error bersama untuk operasi game yang sudah menghasilkan snapshot privat.
def game_result(operation):
    try:
        return operation()
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.get("/active")
# PEMULIHAN: hanya pertandingan milik akun terautentikasi; letakkan sebelum /{code}.
def active(user=Depends(require_authenticated_user)):
    return {"active": room_service.active(user.username)}


@router.post("/{code}/skip-discussion")
# PERSETUJUAN: bukan vote Tribunal, tidak bergantung pada status bungkam.
def skip(code: str, body: SkipOption, user=Depends(require_authenticated_user)):
    return game_result(lambda: room_service.skip(code, user.username, **body.model_dump()))


@router.post("/{code}/start")
# START: otorisasi host dan jumlah peserta dilakukan di RoomService.
def start(code: str, body: StartOption, user=Depends(require_authenticated_user)):
    return game_result(lambda: room_service.start(code, user.username, body.quick))


@router.get("/{code}/game")
# SNAPSHOT: hanya data publik dan informasi privat akun yang meminta.
def state(code: str, user=Depends(require_authenticated_user)):
    return game_result(lambda: room_service.state(code, user.username))


@router.post("/{code}/play")
# COMMAND: validasi bentuk payload, lalu service mengunci aksi/vote atomik.
def play(code: str, body: PlayOption, user=Depends(require_authenticated_user)):
    return game_result(lambda: room_service.play(code, user.username, **body.model_dump()))


@router.post("/{code}/leave")
# LEAVE: service menolak keluar saat pertandingan aktif.
def leave(code: str, user=Depends(require_authenticated_user)):
    game_result(lambda: room_service.leave(code, user.username))
    return {"left": True}


# HELPER CONTROLLER: jalankan operasi lobby, buat snapshot, dan ubah ValueError menjadi HTTP 400.
def result(operation):
    try:
        return room_service.snapshot(operation())
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.post("")
# CONTROLLER: buat ruangan untuk pengguna yang sudah login dan kembalikan kode serta roster.
def create(user=Depends(require_authenticated_user)):
    return result(lambda: room_service.create(user.username))


@router.post("/join")
# CONTROLLER: tambahkan pengguna yang login ke ruangan berdasarkan kode dari request.
def join(body: JoinRoom, user=Depends(require_authenticated_user)):
    return result(lambda: room_service.join(body.code, user.username))


@router.get("/{code}")
# CONTROLLER: ambil snapshot ruangan setelah service memeriksa keanggotaan pengguna.
def details(code: str, user=Depends(require_authenticated_user)):
    return result(lambda: room_service.get(code, user.username))


@router.post("/{code}/bot")
# CONTROLLER: minta service mengubah pilihan NOX; hanya pembuat ruangan yang diizinkan.
def bot(code: str, body: BotOption, user=Depends(require_authenticated_user)):
    return result(lambda: room_service.set_bot(code, user.username, body.enabled))


@router.get("/{code}/checker")
# CONTROLLER DEBUG PUBLIK: validasi format kode lalu baca jejak checker tanpa login, khusus development lokal.
def checker(code: str):
    # Sengaja publik untuk development lokal atas permintaan pengguna.
    # Pasang autentikasi/otorisasi sebelum deployment; prompt membocorkan role bot.
    code = code.strip().upper()
    if len(code) != 6 or any(char not in "0123456789ABCDEF" for char in code):
        raise HTTPException(status_code=400, detail="Kode ruangan harus 6 karakter heksadesimal.")
    with room_service.lock:
        room = room_service.rooms.get(code)
        if room and room.match and not room.match.winner:
            raise HTTPException(status_code=403, detail="Checker dikunci selama pertandingan untuk melindungi role dan Silent Terror.")
    return {"room_code": code, "traces": checker_service.list(code)}

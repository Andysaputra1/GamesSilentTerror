"""Authenticated create/join/inspect lobby endpoints."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from typing import Literal
from controller.middleware.auth import require_authenticated_user
from services.room_service import room_service
from services.persistence_service import PersistenceService, PersistenceError

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


@router.get("/current")
def current(user=Depends(require_authenticated_user)):
    with room_service.lock:
        room = room_service.current(user.username)
        return {"room": room_service.snapshot(room) if room else None}


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
    def create_archived():
        with room_service.lock:
            for _ in range(10):
                room = room_service.create(user.username)
                try:
                    if PersistenceService(room.code).archive_new_room(user.username):
                        return room
                except PersistenceError as error:
                    room_service.rooms.pop(room.code, None)
                    raise HTTPException(503, "Ruangan gagal disimpan. Coba lagi.") from error
                room_service.rooms.pop(room.code, None)
            raise HTTPException(503, "Kode ruangan belum tersedia. Coba lagi.")
    return result(create_archived)


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


@router.get("/{code}/checker", include_in_schema=False)
def checker(code: str):
    raise HTTPException(status_code=410, detail="Checker dipindahkan ke /panel dan memerlukan login administrator.")

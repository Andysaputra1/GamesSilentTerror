"""Endpoint room untuk pengguna yang sudah login: lobby dan perintah selama pertandingan."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from typing import Literal
from app.middleware.auth import require_authenticated_user
from app.services.room_service import RoomBelumTersimpan, room_service

router = APIRouter(prefix="/api/rooms", tags=["rooms"])


class JoinRoom(BaseModel):
    code: str = Field(min_length=6, max_length=6, pattern=r"^[a-fA-F0-9]{6}$")


class CreateRoom(BaseModel):
    capacity: int = Field(default=6, ge=4, le=10)


# Satu tekan = satu bot; aksi di server atomik, jadi dobel klik atau dua tab tidak melompati batas.
class BotOption(BaseModel):
    aksi: Literal["tambah", "kurangi"]


class StartOption(BaseModel):
    quick: bool = False


class SkipOption(BaseModel):
    match_id: str = Field(min_length=1, max_length=40)
    round_number: int = Field(ge=1)
    phase: Literal["day"]


class CancelVoteOption(BaseModel):
    match_id: str = Field(min_length=1, max_length=40)
    round_number: int = Field(ge=1)
    phase: Literal["tribunal"]


class CancelActionOption(BaseModel):
    match_id: str = Field(min_length=1, max_length=40)
    round_number: int = Field(ge=1)
    phase: Literal["night"]


class TeamChatOption(BaseModel):
    match_id: str = Field(min_length=1, max_length=40)
    round_number: int = Field(ge=1)
    phase: Literal["night"]
    message: str = Field(min_length=1, max_length=1000)


class ReadyOption(BaseModel):
    match_id: str = Field(min_length=1, max_length=40)


class PlayOption(BaseModel):
    match_id: str = Field(max_length=40)
    round_number: int = Field(ge=1)
    phase: Literal["day", "night", "tribunal"]
    target: str = Field(min_length=1, max_length=100)
    ability: Literal["gag", "hostage", "guard", "peek"] | None = None


# Adapter error bersama untuk perintah game yang sudah menghasilkan snapshot privat.
def _jalankan_perintah_game(perintah):
    try:
        return perintah()
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.get("/active")
# PEMULIHAN: hanya pertandingan milik akun terautentikasi; letakkan sebelum /{code}.
def active(user=Depends(require_authenticated_user)):
    return {"active": room_service.active(user.username)}


# Pulihkan ruangan milik pengguna, termasuk lobby dan pertandingan selesai.
@router.get("/current")
def current(user=Depends(require_authenticated_user)):
    return {"room": room_service.snapshot_room_saat_ini(user.username)}


@router.post("/{code}/skip-discussion")
# PERSETUJUAN: bukan vote Tribunal, tidak bergantung pada status bungkam.
def skip(code: str, body: SkipOption, user=Depends(require_authenticated_user)):
    return _jalankan_perintah_game(
        lambda: room_service.skip(code, user.username, **body.model_dump())
    )


@router.post("/{code}/start")
# START: otorisasi host dicek RoomService; batas 4–10 peserta dicek Match saat pertandingan dibuat.
def start(code: str, body: StartOption, user=Depends(require_authenticated_user)):
    return _jalankan_perintah_game(lambda: room_service.start(code, user.username, body.quick))


@router.post("/{code}/ready")
# SIAP: manusia menandai sudah membaca panduan; ronde 1 tetap menunggu AI siap.
def ready(code: str, body: ReadyOption, user=Depends(require_authenticated_user)):
    return _jalankan_perintah_game(
        lambda: room_service.ready(code, user.username, match_id=body.match_id)
    )


@router.post("/{code}/reveal")
# BUKA KARTU: manusia sudah melihat role-nya; ronde 1 tetap mengikuti hitung mundur.
def reveal(code: str, body: ReadyOption, user=Depends(require_authenticated_user)):
    return _jalankan_perintah_game(
        lambda: room_service.reveal(code, user.username, match_id=body.match_id)
    )


@router.get("/{code}/game")
# SNAPSHOT: hanya data publik dan informasi privat akun yang meminta.
def state(code: str, user=Depends(require_authenticated_user)):
    return _jalankan_perintah_game(lambda: room_service.state(code, user.username))


@router.post("/{code}/play")
# COMMAND: validasi bentuk payload, lalu service mengunci aksi/vote atomik.
def play(code: str, body: PlayOption, user=Depends(require_authenticated_user)):
    return _jalankan_perintah_game(
        lambda: room_service.play(code, user.username, **body.model_dump())
    )


@router.post("/{code}/cancel-vote")
# BATAL VOTE: tarik suara Tribunal milik sendiri agar bisa memilih ulang sebelum waktu habis.
def cancel_vote(code: str, body: CancelVoteOption, user=Depends(require_authenticated_user)):
    return _jalankan_perintah_game(
        lambda: room_service.cancel_vote(code, user.username, **body.model_dump())
    )


@router.post("/{code}/cancel-action")
# BATAL AKSI MALAM: tarik Hostage/Guard/Peek milik sendiri agar bisa memilih ulang sebelum malam habis.
def cancel_action(code: str, body: CancelActionOption, user=Depends(require_authenticated_user)):
    return _jalankan_perintah_game(
        lambda: room_service.cancel_action(code, user.username, **body.model_dump())
    )


@router.post("/{code}/team-chat")
# CHAT TIM: pesan rahasia rekan setim saat malam; hanya tersimpan di memori pertandingan.
def team_chat(code: str, body: TeamChatOption, user=Depends(require_authenticated_user)):
    return _jalankan_perintah_game(
        lambda: room_service.team_chat(code, user.username, **body.model_dump())
    )


@router.post("/{code}/leave")
# LEAVE: keluar saat pertandingan aktif = tereliminasi seperti dieksekusi (`left`). Keluar ulang dari pertandingan
# yang sama diabaikan selama room masih ada; di lobby, atau sesudah room dihapus, keluar ulang mendapat 400.
def leave(code: str, user=Depends(require_authenticated_user)):
    _jalankan_perintah_game(lambda: room_service.leave(code, user.username))
    return {"left": True}


# HELPER CONTROLLER: jalankan perintah lobby, buat snapshot, dan ubah ValueError menjadi HTTP 400.
def _jalankan_perintah_lobby(perintah):
    try:
        return room_service.snapshot(perintah())
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except RoomBelumTersimpan as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


@router.post("")
# CONTROLLER: buat ruangan untuk pengguna yang sudah login dan kembalikan kode serta roster.
def create(body: CreateRoom = CreateRoom(), user=Depends(require_authenticated_user)):
    return _jalankan_perintah_lobby(
        lambda: room_service.buat_room_terarsip(user.username, capacity=body.capacity)
    )


@router.post("/join")
# CONTROLLER: tambahkan pengguna yang login ke ruangan berdasarkan kode dari request.
def join(body: JoinRoom, user=Depends(require_authenticated_user)):
    return _jalankan_perintah_lobby(lambda: room_service.join(body.code, user.username))


@router.get("/{code}")
# CONTROLLER: ambil snapshot ruangan setelah service memeriksa keanggotaan pengguna.
def details(code: str, user=Depends(require_authenticated_user)):
    return _jalankan_perintah_lobby(lambda: room_service.get(code, user.username))


@router.post("/{code}/bot")
# CONTROLLER: host menambah atau mengurangi satu bot; izin host, batas BOT_MAKS, dan kursi kosong dicek service.
def bot(code: str, body: BotOption, user=Depends(require_authenticated_user)):
    return _jalankan_perintah_lobby(lambda: room_service.ubah_bot(code, user.username, body.aksi))

"""Authenticated create/join/inspect lobby endpoints."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from controller.middleware.auth import require_authenticated_user
from services.room_service import room_service
from services.checker_service import checker_service

router = APIRouter(prefix="/api/rooms", tags=["rooms"])


class JoinRoom(BaseModel):
    code: str = Field(min_length=6, max_length=6, pattern=r"^[a-fA-F0-9]{6}$")


class BotOption(BaseModel):
    enabled: bool


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
    return {"room_code": code, "traces": checker_service.list(code)}

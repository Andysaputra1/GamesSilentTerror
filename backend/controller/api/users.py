"""Endpoint manajemen user hanya untuk sesi administrator panel."""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, model_validator

from controller.api.panel import require_panel
from services.auth_service import AuthenticationPersistenceError
from services import user_management_service as users
from schemas.auth import UpdateProfileRequest

router = APIRouter(
    prefix="/api/panel/users", tags=["panel-users"], dependencies=[Depends(require_panel)]
)


class ResetPasswordRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    password: str = Field(min_length=10, max_length=128)
    password_confirmation: str = Field(min_length=10, max_length=128)

    # Konfirmasi mencegah admin menyimpan password yang salah ketik.
    @model_validator(mode="after")
    def passwords_match(self):
        if self.password != self.password_confirmation:
            raise ValueError("Konfirmasi password tidak cocok.")
        return self


class DeleteUserRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirm_username: str = Field(min_length=1, max_length=100)


class CreateUserRequest(UpdateProfileRequest, ResetPasswordRequest):
    username: str = Field(min_length=3, max_length=40, pattern=r"^[A-Za-z0-9_]+$")


# Ubah error layanan menjadi respons yang aman tanpa detail SQL atau kredensial.
def user_result(operation):
    try:
        return operation()
    except users.UserNotFound as error:
        raise HTTPException(404, str(error)) from error
    except ValueError as error:
        raise HTTPException(409, str(error)) from error
    except AuthenticationPersistenceError as error:
        raise HTTPException(503, "Data user belum dapat diproses. Coba lagi nanti.") from error


# Cari username/nama tampilan dengan cursor ID agar seluruh tabel tidak dimuat sekaligus.
@router.get("")
def list_users(after_id: int = Query(0, ge=0), search: str = Query("", max_length=100)):
    return user_result(lambda: users.list_users(after_id, search.strip()))


# Tambah akun lokal dengan nama pilihan admin; akun Google hanya dibuat lewat login Google asli.
@router.post("", status_code=201)
def create_user(body: CreateUserRequest):
    return user_result(lambda: users.create_user(body.username, body.display_name, body.password))


# Admin boleh mereset password akun lokal; semua sesi lama langsung dicabut.
@router.post("/{user_id}/password", status_code=204)
def reset_password(user_id: int, body: ResetPasswordRequest):
    user_result(lambda: users.reset_password(user_id, body.password))


# Konfirmasi username terikat pada ID target; riwayat chat dan analisis tetap tersedia.
@router.post("/{user_id}/delete", status_code=204)
def delete_user(user_id: int, body: DeleteUserRequest):
    user_result(lambda: users.delete_user(user_id, body.confirm_username))

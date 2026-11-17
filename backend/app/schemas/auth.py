"""Kontrak validasi dan respons untuk login pemain."""

from datetime import datetime
import re
import unicodedata

from pydantic import BaseModel, ConfigDict, Field, EmailStr, field_validator, model_validator

from app.bot.nlu import ISTILAH_GAME, KATA_GANTI


# Nama tampilan dibaca NLU bot dan pemeriksa kalimat bot, jadi dicek sebelum disimpan. Tepi nama dirapikan, lalu ditolak
# bila memuat karakter kontrol atau pembalik arah, tidak punya huruf/angka (mis. hanya emoji), atau kata pertamanya kata
# ganti/istilah game yang oleh NLU tidak pernah dianggap nama (mis. "Aku", "Gw", "Vote"). Hasil: nama yang sudah rapi.
# Dipakai form daftar, ganti profil, panel user, dan nama dari Google.
def periksa_nama_tampilan(nama: str) -> str:
    if any(unicodedata.category(karakter) in {"Cc", "Cf", "Cs"} for karakter in nama):
        raise ValueError("Nama tidak boleh mengandung karakter kontrol.")
    nama = nama.strip()
    if not any(karakter.isalnum() for karakter in nama):
        raise ValueError("Nama harus memuat huruf atau angka.")
    kata = re.findall(r"\w+", nama.casefold())
    if kata and kata[0] in KATA_GANTI | ISTILAH_GAME:
        raise ValueError(
            "Nama tidak boleh diawali kata ganti atau istilah game (mis. Aku, Gw, Dia, Vote, Hitman)."
        )
    return nama


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=254)
    password: str = Field(min_length=1, max_length=256)


class AuthenticatedUserResponse(BaseModel):
    username: str
    display_name: str
    skin_id: str


class UpdateSkinRequest(BaseModel):
    skin_id: str = Field(min_length=1, max_length=20)


class UpdateProfileRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    display_name: str = Field(min_length=1, max_length=100, strict=True)
    username: str | None = Field(
        default=None, min_length=3, max_length=40, pattern=r"^[A-Za-z0-9_]+$"
    )

    # Rapikan dan periksa nama (periksa_nama_tampilan) sebelum validasi panjang dijalankan.
    @field_validator("display_name", mode="before")
    @classmethod
    def clean_display_name(cls, nilai):
        if isinstance(nilai, str):
            return periksa_nama_tampilan(nilai)
        return nilai


class RegisterRequest(UpdateProfileRequest):
    username: str = Field(min_length=3, max_length=40, pattern=r"^[A-Za-z0-9_]+$")
    display_name: str | None = Field(default=None, min_length=1, max_length=100)
    # Email lama tetap diterima dari frontend lama, tetapi tidak disimpan (lihat register_account).
    email: EmailStr | None = Field(default=None, max_length=254)
    email_confirmation: EmailStr | None = Field(default=None, max_length=254)
    password: str = Field(min_length=10, max_length=128)
    password_confirmation: str = Field(min_length=10, max_length=128)

    # Pastikan email dan password cocok dengan kolom konfirmasi pendaftaran. Tanpa nama tampilan, username menjadi
    # nama tampilan, jadi username itu ikut diperiksa sebagai nama.
    @model_validator(mode="after")
    def confirmations_match(self):
        if (self.email or "").lower() != (self.email_confirmation or "").lower():
            raise ValueError("Konfirmasi email tidak cocok.")
        if self.password != self.password_confirmation:
            raise ValueError("Konfirmasi password tidak cocok.")
        if self.display_name is None:
            periksa_nama_tampilan(self.username)
        return self


class GoogleLoginRequest(BaseModel):
    credential: str = Field(min_length=1, max_length=10000)
    nonce: str = Field(min_length=32, max_length=128)


class LoginResponse(BaseModel):
    access_token: str
    expires_at: datetime
    user: AuthenticatedUserResponse

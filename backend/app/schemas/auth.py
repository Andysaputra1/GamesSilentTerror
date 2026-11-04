"""Kontrak validasi dan respons untuk login pemain."""

from datetime import datetime
import unicodedata

from pydantic import BaseModel, ConfigDict, Field, EmailStr, field_validator, model_validator


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

    # Rapikan tepi nama dan tolak karakter kontrol sebelum validasi panjang dijalankan.
    @field_validator("display_name", mode="before")
    @classmethod
    def clean_display_name(cls, nilai):
        if isinstance(nilai, str):
            if any(unicodedata.category(karakter) in {"Cc", "Cf", "Cs"} for karakter in nilai):
                raise ValueError("Nama tidak boleh mengandung karakter kontrol.")
            return nilai.strip()
        return nilai


class RegisterRequest(UpdateProfileRequest):
    username: str = Field(min_length=3, max_length=40, pattern=r"^[A-Za-z0-9_]+$")
    display_name: str | None = Field(default=None, min_length=1, max_length=100)
    # Email lama tetap diterima saat frontend/backend diperbarui bertahap; form baru tidak memintanya.
    email: EmailStr | None = Field(default=None, max_length=254)
    email_confirmation: EmailStr | None = Field(default=None, max_length=254)
    password: str = Field(min_length=10, max_length=128)
    password_confirmation: str = Field(min_length=10, max_length=128)

    # Pastikan email dan password cocok dengan kolom konfirmasi pendaftaran.
    @model_validator(mode="after")
    def confirmations_match(self):
        if (self.email or "").lower() != (self.email_confirmation or "").lower():
            raise ValueError("Konfirmasi email tidak cocok.")
        if self.password != self.password_confirmation:
            raise ValueError("Konfirmasi password tidak cocok.")
        return self


class GoogleLoginRequest(BaseModel):
    credential: str = Field(min_length=1, max_length=10000)
    nonce: str = Field(min_length=32, max_length=128)


class LoginResponse(BaseModel):
    access_token: str
    expires_at: datetime
    user: AuthenticatedUserResponse

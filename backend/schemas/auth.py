"""Validation and response contracts for player login."""

from datetime import datetime

from pydantic import BaseModel, Field, EmailStr, model_validator


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=254)
    password: str = Field(min_length=1, max_length=256)


class AuthenticatedUserResponse(BaseModel):
    username: str
    display_name: str


class RegisterRequest(BaseModel):
    username: str = Field(min_length=3, max_length=40, pattern=r'^[A-Za-z0-9_]+$')
    email: EmailStr = Field(max_length=254)
    email_confirmation: EmailStr = Field(max_length=254)
    password: str = Field(min_length=10, max_length=128)
    password_confirmation: str = Field(min_length=10, max_length=128)

    @model_validator(mode='after')
    def confirmations_match(self):
        if self.email.lower() != self.email_confirmation.lower():
            raise ValueError('Konfirmasi email tidak cocok.')
        if self.password != self.password_confirmation:
            raise ValueError('Konfirmasi password tidak cocok.')
        return self


class GoogleLoginRequest(BaseModel):
    credential: str = Field(min_length=1, max_length=10000)
    nonce: str = Field(min_length=32, max_length=128)


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_at: datetime
    user: AuthenticatedUserResponse

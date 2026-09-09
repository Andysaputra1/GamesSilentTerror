"""Authentication use cases backed by opaque, revocable MySQL sessions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import logging
import secrets

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from module.mysql_connector import SessionLocal
from config.settings import settings
from models import auth_queries
from services.password_service import verify_password


logger = logging.getLogger("shadow_heist.auth")


class AuthenticationError(RuntimeError):
    """Login failed without revealing whether an account exists."""


class SessionValidationError(RuntimeError):
    """Bearer token is missing, expired, or revoked."""


class AuthenticationPersistenceError(RuntimeError):
    """The authentication database transaction failed."""


@dataclass(frozen=True)
class AuthenticatedUser:
    id: int
    username: str
    display_name: str


@dataclass(frozen=True)
class LoginResult:
    access_token: str
    expires_at: datetime
    user: AuthenticatedUser


# HELPER: hash token menggunakan SHA-256 agar database tidak menyimpan token sesi dalam bentuk asli.
def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


# HELPER WAKTU: hasilkan waktu UTC tanpa metadata zona agar sesuai kolom DATETIME MySQL.
def _utc_now() -> datetime:
    # MySQL DATETIME is timezone-naive. Keep every value in UTC.
    return datetime.now(timezone.utc).replace(tzinfo=None)


class AuthService:
    """Validates credentials and creates/revokes database-backed sessions."""

    @staticmethod
    # STATIC METHOD: jalankan operasi database, commit jika sukses, rollback saat error SQL, lalu tutup sesi.
    def _transaction(operation):
        database = SessionLocal()
        try:
            result = operation(database)
            database.commit()
            return result
        except SQLAlchemyError as error:
            database.rollback()
            logger.error("Authentication database transaction failed (%s).", type(error).__name__)
            raise AuthenticationPersistenceError("Layanan login sedang tidak tersedia.") from error
        finally:
            database.close()

    # SERVICE LOGIN: normalisasi username, verifikasi akun/password, dan buat sesi login dengan masa berlaku.
    def login(self, *, username: str, password: str) -> LoginResult:
        normalized_username = username.strip()

        # CALLBACK TRANSAKSI LOGIN: ambil akun, verifikasi password, lalu simpan hash token baru dan kembalikan sesi.
        def operation(database: Session) -> LoginResult:
            account = auth_queries.account_by_username(database, normalized_username)
            if (
                account is None
                or not account["is_active"]
                or not verify_password(password, account["password_hash"])
            ):
                raise AuthenticationError("Username atau password tidak valid.")

            token = secrets.token_urlsafe(32)
            expires_at = _utc_now() + timedelta(hours=settings.auth_session_hours)
            auth_queries.create_session(
                database, user_id=account["id"], token_hash=_token_hash(token), expires_at=expires_at
            )
            return LoginResult(
                access_token=token,
                expires_at=expires_at.replace(tzinfo=timezone.utc),
                user=AuthenticatedUser(
                    id=account["id"],
                    username=account["username"],
                    display_name=account["display_name"],
                ),
            )

        return self._transaction(operation)

    # SERVICE AUTH: cari akun aktif untuk token yang belum kedaluwarsa; sesi tidak valid ditolak.
    def user_for_token(self, token: str) -> AuthenticatedUser:
        if not token.strip():
            raise SessionValidationError("Sesi login tidak ditemukan.")

        database = SessionLocal()
        try:
            row = auth_queries.account_for_token(database, _token_hash(token), _utc_now())
        except SQLAlchemyError as error:
            logger.error("Session database query failed (%s).", type(error).__name__)
            raise AuthenticationPersistenceError("Layanan login sedang tidak tersedia.") from error
        finally:
            database.close()

        if row is None:
            raise SessionValidationError("Sesi login sudah tidak valid.")
        return AuthenticatedUser(id=row["id"], username=row["username"], display_name=row["display_name"])

    # SERVICE LOGOUT: cabut token melalui transaksi database; token kosong tidak memerlukan operasi.
    def logout(self, token: str) -> None:
        if not token.strip():
            return

        # CALLBACK TRANSAKSI LOGOUT: hapus sesi yang cocok dengan hash token dalam transaksi pemanggil.
        def operation(database: Session) -> None:
            auth_queries.delete_session(database, _token_hash(token))

        self._transaction(operation)


auth_service = AuthService()

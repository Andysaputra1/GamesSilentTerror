"""Authentication use cases backed by opaque, revocable MySQL sessions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import logging
import secrets

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from config.database import SessionLocal
from config.settings import settings
from models import AuthSession, UserAccount
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


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _utc_now() -> datetime:
    # MySQL DATETIME is timezone-naive. Keep every value in UTC.
    return datetime.now(timezone.utc).replace(tzinfo=None)


class AuthService:
    """Validates credentials and creates/revokes database-backed sessions."""

    @staticmethod
    def _transaction(operation):
        database = SessionLocal()
        try:
            result = operation(database)
            database.commit()
            return result
        except SQLAlchemyError as error:
            database.rollback()
            logger.exception("Transaksi autentikasi MySQL gagal: %s", error)
            raise AuthenticationPersistenceError("Layanan login sedang tidak tersedia.") from error
        finally:
            database.close()

    def login(self, *, username: str, password: str) -> LoginResult:
        normalized_username = username.strip()

        def operation(database: Session) -> LoginResult:
            account = database.scalar(
                select(UserAccount).where(UserAccount.username == normalized_username)
            )
            if (
                account is None
                or not account.is_active
                or not verify_password(password, account.password_hash)
            ):
                raise AuthenticationError("Username atau password tidak valid.")

            token = secrets.token_urlsafe(32)
            expires_at = _utc_now() + timedelta(hours=settings.auth_session_hours)
            database.add(
                AuthSession(
                    user_id=account.id,
                    token_hash=_token_hash(token),
                    expires_at=expires_at,
                )
            )
            return LoginResult(
                access_token=token,
                expires_at=expires_at.replace(tzinfo=timezone.utc),
                user=AuthenticatedUser(
                    id=account.id,
                    username=account.username,
                    display_name=account.display_name,
                ),
            )

        return self._transaction(operation)

    def user_for_token(self, token: str) -> AuthenticatedUser:
        if not token.strip():
            raise SessionValidationError("Sesi login tidak ditemukan.")

        database = SessionLocal()
        try:
            row = database.execute(
                select(UserAccount).join(AuthSession).where(
                    AuthSession.token_hash == _token_hash(token),
                    AuthSession.expires_at > _utc_now(),
                    UserAccount.is_active.is_(True),
                )
            ).scalar_one_or_none()
        except SQLAlchemyError as error:
            logger.exception("Validasi sesi MySQL gagal: %s", error)
            raise AuthenticationPersistenceError("Layanan login sedang tidak tersedia.") from error
        finally:
            database.close()

        if row is None:
            raise SessionValidationError("Sesi login sudah tidak valid.")
        return AuthenticatedUser(id=row.id, username=row.username, display_name=row.display_name)

    def logout(self, token: str) -> None:
        if not token.strip():
            return

        def operation(database: Session) -> None:
            session = database.scalar(
                select(AuthSession).where(AuthSession.token_hash == _token_hash(token))
            )
            if session is not None:
                database.delete(session)

        self._transaction(operation)


auth_service = AuthService()

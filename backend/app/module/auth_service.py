"""Layanan login dan sesi: token buram yang disimpan di MySQL dan bisa dicabut.

DB hanya menyimpan hash SHA-256 token, bukan token asli. Waktu memakai UTC tanpa zona, karena kolom DATETIME MySQL tidak menyimpan zona waktu.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import logging
import secrets

from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.module.mysql_connector import SessionLocal
from app.config.settings import settings
from app.models import auth_queries
from app.module.password_service import verify_password

logger = logging.getLogger("shadow_heist.auth")


class AuthenticationError(RuntimeError):
    """Login gagal tanpa mengungkap apakah akunnya ada."""


class SessionValidationError(RuntimeError):
    """Token bearer kosong, kedaluwarsa, atau sudah dicabut."""


class AuthenticationPersistenceError(RuntimeError):
    """Transaksi database autentikasi gagal."""


@dataclass(frozen=True)
class AuthenticatedUser:
    id: int
    username: str
    display_name: str
    skin_id: str = "dexter"


@dataclass(frozen=True)
class LoginResult:
    access_token: str
    expires_at: datetime
    user: AuthenticatedUser


class AuthService:
    """Memeriksa kredensial serta membuat dan mencabut sesi di database."""

    # Jalankan operasi database: commit bila sukses, rollback saat error SQL, lalu tutup sesi.
    @staticmethod
    def _jalankan_transaksi(operasi):
        database = SessionLocal()
        try:
            hasil = operasi(database)
            database.commit()
            return hasil
        except SQLAlchemyError as error:
            database.rollback()
            logger.error("Authentication database transaction failed (%s).", type(error).__name__)
            raise AuthenticationPersistenceError("Layanan login sedang tidak tersedia.") from error
        finally:
            database.close()

    # Normalisasi username, verifikasi akun dan password, lalu buat sesi dengan masa berlaku.
    def login(self, *, username: str, password: str) -> LoginResult:
        username_bersih = username.strip()

        # Hanya hash token yang disimpan; token asli dikembalikan sekali ini ke klien.
        def periksa_akun_lalu_buat_sesi(database: Session) -> LoginResult:
            akun = auth_queries.account_by_login(database, username_bersih)
            if (
                akun is None
                or not akun["is_active"]
                or not verify_password(password, akun["password_hash"])
            ):
                raise AuthenticationError("Username atau password tidak valid.")

            token = secrets.token_urlsafe(32)
            waktu_kedaluwarsa = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(
                hours=settings.auth_session_hours
            )
            auth_queries.create_session(
                database,
                user_id=akun["id"],
                token_hash=hashlib.sha256(token.encode("utf-8")).hexdigest(),
                expires_at=waktu_kedaluwarsa,
            )
            return LoginResult(
                access_token=token,
                expires_at=waktu_kedaluwarsa.replace(tzinfo=timezone.utc),
                user=AuthenticatedUser(
                    id=akun["id"],
                    username=akun["username"],
                    display_name=akun["display_name"],
                    skin_id=akun["skin_id"],
                ),
            )

        return self._jalankan_transaksi(periksa_akun_lalu_buat_sesi)

    # Cari akun aktif untuk token yang belum kedaluwarsa; sesi tidak valid ditolak.
    def user_for_token(self, token: str) -> AuthenticatedUser:
        if not token.strip():
            raise SessionValidationError("Sesi login tidak ditemukan.")

        akun = self._jalankan_transaksi(
            lambda database: auth_queries.account_for_token(
                database,
                hashlib.sha256(token.encode("utf-8")).hexdigest(),
                datetime.now(timezone.utc).replace(tzinfo=None),
            )
        )
        if akun is None:
            raise SessionValidationError("Sesi login sudah tidak valid.")
        return AuthenticatedUser(**akun)

    # Username hanya boleh berganti di luar ruangan; token tetap terkait ID akun yang sama.
    def update_profile(
        self, user: AuthenticatedUser, display_name: str, username: str | None = None
    ) -> AuthenticatedUser:
        from app.module.room_service import room_service

        username_terpilih = username or user.username
        username_berubah = username_terpilih != user.username
        if username_berubah:
            # Impor lambat: user_management_service mengimpor modul ini.
            from app.module.user_management_service import validate_username

            validate_username(username_terpilih)

        # Nama dan username harus disimpan bersama; benturan username membatalkan seluruh perubahan.
        def simpan_nama_dan_username(database):
            if username_berubah:
                try:
                    auth_queries.update_username(database, user.id, username_terpilih)
                except IntegrityError as error:
                    raise ValueError("Username sudah digunakan. Pilih username lain.") from error
            auth_queries.update_display_name(database, user.id, display_name)

        with room_service.lock:
            if username_berubah and room_service.current(user.username):
                raise ValueError("Keluar dari ruangan terlebih dahulu sebelum mengganti username.")
            self._jalankan_transaksi(simpan_nama_dan_username)
        return AuthenticatedUser(user.id, username_terpilih, display_name, user.skin_id)

    # Ubah skin pilihan pengguna; hanya skin dalam daftar yang diizinkan.
    def update_skin(self, user: AuthenticatedUser, skin_id: str) -> str:
        from app.module.skin_constants import ALL_SKINS

        if skin_id not in ALL_SKINS:
            raise ValueError(f"Skin tidak valid. Pilihan: {', '.join(ALL_SKINS)}")

        def simpan_skin(database):
            auth_queries.update_skin(database, user.id, skin_id)

        self._jalankan_transaksi(simpan_skin)
        return skin_id

    # Cabut token lewat transaksi database; token kosong tidak memerlukan operasi.
    def logout(self, token: str) -> None:
        if not token.strip():
            return

        def hapus_sesi(database: Session) -> None:
            auth_queries.delete_session(database, hashlib.sha256(token.encode("utf-8")).hexdigest())

        self._jalankan_transaksi(hapus_sesi)


auth_service = AuthService()

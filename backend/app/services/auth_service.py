"""Layanan login, pendaftaran, login Google, dan sesi: token buram yang disimpan di MySQL dan bisa dicabut.

DB hanya menyimpan hash SHA-256 token, bukan token asli. Waktu memakai UTC tanpa zona, karena kolom DATETIME MySQL tidak menyimpan zona waktu.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import secrets
from threading import RLock
import time

from google.auth.exceptions import GoogleAuthError, TransportError
from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2 import id_token
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config.database import jalankan_transaksi
from app.config.settings import settings
from app.models import auth_queries
from app.services.password_service import hash_password, verify_password

# Controller auth mengirim teks ini ke klien sebagai detail HTTP 503.
PESAN_LOGIN = "Layanan login sedang tidak tersedia."


class AuthenticationError(RuntimeError):
    """Login gagal tanpa mengungkap apakah akunnya ada."""


class SessionValidationError(RuntimeError):
    """Token bearer kosong, kedaluwarsa, atau sudah dicabut."""


class GoogleTidakTersedia(RuntimeError):
    """Login Google belum dikonfigurasi atau server Google belum bisa dihubungi."""


# Registrasi dan identitas federasi tidak pernah menggabungkan akun berdasarkan email.
class AccountConflict(ValueError):
    """Username/email sudah dipakai; jangan mengubah akun lama."""


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

        return jalankan_transaksi(periksa_akun_lalu_buat_sesi, PESAN_LOGIN)

    # Mengubah token dari browser menjadi data akun, dan menolak kalau tidak sah.
    # DB hanya menyimpan hash, jadi token asli tidak terbaca walau DB bocor.
    def check_user_by_token(self, token: str) -> AuthenticatedUser:
        if not token.strip():
            raise SessionValidationError("Sesi login tidak ditemukan.")

        akun = jalankan_transaksi(
            lambda database: auth_queries.account_by_token(
                database,
                hashlib.sha256(token.encode("utf-8")).hexdigest(),
                datetime.now(timezone.utc).replace(tzinfo=None),
            ),
            PESAN_LOGIN,
        )
        if akun is None:
            raise SessionValidationError("Sesi login sudah tidak valid.")
        return AuthenticatedUser(**akun)

    # Username hanya boleh berganti di luar ruangan; token tetap terkait ID akun yang sama.
    def update_profile(
        self, user: AuthenticatedUser, display_name: str, username: str | None = None
    ) -> AuthenticatedUser:
        from app.services.room_service import room_service

        username_terpilih = username or user.username
        username_berubah = username_terpilih != user.username
        if username_berubah:
            from app.services.user_service import validate_username

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
            jalankan_transaksi(simpan_nama_dan_username, PESAN_LOGIN)
        return AuthenticatedUser(user.id, username_terpilih, display_name, user.skin_id)

    # Ubah skin pilihan pengguna; hanya skin dalam daftar yang diizinkan.
    def update_skin(self, user: AuthenticatedUser, skin_id: str) -> str:
        from app.config.skins import ALL_SKINS

        if skin_id not in ALL_SKINS:
            raise ValueError(f"Skin tidak valid. Pilihan: {', '.join(ALL_SKINS)}")

        def simpan_skin(database):
            auth_queries.update_skin(database, user.id, skin_id)

        jalankan_transaksi(simpan_skin, PESAN_LOGIN)
        return skin_id

    # Cabut token lewat transaksi database; token kosong tidak memerlukan operasi.
    def logout(self, token: str) -> None:
        if not token.strip():
            return

        def hapus_sesi(database: Session) -> None:
            auth_queries.delete_session(database, hashlib.sha256(token.encode("utf-8")).hexdigest())

        jalankan_transaksi(hapus_sesi, PESAN_LOGIN)


auth_service = AuthService()


def issue_session(database, akun):
    """Buat sesi aplikasi biasa; token Google tidak disimpan."""
    if not akun["is_active"]:
        raise AuthenticationError("Akun tidak aktif.")
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
        token,
        waktu_kedaluwarsa.replace(tzinfo=timezone.utc),
        AuthenticatedUser(
            akun["id"],
            akun["username"],
            akun["display_name"],
            akun.get("skin_id") or "dexter",
        ),
    )


def register_account(username, password, display_name=None, email=None):
    """Simpan akun + email dalam satu transaksi dan login setelah pendaftaran."""
    from app.services.user_service import validate_username

    try:
        validate_username(username)
    except ValueError as error:
        raise AccountConflict("Username tidak tersedia.") from error
    hash_tersimpan = hash_password(password)
    nama_tampilan = display_name or username

    # Kerjakan perubahan akun dan penerbitan sesi dalam transaksi yang sama.
    def simpan_akun_lalu_buat_sesi(database):
        try:
            id_akun = auth_queries.create_account(
                database,
                username=username,
                display_name=nama_tampilan,
                password_hash=hash_tersimpan,
            )
            # Konfirmasi email di form hanya pencocokan, bukan bukti kepemilikan.
            if email:
                auth_queries.create_identity(database, id_akun, str(email).lower())
            return issue_session(
                database,
                {
                    "id": id_akun,
                    "username": username,
                    "display_name": nama_tampilan,
                    "is_active": True,
                },
            )
        except IntegrityError as error:
            database.rollback()
            raise AccountConflict("Username atau email sudah digunakan. Silakan login.") from error

    return jalankan_transaksi(simpan_akun_lalu_buat_sesi, PESAN_LOGIN)


def google_account(klaim):
    """Google sub adalah identitas utama. Email yang sama tidak otomatis mengambil alih akun."""

    # Kerjakan perubahan akun dan penerbitan sesi dalam transaksi yang sama.
    def cari_atau_buat_akun_lalu_buat_sesi(database):
        akun = auth_queries.account_by_google_subject(database, klaim["sub"])
        if akun:
            # Pertahankan nama profil pilihan pengguna saat login Google berikutnya.
            return issue_session(database, akun)
        try:
            # Username tidak berasal dari email dan tidak dapat bertabrakan dengan admin.
            username_acak = "google_" + secrets.token_hex(8)
            # Akun baru memakai nama dari identitas Google yang sudah diverifikasi.
            nama_tampilan = str(klaim.get("name") or "Detective")[:100]
            id_akun = auth_queries.create_account(
                database,
                username=username_acak,
                display_name=nama_tampilan,
                password_hash="google_only",
            )
            auth_queries.create_identity(database, id_akun, klaim["email"].lower(), klaim["sub"])
            return issue_session(
                database,
                {
                    "id": id_akun,
                    "username": username_acak,
                    "display_name": nama_tampilan,
                    "is_active": True,
                },
            )
        except IntegrityError as error:
            database.rollback()
            raise AccountConflict(
                "Email sudah terdaftar. Gunakan metode login awal; penautan akun belum tersedia."
            ) from error

    return jalankan_transaksi(cari_atau_buat_akun_lalu_buat_sesi, PESAN_LOGIN)


# Login Google memverifikasi ID token + nonce sekali pakai, bukan sekadar decode JWT.
class NonceStore:
    # Siapkan penyimpanan nonce sekali pakai dengan lock lintas thread.
    def __init__(self):
        self.values = OrderedDict()
        self.lock = RLock()

    # Bersihkan nonce lama lalu buat challenge acak yang berlaku lima menit.
    def issue(self):
        with self.lock:
            waktu_sekarang = time.monotonic()
            self.values = OrderedDict(
                (nonce_lama, batas_waktu)
                for nonce_lama, batas_waktu in self.values.items()
                if batas_waktu > waktu_sekarang
            )
            if len(self.values) >= 1000:
                self.values.popitem(last=False)
            nonce = secrets.token_urlsafe(32)
            self.values[nonce] = waktu_sekarang + 300
            return nonce

    # Ambil dan hapus nonce sekaligus; nonce kedaluwarsa atau berulang ditolak.
    def consume(self, nonce):
        with self.lock:
            return self.values.pop(nonce, 0) > time.monotonic()


nonces = NonceStore()


# Nonce sekali pakai untuk satu percobaan login Google.
def buat_nonce_google():
    if not settings.google_client_id.strip():
        raise GoogleTidakTersedia("Login Google belum dikonfigurasi.")
    return nonces.issue()


class BoundedGoogleRequest(GoogleRequest):
    # Library mengambil sertifikat Google; batasi waktu jaringan.
    def __call__(self, *args, **kwargs):
        kwargs["timeout"] = 8
        return super().__call__(*args, **kwargs)


# Habiskan nonce lalu verifikasi tanda tangan, audience, nonce, dan email Google.
def verify_google(credential, nonce):
    if not settings.google_client_id.strip():
        raise GoogleTidakTersedia("Login Google belum dikonfigurasi.")
    if not nonces.consume(nonce):
        raise AuthenticationError("Percobaan login kedaluwarsa. Muat ulang halaman.")
    try:
        klaim = id_token.verify_oauth2_token(
            credential, BoundedGoogleRequest(), settings.google_client_id
        )
        if (
            klaim.get("nonce") != nonce
            or not klaim.get("sub")
            or len(str(klaim["sub"])) > 255
            or klaim.get("email_verified") is not True
            or not isinstance(klaim.get("email"), str)
            or len(klaim["email"]) > 254
        ):
            raise ValueError("Invalid Google identity")
        return klaim
    # Issuer salah dilempar sebagai GoogleAuthError. TransportError turunannya, jadi harus lebih dulu.
    except TransportError as error:
        raise GoogleTidakTersedia("Google belum dapat dihubungi. Coba lagi.") from error
    except (ValueError, TypeError, GoogleAuthError) as error:
        raise AuthenticationError("Identitas Google tidak valid. Coba login ulang.") from error

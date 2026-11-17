"""Layanan login, pendaftaran, login Google, dan sesi: token buram yang disimpan di MySQL dan bisa dicabut.

DB hanya menyimpan hash SHA-256 token, bukan token asli. Waktu memakai UTC tanpa zona, karena kolom DATETIME MySQL tidak menyimpan zona waktu.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import lru_cache
import hashlib
import hmac
import logging
import secrets
from threading import RLock
import time

from google.auth.exceptions import GoogleAuthError, TransportError
from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2 import id_token
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config.database import PersistenceError, jalankan_transaksi
from app.config.settings import settings
from app.models import auth_queries
from app.schemas.auth import periksa_nama_tampilan
from app.services.password_service import hash_password, verify_password

# Controller auth mengirim teks ini ke klien sebagai detail HTTP 503.
PESAN_LOGIN = "Layanan login sedang tidak tersedia."
logger = logging.getLogger("shadow_heist.auth")


# Bersihkan sesi kedaluwarsa di transaksinya sendiri, sesudah login, daftar, atau login Google berhasil.
# Dipisah dari transaksi login supaya dua login bersamaan tidak saling mengunci. Gagal membersihkan tidak
# menggagalkan login: sesi kedaluwarsa memang sudah ditolak saat token dicek, dan dibersihkan login berikutnya.
# Alur: 1 hapus sesi yang expires_at-nya lewat -> 2 gagal: catat di log, login tetap berhasil
def bersihkan_sesi_kedaluwarsa() -> None:
    try:
        jalankan_transaksi(
            lambda database: auth_queries.delete_expired_sessions(
                database, datetime.now(timezone.utc).replace(tzinfo=None)
            ),
            PESAN_LOGIN,
        )
    except PersistenceError:
        logger.warning("Sesi kedaluwarsa belum terhapus; dicoba lagi pada login berikutnya.")


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


# Hash pembanding untuk akun yang tidak ada, nonaktif, atau khusus Google. Dihitung sekali saat pertama dibutuhkan.
@lru_cache(maxsize=1)
def hash_tiruan() -> str:
    return hash_password(secrets.token_urlsafe(16))


class AuthService:
    """Memeriksa kredensial serta membuat dan mencabut sesi di database."""

    # Normalisasi username, verifikasi akun dan password, lalu buat sesi dengan masa berlaku.
    # Alur: 1 cari akun lewat username atau email terverifikasi -> 2 hitung hash password; akun yang tidak bisa login
    #       dengan password memakai hash tiruan, jadi lama respons tidak membocorkan akun ada atau tidak -> 3 buat sesi
    def login(self, *, username: str, password: str) -> LoginResult:
        username_bersih = username.strip()

        # Hanya hash token yang disimpan; token asli dikembalikan sekali ini ke klien.
        def periksa_akun_lalu_buat_sesi(database: Session) -> LoginResult:
            akun = auth_queries.account_by_login(database, username_bersih)
            bisa_login = (
                akun is not None
                and akun["is_active"]
                and akun["password_hash"].startswith("pbkdf2_sha256$")
            )
            password_cocok = verify_password(
                password, akun["password_hash"] if bisa_login else hash_tiruan()
            )
            if not (bisa_login and password_cocok):
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

        hasil = jalankan_transaksi(periksa_akun_lalu_buat_sesi, PESAN_LOGIN)
        bersihkan_sesi_kedaluwarsa()
        return hasil

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

        # Nama dan username harus disimpan bersama; benturan username membatalkan seluruh perubahan. Username yang masih
        # punya riwayat pertandingan atau survei (milik akun lain atau akun yang sudah dihapus) tidak boleh dipakai.
        def simpan_nama_dan_username(database):
            if username_berubah:
                if auth_queries.username_punya_riwayat(database, username_terpilih):
                    raise ValueError("Username tersebut tidak tersedia.")
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


# Email dari form daftar tidak pernah dibuktikan miliknya, jadi tidak disimpan: tidak bisa dipakai login dan tidak
# memblokir login Google pemilik aslinya.
def register_account(username, password, display_name=None):
    """Simpan akun dalam satu transaksi dan login setelah pendaftaran."""
    from app.services.user_service import validate_username

    try:
        validate_username(username)
    except ValueError as error:
        raise AccountConflict("Username tidak tersedia.") from error
    hash_tersimpan = hash_password(password)
    nama_tampilan = display_name or username

    # Kerjakan perubahan akun dan penerbitan sesi dalam transaksi yang sama. Username yang masih punya riwayat
    # pertandingan atau survei ditolak, supaya pendaftar baru tidak mewarisi survei milik orang lain.
    def simpan_akun_lalu_buat_sesi(database):
        if auth_queries.username_punya_riwayat(database, username):
            raise AccountConflict("Username tidak tersedia.")
        try:
            id_akun = auth_queries.create_account(
                database,
                username=username,
                display_name=nama_tampilan,
                password_hash=hash_tersimpan,
            )
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
            raise AccountConflict("Username sudah digunakan. Silakan login.") from error

    hasil = jalankan_transaksi(simpan_akun_lalu_buat_sesi, PESAN_LOGIN)
    bersihkan_sesi_kedaluwarsa()
    return hasil


# Nama tampilan akun Google baru: nama dari Google bila lolos aturan yang sama dengan form (tanpa karakter kontrol atau
# pembalik arah, ada huruf/angka, bukan kata ganti atau istilah game); selain itu "Detective".
def nama_dari_google(klaim):
    try:
        return periksa_nama_tampilan(str(klaim.get("name") or ""))[:100].strip()
    except ValueError:
        return "Detective"


def google_account(klaim):
    """Google sub adalah identitas utama. Akun lama tidak pernah diambil alih lewat kesamaan email."""

    # Kerjakan perubahan akun dan penerbitan sesi dalam transaksi yang sama.
    # Alur: 1 Google sub sudah dikenal: buat sesi -> 2 lepas email yang sama dari identitas lama yang belum
    #       terverifikasi -> 3 buat akun Google baru beserta identitasnya -> 4 buat sesi
    def cari_atau_buat_akun_lalu_buat_sesi(database):
        akun = auth_queries.account_by_google_subject(database, klaim["sub"])
        if akun:
            # Pertahankan nama profil pilihan pengguna saat login Google berikutnya.
            return issue_session(database, akun)
        email = klaim["email"].lower()
        # Email itu dulu diketik di form daftar tanpa bukti kepemilikan. Akun lamanya tetap ada dan tetap bisa login
        # dengan username; hanya emailnya yang dilepas, supaya pemilik yang sudah dibuktikan Google tidak ditolak.
        auth_queries.delete_unverified_identity(database, email)
        try:
            # Username tidak berasal dari email dan tidak dapat bertabrakan dengan admin.
            username_acak = "google_" + secrets.token_hex(8)
            nama_tampilan = nama_dari_google(klaim)
            id_akun = auth_queries.create_account(
                database,
                username=username_acak,
                display_name=nama_tampilan,
                password_hash="google_only",
            )
            auth_queries.create_identity(database, id_akun, email, klaim["sub"])
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

    hasil = jalankan_transaksi(cari_atau_buat_akun_lalu_buat_sesi, PESAN_LOGIN)
    bersihkan_sesi_kedaluwarsa()
    return hasil


# Login Google memverifikasi ID token + nonce sekali pakai, bukan sekadar decode JWT. Nonce ditandatangani (HMAC dengan
# kunci acak proses ini) dan membawa batas waktunya sendiri, jadi menerbitkan nonce tidak mengisi memori dan banjir
# /google/challenge tidak bisa menggusur nonce pemain lain. Yang diingat hanya nonce yang sudah dipakai, sampai batas
# waktunya lewat, untuk menolak pemakaian ulang.
class NonceStore:
    BERLAKU_DETIK = 300
    MAKS_TERPAKAI = 10000

    # Siapkan kunci tanda tangan dan catatan nonce terpakai dengan lock lintas thread.
    def __init__(self):
        self.kunci = secrets.token_bytes(32)
        self.terpakai = OrderedDict()
        self.lock = RLock()

    # Tanda tangan isi nonce (batas waktu dan bagian acak).
    def _tanda(self, isi):
        return hmac.new(self.kunci, isi.encode("utf-8"), hashlib.sha256).hexdigest()

    # Challenge baru "batas_waktu.acak.tanda" yang berlaku lima menit.
    def issue(self):
        isi = f"{int(time.monotonic()) + self.BERLAKU_DETIK}.{secrets.token_urlsafe(16)}"
        return f"{isi}.{self._tanda(isi)}"

    # Nonce sah sekali pakai: tanda tangan cocok, belum kedaluwarsa, dan belum pernah dipakai.
    # Alur: 1 cek tanda tangan dan batas waktu -> 2 buang catatan yang sudah kedaluwarsa -> 3 tolak bila sudah dipakai
    #       -> 4 catat sebagai terpakai
    def consume(self, nonce):
        isi, _, tanda = str(nonce).rpartition(".")
        try:
            batas_waktu = int(isi.split(".", 1)[0])
        except ValueError:
            return False
        waktu_sekarang = time.monotonic()
        tanda_benar = self._tanda(isi).encode()
        if not hmac.compare_digest(tanda.encode(), tanda_benar) or batas_waktu <= waktu_sekarang:
            return False
        with self.lock:
            while self.terpakai and next(iter(self.terpakai.values())) <= waktu_sekarang:
                self.terpakai.popitem(last=False)
            if nonce in self.terpakai:
                return False
            self.terpakai[nonce] = batas_waktu
            while len(self.terpakai) > self.MAKS_TERPAKAI:
                self.terpakai.popitem(last=False)
            return True


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

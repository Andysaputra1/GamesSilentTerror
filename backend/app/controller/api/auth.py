"""Controller HTTP untuk login, pendaftaran akun, dan verifikasi identitas Google."""

from collections import OrderedDict
from datetime import datetime, timedelta, timezone
import hashlib
import secrets
from threading import RLock
import time

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from google.auth.exceptions import TransportError
from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2 import id_token
from sqlalchemy.exc import IntegrityError

from app.controller.middleware.auth import require_authenticated_user
from app.schemas.auth import (
    AuthenticatedUserResponse,
    GoogleLoginRequest,
    LoginRequest,
    LoginResponse,
    RegisterRequest,
    UpdateProfileRequest,
    UpdateSkinRequest,
)
from app.config.settings import settings
from app.controller.middleware.auth_limits import limit_auth
from app.controller.middleware.safe_validation import SafeValidationRoute
from app.models import auth_queries
from app.module.auth_service import (
    AuthenticatedUser,
    AuthenticationError,
    LoginResult,
    PESAN_LOGIN,
    auth_service,
)
from app.module.mysql_connector import PersistenceError, jalankan_transaksi
from app.module.password_service import hash_password

router = APIRouter(prefix="/api/auth", tags=["auth"], route_class=SafeValidationRoute)
_skema_bearer = HTTPBearer(auto_error=False)


# Data pengguna yang boleh dikirim ke klien.
def _buat_respons_pengguna(user: AuthenticatedUser) -> AuthenticatedUserResponse:
    return AuthenticatedUserResponse(
        username=user.username,
        display_name=user.display_name,
        skin_id=user.skin_id,
    )


# Bentuk respons yang sama untuk login, pendaftaran, dan login Google.
def _buat_respons_login(hasil_login: LoginResult) -> LoginResponse:
    return LoginResponse(
        access_token=hasil_login.access_token,
        expires_at=hasil_login.expires_at,
        user=_buat_respons_pengguna(hasil_login.user),
    )


# Minta service memeriksa akun dan membuat sesi; kembalikan token atau error HTTP.
@router.post("/login", response_model=LoginResponse, dependencies=[Depends(limit_auth)])
def login(body: LoginRequest) -> LoginResponse:
    """Create a short-lived opaque session after validating credentials."""
    try:
        hasil_login = auth_service.login(username=body.username, password=body.password)
    except AuthenticationError as error:
        raise HTTPException(status_code=401, detail=str(error)) from error
    except PersistenceError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    return _buat_respons_login(hasil_login)


# Kembalikan username dan nama tampilan pengguna yang sudah lolos autentikasi.
@router.get("/me", response_model=AuthenticatedUserResponse)
def current_user(
    user: AuthenticatedUser = Depends(require_authenticated_user),
) -> AuthenticatedUserResponse:
    return _buat_respons_pengguna(user)


# Akun yang diubah berasal dari bearer token; username baru tidak dapat memilih akun lain.
@router.post("/me", response_model=AuthenticatedUserResponse)
def update_profile(
    body: UpdateProfileRequest,
    response: Response,
    user: AuthenticatedUser = Depends(require_authenticated_user),
) -> AuthenticatedUserResponse:
    response.headers["Cache-Control"] = "no-store"
    try:
        pengguna_terbaru = auth_service.update_profile(user, body.display_name, body.username)
    except ValueError as error:
        raise HTTPException(409, str(error)) from error
    except PersistenceError as error:
        raise HTTPException(503, "Nama belum berhasil disimpan. Coba lagi nanti.") from error
    return _buat_respons_pengguna(pengguna_terbaru)


# Ubah skin pilihan dari token autentikasi; user tidak bisa mengubah skin user lain.
@router.put("/skin")
def update_skin(
    body: UpdateSkinRequest,
    user: AuthenticatedUser = Depends(require_authenticated_user),
):
    try:
        skin_id = auth_service.update_skin(user, body.skin_id)
    except ValueError as error:
        raise HTTPException(400, str(error)) from error
    except PersistenceError as error:
        raise HTTPException(503, "Skin gagal disimpan. Coba lagi.") from error
    return {"skin_id": skin_id}


# Cabut sesi bearer yang diberikan; error database diterjemahkan menjadi HTTP 503.
@router.post("/logout", status_code=204)
def logout(
    kredensial: HTTPAuthorizationCredentials | None = Depends(_skema_bearer),
) -> None:
    if kredensial is not None and kredensial.scheme.lower() == "bearer":
        try:
            auth_service.logout(kredensial.credentials)
        except PersistenceError as error:
            raise HTTPException(status_code=503, detail=str(error)) from error


# Terjemahkan kegagalan tanpa memuat password/token dalam detail error.
def _jalankan_operasi_akun(operasi):
    try:
        hasil_login = operasi()
    except AccountConflict as error:
        raise HTTPException(409, str(error)) from error
    except AuthenticationError as error:
        raise HTTPException(401, str(error)) from error
    except PersistenceError as error:
        raise HTTPException(503, str(error)) from error
    return _buat_respons_login(hasil_login)


# Daftarkan akun dan terbitkan sesi; respons autentikasi tidak boleh di-cache.
@router.post(
    "/register", response_model=LoginResponse, status_code=201, dependencies=[Depends(limit_auth)]
)
def register(body: RegisterRequest, response: Response):
    response.headers["Cache-Control"] = "no-store"
    return _jalankan_operasi_akun(lambda: register_account(body))


# Kirim client ID publik agar browser dapat menyiapkan tombol Google.
@router.get("/google/config")
def google_config(response: Response):
    response.headers["Cache-Control"] = "no-store"
    return {"client_id": settings.google_client_id.strip()}


# Validasi origin lalu buat nonce sekali pakai untuk percobaan login Google.
@router.post("/google/challenge", dependencies=[Depends(limit_auth)])
def google_challenge(request: Request, response: Response):
    validate_google_origin(request)
    if not settings.google_client_id.strip():
        raise HTTPException(503, "Login Google belum dikonfigurasi.")
    response.headers["Cache-Control"] = "no-store"
    return {"nonce": nonces.issue()}


# Tolak login Google dari origin yang tidak diizinkan backend.
def validate_google_origin(request):
    # Callback JS mengirim JSON, bukan auto POST form GIS. Tolak origin lain.
    if request.headers.get("origin") not in settings.allowed_origins:
        raise HTTPException(403, "Origin login tidak diizinkan.")


# Verifikasi origin, token, dan nonce Google sebelum membuat sesi aplikasi.
@router.post("/google", response_model=LoginResponse, dependencies=[Depends(limit_auth)])
def google_login(body: GoogleLoginRequest, request: Request, response: Response):
    validate_google_origin(request)
    response.headers["Cache-Control"] = "no-store"
    return _jalankan_operasi_akun(
        lambda: google_account(verify_google(body.credential, body.nonce))
    )


# Registrasi dan identitas federasi tidak pernah menggabungkan akun berdasarkan email.
class AccountConflict(ValueError):
    """Username/email sudah dipakai; jangan mengubah akun lama."""


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


def register_account(body):
    """Simpan akun + email dalam satu transaksi dan login setelah pendaftaran."""
    from app.module.user_management_service import validate_username

    try:
        validate_username(body.username)
    except ValueError as error:
        raise AccountConflict("Username tidak tersedia.") from error
    hash_tersimpan = hash_password(body.password)
    nama_tampilan = body.display_name or body.username

    # Kerjakan perubahan akun dan penerbitan sesi dalam transaksi yang sama.
    def simpan_akun_lalu_buat_sesi(database):
        try:
            id_akun = auth_queries.create_account(
                database,
                username=body.username,
                display_name=nama_tampilan,
                password_hash=hash_tersimpan,
            )
            # Konfirmasi email di form hanya pencocokan, bukan bukti kepemilikan.
            if body.email:
                auth_queries.create_identity(database, id_akun, str(body.email).lower())
            return issue_session(
                database,
                {
                    "id": id_akun,
                    "username": body.username,
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


class BoundedGoogleRequest(GoogleRequest):
    # Library mengambil sertifikat Google; batasi waktu jaringan.
    def __call__(self, *args, **kwargs):
        kwargs["timeout"] = 8
        return super().__call__(*args, **kwargs)


# Habiskan nonce lalu verifikasi tanda tangan, audience, nonce, dan email Google.
def verify_google(credential, nonce):
    if not settings.google_client_id.strip():
        raise HTTPException(503, "Login Google belum dikonfigurasi.")
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
    except (ValueError, TypeError) as error:
        raise AuthenticationError("Identitas Google tidak valid. Coba login ulang.") from error
    except TransportError as error:
        raise HTTPException(503, "Google belum dapat dihubungi. Coba lagi.") from error

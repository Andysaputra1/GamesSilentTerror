"""Authentication HTTP controllers, account registration, and Google identity verification."""

from collections import OrderedDict
from datetime import timedelta, timezone
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
from app.schemas.auth import AuthenticatedUserResponse, LoginRequest, LoginResponse
from app.schemas.auth import (
    RegisterRequest,
    GoogleLoginRequest,
    UpdateProfileRequest,
    UpdateSkinRequest,
)
from app.config.settings import settings
from app.controller.middleware.auth_limits import limit_auth
from app.models import auth_queries
from app.module.auth_service import (
    AuthenticatedUser,
    AuthenticationError,
    AuthenticationPersistenceError,
    LoginResult,
    auth_service,
    _token_hash,
    _utc_now,
)
from app.module.password_service import hash_password

router = APIRouter(prefix="/api/auth", tags=["auth"])
_bearer_scheme = HTTPBearer(auto_error=False)


@router.post("/login", response_model=LoginResponse, dependencies=[Depends(limit_auth)])
# CONTROLLER LOGIN: minta service memeriksa akun dan membuat sesi; kembalikan token atau error HTTP.
def login(request: LoginRequest) -> LoginResponse:
    """Create a short-lived opaque session after validating credentials."""
    try:
        result = auth_service.login(username=request.username, password=request.password)
    except AuthenticationError as error:
        raise HTTPException(status_code=401, detail=str(error)) from error
    except AuthenticationPersistenceError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    return LoginResponse(
        access_token=result.access_token,
        expires_at=result.expires_at,
        user=AuthenticatedUserResponse(
            username=result.user.username,
            display_name=result.user.display_name,
            skin_id=result.user.skin_id,
        ),
    )


@router.get("/me", response_model=AuthenticatedUserResponse)
# CONTROLLER PROFIL: kembalikan username dan nama tampilan pengguna yang sudah lolos autentikasi.
def current_user(
    user: AuthenticatedUser = Depends(require_authenticated_user),
) -> AuthenticatedUserResponse:
    return AuthenticatedUserResponse(
        username=user.username,
        display_name=user.display_name,
        skin_id=user.skin_id,
    )


# Akun yang diubah berasal dari bearer token; username baru tidak dapat memilih akun lain.
@router.post("/me", response_model=AuthenticatedUserResponse)
def update_profile(
    body: UpdateProfileRequest,
    response: Response,
    user: AuthenticatedUser = Depends(require_authenticated_user),
) -> AuthenticatedUserResponse:
    response.headers["Cache-Control"] = "no-store"
    try:
        updated = auth_service.update_profile(user, body.display_name, body.username)
    except ValueError as error:
        raise HTTPException(409, str(error)) from error
    except AuthenticationPersistenceError as error:
        raise HTTPException(503, "Nama belum berhasil disimpan. Coba lagi nanti.") from error
    return AuthenticatedUserResponse(
        username=updated.username,
        display_name=updated.display_name,
        skin_id=updated.skin_id,
    )


@router.put("/skin")
# CONTROLLER: ubah skin preference dari token autentikasi; user tidak bisa mengubah skin user lain.
def update_skin(
    body: UpdateSkinRequest,
    user: AuthenticatedUser = Depends(require_authenticated_user),
):
    try:
        skin_id = auth_service.update_skin(user, body.skin_id)
    except ValueError as error:
        raise HTTPException(400, str(error)) from error
    except AuthenticationPersistenceError as error:
        raise HTTPException(503, "Skin gagal disimpan. Coba lagi.") from error
    return {"skin_id": skin_id}


@router.post("/logout", status_code=204)
# CONTROLLER LOGOUT: cabut sesi bearer yang diberikan; error database diterjemahkan menjadi HTTP 503.
def logout(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> None:
    if credentials is not None and credentials.scheme.lower() == "bearer":
        try:
            auth_service.logout(credentials.credentials)
        except AuthenticationPersistenceError as error:
            raise HTTPException(status_code=503, detail=str(error)) from error


def account_response(operation):
    """Terjemahkan kegagalan tanpa memuat password/token dalam detail error."""
    try:
        result = operation()
    except AccountConflict as error:
        raise HTTPException(409, str(error)) from error
    except AuthenticationError as error:
        raise HTTPException(401, str(error)) from error
    except AuthenticationPersistenceError as error:
        raise HTTPException(503, str(error)) from error
    return LoginResponse(
        access_token=result.access_token,
        expires_at=result.expires_at,
        user=AuthenticatedUserResponse(
            username=result.user.username,
            display_name=result.user.display_name,
            skin_id=result.user.skin_id,
        ),
    )


# Daftarkan akun dan terbitkan sesi; respons autentikasi tidak boleh di-cache.
@router.post(
    "/register", response_model=LoginResponse, status_code=201, dependencies=[Depends(limit_auth)]
)
def register(body: RegisterRequest, response: Response):
    response.headers["Cache-Control"] = "no-store"
    return account_response(lambda: register_account(body))


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
    return account_response(lambda: google_account(verify_google(body.credential, body.nonce)))


# AKUN: registrasi dan identitas federasi. Tidak pernah menggabungkan akun berdasarkan email.
class AccountConflict(ValueError):
    """Username/email sudah dipakai; jangan mengubah akun lama."""


def issue_session(database, account):
    """Buat sesi aplikasi biasa; token Google tidak disimpan."""
    if not account["is_active"]:
        raise AuthenticationError("Akun tidak aktif.")
    token = secrets.token_urlsafe(32)
    expires = _utc_now() + timedelta(hours=settings.auth_session_hours)
    auth_queries.create_session(
        database, user_id=account["id"], token_hash=_token_hash(token), expires_at=expires
    )
    return LoginResult(
        token,
        expires.replace(tzinfo=timezone.utc),
        AuthenticatedUser(
            account["id"],
            account["username"],
            account["display_name"],
            account.get("skin_id") or "dexter",
        ),
    )


def register_account(body):
    """Simpan akun + email dalam satu transaksi dan login setelah pendaftaran."""
    from app.module.user_management_service import validate_username

    try:
        validate_username(body.username)
    except ValueError as error:
        raise AccountConflict("Username tidak tersedia.") from error
    password_hash = hash_password(body.password)

    # Kerjakan perubahan akun dan penerbitan sesi dalam transaksi yang sama.
    def operation(database):
        try:
            user_id = auth_queries.create_account(
                database,
                username=body.username,
                display_name=body.display_name or body.username,
                password_hash=password_hash,
            )
            # Konfirmasi email di form hanya pencocokan, bukan bukti kepemilikan.
            if body.email:
                auth_queries.create_identity(database, user_id, str(body.email).lower())
            return issue_session(
                database,
                {
                    "id": user_id,
                    "username": body.username,
                    "display_name": body.display_name or body.username,
                    "is_active": True,
                },
            )
        except IntegrityError as error:
            database.rollback()
            raise AccountConflict("Username atau email sudah digunakan. Silakan login.") from error

    return auth_service._transaction(operation)


def google_account(claims):
    """Google sub adalah identitas utama. Email yang sama tidak otomatis mengambil alih akun."""

    # Kerjakan perubahan akun dan penerbitan sesi dalam transaksi yang sama.
    def operation(database):
        account = auth_queries.account_by_google_subject(database, claims["sub"])
        if account:
            # Pertahankan nama profil pilihan pengguna saat login Google berikutnya.
            return issue_session(database, account)
        try:
            # Username tidak berasal dari email dan tidak dapat bertabrakan dengan admin.
            username = "google_" + secrets.token_hex(8)
            # Akun baru memakai nama dari identitas Google yang sudah diverifikasi.
            display_name = str(claims.get("name") or "Detective")[:100]
            user_id = auth_queries.create_account(
                database, username=username, display_name=display_name, password_hash="google_only"
            )
            auth_queries.create_identity(database, user_id, claims["email"].lower(), claims["sub"])
            return issue_session(
                database,
                {
                    "id": user_id,
                    "username": username,
                    "display_name": display_name,
                    "is_active": True,
                },
            )
        except IntegrityError as error:
            database.rollback()
            raise AccountConflict(
                "Email sudah terdaftar. Gunakan metode login awal; penautan akun belum tersedia."
            ) from error

    return auth_service._transaction(operation)


# LOGIN GOOGLE: verifikasi ID token Google + nonce sekali pakai, bukan sekadar decode JWT.
class NonceStore:
    # Siapkan penyimpanan nonce sekali pakai dengan lock lintas thread.
    def __init__(self):
        self.values = OrderedDict()
        self.lock = RLock()

    # Bersihkan nonce lama lalu buat challenge acak yang berlaku lima menit.
    def issue(self):
        with self.lock:
            now = time.monotonic()
            self.values = OrderedDict((k, v) for k, v in self.values.items() if v > now)
            if len(self.values) >= 1000:
                self.values.popitem(last=False)
            nonce = secrets.token_urlsafe(32)
            self.values[nonce] = now + 300
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
        raise AuthenticationPersistenceError("Login Google belum dikonfigurasi.")
    if not nonces.consume(nonce):
        raise AuthenticationError("Percobaan login kedaluwarsa. Muat ulang halaman.")
    try:
        claims = id_token.verify_oauth2_token(
            credential, BoundedGoogleRequest(), settings.google_client_id
        )
        if (
            claims.get("nonce") != nonce
            or not claims.get("sub")
            or len(str(claims["sub"])) > 255
            or claims.get("email_verified") is not True
            or not isinstance(claims.get("email"), str)
            or len(claims["email"]) > 254
        ):
            raise ValueError("Invalid Google identity")
        return claims
    except (ValueError, TypeError) as error:
        raise AuthenticationError("Identitas Google tidak valid. Coba login ulang.") from error
    except TransportError as error:
        raise AuthenticationPersistenceError("Google belum dapat dihubungi. Coba lagi.") from error

"""Controller HTTP untuk login, pendaftaran akun, dan verifikasi identitas Google."""

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.middleware.auth import require_authenticated_user
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
from app.middleware.auth_limits import limit_auth
from app.middleware.safe_validation import SafeValidationRoute
from app.services.auth_service import (
    AccountConflict,
    AuthenticatedUser,
    AuthenticationError,
    GoogleTidakTersedia,
    LoginResult,
    auth_service,
    buat_nonce_google,
    google_account,
    register_account,
    verify_google,
)
from app.config.database import PersistenceError

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
    except (GoogleTidakTersedia, PersistenceError) as error:
        raise HTTPException(503, str(error)) from error
    return _buat_respons_login(hasil_login)


# Daftarkan akun dan terbitkan sesi; respons autentikasi tidak boleh di-cache.
@router.post(
    "/register", response_model=LoginResponse, status_code=201, dependencies=[Depends(limit_auth)]
)
def register(body: RegisterRequest, response: Response):
    response.headers["Cache-Control"] = "no-store"
    return _jalankan_operasi_akun(
        lambda: register_account(body.username, body.password, body.display_name, body.email)
    )


# Kirim client ID publik agar browser dapat menyiapkan tombol Google.
@router.get("/google/config")
def google_config(response: Response):
    response.headers["Cache-Control"] = "no-store"
    return {"client_id": settings.google_client_id.strip()}


# Tolak login Google dari origin yang tidak diizinkan backend.
def validate_google_origin(request):
    # Callback JS mengirim JSON, bukan auto POST form GIS. Tolak origin lain.
    if request.headers.get("origin") not in settings.allowed_origins:
        raise HTTPException(403, "Origin login tidak diizinkan.")


# Validasi origin lalu buat nonce sekali pakai untuk percobaan login Google.
@router.post("/google/challenge", dependencies=[Depends(limit_auth)])
def google_challenge(request: Request, response: Response):
    validate_google_origin(request)
    try:
        nonce = buat_nonce_google()
    except GoogleTidakTersedia as error:
        raise HTTPException(503, str(error)) from error
    response.headers["Cache-Control"] = "no-store"
    return {"nonce": nonce}


# Verifikasi origin, token, dan nonce Google sebelum membuat sesi aplikasi.
@router.post("/google", response_model=LoginResponse, dependencies=[Depends(limit_auth)])
def google_login(body: GoogleLoginRequest, request: Request, response: Response):
    validate_google_origin(request)
    response.headers["Cache-Control"] = "no-store"
    return _jalankan_operasi_akun(
        lambda: google_account(verify_google(body.credential, body.nonce))
    )

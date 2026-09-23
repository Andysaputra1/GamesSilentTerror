"""Authentication HTTP controllers."""

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from controller.middleware.auth import require_authenticated_user
from schemas.auth import AuthenticatedUserResponse, LoginRequest, LoginResponse
from schemas.auth import RegisterRequest, GoogleLoginRequest
from config.settings import settings
from controller.middleware.auth_limits import limit_auth
from services.account_service import register_account, google_account, AccountConflict
from services.google_identity_service import verify_google, nonces
from services.auth_service import (
    AuthenticatedUser,
    AuthenticationError,
    AuthenticationPersistenceError,
    auth_service,
)


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
        ),
    )


@router.get("/me", response_model=AuthenticatedUserResponse)
# CONTROLLER PROFIL: kembalikan username dan nama tampilan pengguna yang sudah lolos autentikasi.
def current_user(
    user: AuthenticatedUser = Depends(require_authenticated_user),
) -> AuthenticatedUserResponse:
    return AuthenticatedUserResponse(username=user.username, display_name=user.display_name)


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
    return LoginResponse(access_token=result.access_token, expires_at=result.expires_at,
        user=AuthenticatedUserResponse(username=result.user.username, display_name=result.user.display_name))


@router.post('/register', response_model=LoginResponse, status_code=201, dependencies=[Depends(limit_auth)])
def register(body: RegisterRequest, response: Response):
    response.headers['Cache-Control'] = 'no-store'
    return account_response(lambda: register_account(body))


@router.get('/google/config')
def google_config(response: Response):
    response.headers['Cache-Control'] = 'no-store'
    return {'client_id': settings.google_client_id.strip()}


@router.post('/google/challenge', dependencies=[Depends(limit_auth)])
def google_challenge(request: Request, response: Response):
    validate_google_origin(request)
    if not settings.google_client_id.strip():
        raise HTTPException(503, 'Login Google belum dikonfigurasi.')
    response.headers['Cache-Control'] = 'no-store'
    return {'nonce': nonces.issue()}


def validate_google_origin(request):
    # Callback JS mengirim JSON, bukan auto POST form GIS. Tolak origin lain.
    if request.headers.get('origin') not in settings.allowed_origins:
        raise HTTPException(403, 'Origin login tidak diizinkan.')


@router.post('/google', response_model=LoginResponse, dependencies=[Depends(limit_auth)])
def google_login(body: GoogleLoginRequest, request: Request, response: Response):
    validate_google_origin(request)
    response.headers['Cache-Control'] = 'no-store'
    return account_response(lambda: google_account(verify_google(body.credential, body.nonce)))

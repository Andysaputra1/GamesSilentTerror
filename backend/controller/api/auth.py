"""Authentication HTTP controllers."""

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from controller.middleware.auth import require_authenticated_user
from schemas.auth import AuthenticatedUserResponse, LoginRequest, LoginResponse
from services.auth_service import (
    AuthenticatedUser,
    AuthenticationError,
    AuthenticationPersistenceError,
    auth_service,
)


router = APIRouter(prefix="/api/auth", tags=["auth"])
_bearer_scheme = HTTPBearer(auto_error=False)


@router.post("/login", response_model=LoginResponse)
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

"""Dependency bersama untuk controller HTTP."""

from fastapi import HTTPException, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.module.auth_service import (
    AuthenticatedUser,
    AuthenticationPersistenceError,
    SessionValidationError,
    auth_service,
)

_skema_bearer = HTTPBearer(auto_error=False)


# Validasi bearer token lewat service sebelum endpoint dijalankan; gagal menjadi HTTP 401/503.
def require_authenticated_user(
    kredensial: HTTPAuthorizationCredentials | None = Security(_skema_bearer),
) -> AuthenticatedUser:
    if kredensial is None or kredensial.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="Login diperlukan.")
    try:
        return auth_service.user_for_token(kredensial.credentials)
    except SessionValidationError as error:
        raise HTTPException(status_code=401, detail=str(error)) from error
    except AuthenticationPersistenceError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error

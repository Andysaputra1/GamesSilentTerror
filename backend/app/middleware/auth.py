"""Dependency bersama untuk controller HTTP."""

from fastapi import HTTPException, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.services.auth_service import (
    AuthenticatedUser,
    SessionValidationError,
    auth_service,
)
from app.config.database import PersistenceError

_skema_bearer = HTTPBearer(auto_error=False)


# Validasi bearer token lewat service sebelum endpoint dijalankan; gagal menjadi HTTP 401/503.
def require_authenticated_user(
    kredensial: HTTPAuthorizationCredentials | None = Security(_skema_bearer),
) -> AuthenticatedUser:
    if kredensial is None or kredensial.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="Login diperlukan.")
    try:
        return auth_service.check_user_by_token(kredensial.credentials)
    except SessionValidationError as error:
        raise HTTPException(status_code=401, detail=str(error)) from error
    except PersistenceError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error

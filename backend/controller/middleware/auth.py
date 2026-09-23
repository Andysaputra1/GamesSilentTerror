"""Shared HTTP-controller dependencies."""

from fastapi import HTTPException, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from services.auth_service import (
    AuthenticatedUser,
    AuthenticationPersistenceError,
    SessionValidationError,
    auth_service,
)

_bearer_scheme = HTTPBearer(auto_error=False)


# DEPENDENCY AUTH: validasi bearer token lewat service sebelum endpoint dijalankan; gagal menjadi HTTP 401/503.
def require_authenticated_user(
    credentials: HTTPAuthorizationCredentials | None = Security(_bearer_scheme),
) -> AuthenticatedUser:
    """Validate the bearer token before accessing a protected API route."""
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="Login diperlukan.")
    try:
        return auth_service.user_for_token(credentials.credentials)
    except SessionValidationError as error:
        raise HTTPException(status_code=401, detail=str(error)) from error
    except AuthenticationPersistenceError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error

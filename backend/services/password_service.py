"""Password hashing helpers using only Python's standard library."""

from __future__ import annotations

import hashlib
import hmac
import secrets

_ALGORITHM = "sha256"
_ITERATIONS = 600_000
_SCHEME = "pbkdf2_sha256"


# FUNCTION HASH: buat hash PBKDF2-SHA256 dengan salt acak; password asli tidak disimpan.
def hash_password(password: str) -> str:
    """Create a salted PBKDF2-SHA256 password hash for a new account."""
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(_ALGORITHM, password.encode("utf-8"), salt, _ITERATIONS)
    return f"{_SCHEME}${_ITERATIONS}${salt.hex()}${digest.hex()}"


# FUNCTION VERIFIKASI: hitung ulang hash password dan bandingkan digest dengan compare_digest; format rusak menghasilkan False.
def verify_password(password: str, encoded_hash: str) -> bool:
    """Compare a password against a PBKDF2 hash without timing leaks."""
    try:
        scheme, iterations, salt_hex, expected_digest = encoded_hash.split("$", 3)
        if scheme != _SCHEME:
            return False
        digest = hashlib.pbkdf2_hmac(
            _ALGORITHM,
            password.encode("utf-8"),
            bytes.fromhex(salt_hex),
            int(iterations),
        ).hex()
        return hmac.compare_digest(digest, expected_digest)
    except (TypeError, ValueError):
        return False

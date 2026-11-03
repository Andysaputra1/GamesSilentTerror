"""Hash dan verifikasi password memakai pustaka standar Python saja."""

from __future__ import annotations

import hashlib
import hmac
import secrets

_ALGORITHM = "sha256"
_ITERATIONS = 600_000
_SCHEME = "pbkdf2_sha256"


# Buat hash PBKDF2-SHA256 dengan salt acak; password asli tidak disimpan.
def hash_password(password: str) -> str:
    salt_acak = secrets.token_bytes(16)
    hash_baru = hashlib.pbkdf2_hmac(_ALGORITHM, password.encode("utf-8"), salt_acak, _ITERATIONS)
    return f"{_SCHEME}${_ITERATIONS}${salt_acak.hex()}${hash_baru.hex()}"


# Hitung ulang hash lalu bandingkan dengan compare_digest agar lama proses tidak membocorkan isinya.
# Format hash yang rusak menghasilkan False.
def verify_password(password: str, encoded_hash: str) -> bool:
    try:
        skema, jumlah_putaran, salt_hex, hash_tersimpan = encoded_hash.split("$", 3)
        if skema != _SCHEME:
            return False
        hash_hitungan = hashlib.pbkdf2_hmac(
            _ALGORITHM,
            password.encode("utf-8"),
            bytes.fromhex(salt_hex),
            int(jumlah_putaran),
        ).hex()
        return hmac.compare_digest(hash_hitungan, hash_tersimpan)
    except (TypeError, ValueError):
        return False

"""CLI admin lokal, dari folder backend: python scripts/create_user.py username --name 'Nama pemain'."""

import argparse
from getpass import getpass
from pathlib import Path
import sys

from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.config.database import PersistenceError
from app.schemas.auth import RegisterRequest
from app.services.user_service import create_user


# Buat satu akun pemain dari baris perintah tanpa mengubah akun lama. Aturannya sama dengan pendaftaran lewat API:
# validator RegisterRequest (username, nama tampilan, password) lalu create_user milik panel (username terlarang,
# riwayat pertandingan/survei, username kembar).
# Alur: 1 baca argumen dan password tersembunyi -> 2 validasi seperti API -> 3 simpan -> 4 lapor
def main():
    pengurai_argumen = argparse.ArgumentParser(
        description="Buat akun pemain untuk multiplayer lokal."
    )
    pengurai_argumen.add_argument("username")
    pengurai_argumen.add_argument("--name", default=None)
    argumen = pengurai_argumen.parse_args()

    # INPUT: username dan nama dari baris perintah, password diketik tersembunyi dua kali
    password = getpass("Password (10-128 karakter): ")
    try:
        data = RegisterRequest(
            username=argumen.username,
            display_name=argumen.name,
            password=password,
            password_confirmation=getpass("Ulangi password: "),
        )
    except ValidationError as error:
        pengurai_argumen.error("; ".join(galat["msg"] for galat in error.errors()))

    # PROSES: hash password lalu INSERT; username yang sudah ada atau terlarang ditolak
    try:
        create_user(data.username, data.display_name or data.username, data.password)
    except ValueError as error:
        pengurai_argumen.error(str(error))
    except PersistenceError as error:
        pengurai_argumen.error(f"Database gagal: {error}")

    # OUTPUT: beri tahu admin bahwa akun siap dipakai
    print(f"Akun {data.username} siap dipakai login.")


if __name__ == "__main__":
    main()

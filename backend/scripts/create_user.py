"""CLI admin lokal, dari folder backend: python scripts/create_user.py username --name 'Nama pemain'."""

import argparse
from getpass import getpass
from pathlib import Path
import re
import sys
from sqlalchemy.exc import IntegrityError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.models.auth_queries import create_account
from app.config.database import SessionLocal
from app.services.password_service import hash_password


# Buat satu akun pemain dari baris perintah tanpa mengubah akun lama.
def main():
    pengurai_argumen = argparse.ArgumentParser(
        description="Buat akun pemain untuk multiplayer lokal."
    )
    pengurai_argumen.add_argument("username")
    pengurai_argumen.add_argument("--name", default=None)
    argumen = pengurai_argumen.parse_args()

    # INPUT: username dan nama dari baris perintah, password diketik tersembunyi dua kali
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,32}", argumen.username):
        pengurai_argumen.error("Username 1-32 huruf/angka/underscore/tanda minus.")
    nama_tampilan = argumen.name or argumen.username
    if len(nama_tampilan) > 100:
        pengurai_argumen.error("Nama tampilan maksimal 100 karakter.")
    password = getpass("Password (minimal 8 karakter): ")
    if not 8 <= len(password) <= 256 or password != getpass("Ulangi password: "):
        pengurai_argumen.error("Password harus 8-256 karakter dan konfirmasi harus sama.")

    # PROSES: hash password lalu INSERT; username yang sudah ada ditolak constraint unik
    try:
        with SessionLocal.begin() as database:
            create_account(
                database,
                username=argumen.username,
                display_name=nama_tampilan,
                password_hash=hash_password(password),
            )
    except IntegrityError:
        pengurai_argumen.error("Username sudah digunakan; akun lama tidak diubah.")

    # OUTPUT: beri tahu admin bahwa akun siap dipakai
    print(f"Akun {argumen.username} siap dipakai login.")


if __name__ == "__main__":
    main()

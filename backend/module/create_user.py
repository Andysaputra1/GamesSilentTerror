"""CLI admin lokal: python -m module.create_user username --name 'Nama pemain'."""

import argparse
from getpass import getpass
import re
from sqlalchemy.exc import IntegrityError
from models.auth_queries import create_account
from module.mysql_connector import SessionLocal
from services.password_service import hash_password


# COMMAND: password dibaca tersembunyi, di-hash, lalu INSERT tanpa mengubah akun lama.
def main():
    parser = argparse.ArgumentParser(description="Buat akun pemain untuk multiplayer lokal.")
    parser.add_argument("username")
    parser.add_argument("--name", default=None)
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,32}", args.username):
        parser.error("Username 1-32 huruf/angka/underscore/tanda minus.")
    display_name = args.name or args.username
    if len(display_name) > 100:
        parser.error("Nama tampilan maksimal 100 karakter.")
    password = getpass("Password (minimal 8 karakter): ")
    if not 8 <= len(password) <= 256 or password != getpass("Ulangi password: "):
        parser.error("Password harus 8-256 karakter dan konfirmasi harus sama.")
    try:
        with SessionLocal.begin() as database:
            create_account(
                database,
                username=args.username,
                display_name=display_name,
                password_hash=hash_password(password),
            )
    except IntegrityError:
        parser.error("Username sudah digunakan; akun lama tidak diubah.")
    print(f"Akun {args.username} siap dipakai login.")


if __name__ == "__main__":
    main()

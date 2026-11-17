"""Run from repository root: python backend/scripts/setup_panel.py <path/to/.env atau .env.azure>."""

import base64
import getpass
import os
import sys
import secrets
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services.password_service import hash_password


# Tulis file berisi secret. Di POSIX file baru langsung dibuat 600, tanpa jeda sempat terbaca pengguna lain, dan file
# lama yang izinnya lebih longgar diperketat.
def tulis_rahasia(target, isi):
    deskriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(deskriptor, "w", encoding="utf-8") as berkas:
        berkas.write(isi)
    if os.name == "posix":
        os.chmod(target, 0o600)


# Buat kunci enkripsi panel hanya jika environment belum memilikinya.
def ensure_encryption(path):
    target = Path(path)
    content = target.read_text(encoding="utf-8") if target.exists() else ""
    if not any(
        line.startswith("PANEL_ENCRYPTION_KEY=") and line.partition("=")[2].strip()
        for line in content.splitlines()
    ):
        content = "\n".join(
            line for line in content.splitlines() if not line.startswith("PANEL_ENCRYPTION_KEY=")
        )
        tulis_rahasia(
            target,
            content.rstrip()
            + "\nPANEL_ENCRYPTION_KEY="
            + base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()
            + "\n",
        )


# Simpan hash password admin dan pastikan kunci enkripsi panel tersedia.
def configure(path, password):
    target = Path(path)
    encoded = base64.b64encode(hash_password(password).encode()).decode()
    lines = target.read_text(encoding="utf-8").splitlines() if target.exists() else []
    lines = [
        line for line in lines if not line.startswith(("PANEL_USERNAME=", "PANEL_PASSWORD_HASH="))
    ]
    lines.extend(["PANEL_USERNAME=administrator", "PANEL_PASSWORD_HASH=" + encoded])
    tulis_rahasia(target, "\n".join(lines) + "\n")
    ensure_encryption(target)


if __name__ == "__main__":
    # Path wajib ditulis: lokal memakai .env, Azure .env.azure. Tanpa argumen dulu diam-diam menulis .env, sehingga
    # password panel produksi bisa tersimpan di file yang tidak dibaca server.
    if len(sys.argv) != 2:
        raise SystemExit(
            "Pakai: python backend/scripts/setup_panel.py <file env>, mis. .env (lokal) atau .env.azure (Azure)."
        )
    password = getpass.getpass("Password administrator: ")
    if len(password) < 8 or password != getpass.getpass("Ulangi password: "):
        raise SystemExit("Password minimal 8 karakter dan konfirmasi harus sama.")
    configure(sys.argv[1], password)
    print(f"Hash password panel tersimpan di {sys.argv[1]}. Restart backend untuk menerapkan.")

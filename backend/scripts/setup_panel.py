"""Run from repository root: python backend/scripts/setup_panel.py [path/to/.env]."""
import base64
import getpass
import sys
import secrets
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services.password_service import hash_password


def ensure_encryption(path):
    target = Path(path)
    content = target.read_text(encoding="utf-8") if target.exists() else ""
    if not any(line.startswith("PANEL_ENCRYPTION_KEY=") and line.partition("=")[2].strip() for line in content.splitlines()):
        content = "\n".join(line for line in content.splitlines() if not line.startswith("PANEL_ENCRYPTION_KEY="))
        target.write_text(content.rstrip() + "\nPANEL_ENCRYPTION_KEY=" + base64.urlsafe_b64encode(secrets.token_bytes(32)).decode() + "\n", encoding="utf-8")


def configure(path, password):
    target=Path(path)
    encoded=base64.b64encode(hash_password(password).encode()).decode()
    lines=target.read_text(encoding="utf-8").splitlines() if target.exists() else []
    lines=[line for line in lines if not line.startswith(("PANEL_USERNAME=", "PANEL_PASSWORD_HASH="))]
    lines.extend(["PANEL_USERNAME=administrator", "PANEL_PASSWORD_HASH="+encoded])
    target.write_text("\n".join(lines)+"\n", encoding="utf-8")
    ensure_encryption(target)
    try:
        target.chmod(0o600)
    except OSError:
        pass


if __name__=="__main__":
    password=getpass.getpass("Password administrator: ")
    if len(password)<8 or password!=getpass.getpass("Ulangi password: "):
        raise SystemExit("Password minimal 8 karakter dan konfirmasi harus sama.")
    configure(sys.argv[1] if len(sys.argv)>1 else ".env", password)
    print("Hash password panel tersimpan. Restart backend untuk menerapkan.")

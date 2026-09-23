"""Create missing Azure configuration, preserving existing database credentials."""

from pathlib import Path
import secrets
import getpass
from setup_panel import configure, ensure_encryption

path = Path(".env.azure")
content = path.read_text(encoding="utf-8") if path.exists() else ""
existing = {
    line.split("=", 1)[0]: line.split("=", 1)[1]
    for line in content.splitlines()
    if "=" in line and not line.lstrip().startswith("#")
}


# Tambahkan variabel yang belum ada tanpa menimpa kredensial deployment lama.
def add(name, value):
    global content
    if name not in existing:
        content = content.rstrip() + "\n" + name + "=" + value + "\n"
        existing[name] = value


add("MYSQL_PASSWORD", secrets.token_hex(24))
add("MYSQL_ROOT_PASSWORD", secrets.token_hex(24))
add("BACKEND_DOMAIN", "backendthesis.andylabs.site")
add("FRONTEND_ORIGIN", "https://silent-terror.andylabs.site")
add("GOOGLE_CLIENT_ID", "")
add("openrouter_default", "")
add("OLLAMA_TUNNEL_TOKEN", "")
path.write_text(content.lstrip(), encoding="utf-8")
path.chmod(0o600)
if not existing.get("PANEL_PASSWORD_HASH", "").strip():
    password = getpass.getpass("Password administrator panel: ")
    if len(password) < 8 or password != getpass.getpass("Ulangi password: "):
        raise SystemExit(
            "Password minimal 8 karakter dan konfirmasi harus cocok. Jalankan ulang script."
        )
    configure(path, password)
else:
    ensure_encryption(path)
print(
    ".env.azure siap. Isi GOOGLE_CLIENT_ID dan opsional openrouter_default lewat nano .env.azure. Password database lama dipertahankan."
)

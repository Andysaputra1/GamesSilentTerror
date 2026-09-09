"""Reusable upload policies; no HTTP or file-writing logic here."""

from dataclasses import dataclass
from pathlib import Path

from config.settings import BACKEND_DIR

UPLOAD_ROOT = BACKEND_DIR / "public" / "uploads"


@dataclass(frozen=True)
class UploadPolicy:
    directory: str
    max_bytes: int
    max_files: int = 1
    allowed_types: tuple[str, ...] = ("image/jpeg", "image/png", "image/webp")


APP_ICON = UploadPolicy("app_icon", 5 * 1024 * 1024)
ASSET_ICON = UploadPolicy("asset_icon", 5 * 1024 * 1024, max_files=50)
PROFILE_PICTURE = UploadPolicy("profile-picture", 2 * 1024 * 1024)

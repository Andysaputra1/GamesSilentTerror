"""Reusable FastAPI UploadFile storage with bounded reads and unique filenames."""

from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from fastapi import UploadFile

from config.upload import UPLOAD_ROOT, UploadPolicy


class UploadError(ValueError):
    """An upload does not match its configured policy."""


@dataclass(frozen=True)
class StoredUpload:
    filename: str
    relative_path: str
    size: int
    content_type: str


# HELPER VALIDASI: kenali signature awal PNG/JPEG/WebP; bukan decoding atau validasi seluruh isi gambar.
def _image_type(header: bytes) -> tuple[str, str]:
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png", ".png"
    if header.startswith(b"\xff\xd8\xff"):
        return "image/jpeg", ".jpg"
    if header.startswith(b"RIFF") and header[8:12] == b"WEBP":
        return "image/webp", ".webp"
    raise UploadError("Format gambar tidak didukung. Gunakan PNG, JPEG, atau WebP.")


# HELPER ASYNC: periksa path, tipe, dan ukuran upload; simpan bernama UUID, bersihkan file parsial jika gagal.
async def save_upload(
    file: UploadFile, policy: UploadPolicy, *, root: Path = UPLOAD_ROOT
) -> StoredUpload:
    """Validate headers and size; callers decide authorization and HTTP responses."""
    root = root.resolve()
    destination = (root / policy.directory).resolve()
    if not destination.is_relative_to(root):
        raise UploadError("Folder upload tidak valid.")
    stored_path: Path | None = None
    created = False
    try:
        header = await file.read(12)
        content_type, extension = _image_type(header)
        if content_type not in policy.allowed_types or file.content_type != content_type:
            raise UploadError("Isi file tidak sesuai dengan tipe gambar yang diizinkan.")
        destination.mkdir(parents=True, exist_ok=True)
        # Original filenames are never used as filesystem paths.
        filename = uuid4().hex + extension
        stored_path = destination / filename
        size = len(header)
        with stored_path.open("xb") as output:
            created = True
            if size > policy.max_bytes:
                raise UploadError("Ukuran file melebihi batas upload.")
            output.write(header)
            while chunk := await file.read(64 * 1024):
                size += len(chunk)
                if size > policy.max_bytes:
                    raise UploadError("Ukuran file melebihi batas upload.")
                output.write(chunk)
        return StoredUpload(filename, stored_path.relative_to(root).as_posix(), size, content_type)
    except BaseException:
        if created and stored_path is not None:
            stored_path.unlink(missing_ok=True)
        raise
    finally:
        await file.close()


# HELPER ASYNC BATCH: simpan beberapa file sesuai batas kebijakan; jika gagal, hapus hanya hasil batch ini.
async def save_uploads(
    files: list[UploadFile], policy: UploadPolicy, *, root: Path = UPLOAD_ROOT
) -> list[StoredUpload]:
    """Batch upload; a failed file removes only files created in this batch."""
    uploaded: list[StoredUpload] = []
    try:
        if not 1 <= len(files) <= policy.max_files:
            raise UploadError(f"Jumlah file harus antara 1 dan {policy.max_files}.")
        for file in files:
            uploaded.append(await save_upload(file, policy, root=root))
        return uploaded
    except BaseException:
        for item in uploaded:
            (root / item.relative_path).unlink(missing_ok=True)
        raise
    finally:
        for file in files:
            await file.close()

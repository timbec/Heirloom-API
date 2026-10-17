"""Saving uploaded files. Local disk under STORAGE_DIR for now; swap this module for S3 at
deploy time. Paths stored in the database are relative to the storage root."""

import uuid
from pathlib import Path

from fastapi import UploadFile

from app.config import get_settings

CHUNK_BYTES = 1024 * 1024


class FileTooLargeError(Exception):
    pass


def absolute_path(relative: str) -> Path:
    return get_settings().storage_dir / relative


async def save_upload(upload: UploadFile, folder: str, suffix: str, max_bytes: int) -> str:
    """Stream an upload to `folder/<random>.<suffix>`, refusing anything over max_bytes.
    Returns the relative path."""
    relative = f"{folder}/{uuid.uuid4().hex}{suffix}"
    target = absolute_path(relative)
    target.parent.mkdir(parents=True, exist_ok=True)

    written = 0
    try:
        with target.open("wb") as out:
            while chunk := await upload.read(CHUNK_BYTES):
                written += len(chunk)
                if written > max_bytes:
                    raise FileTooLargeError
                out.write(chunk)
    except BaseException:
        target.unlink(missing_ok=True)
        raise
    return relative

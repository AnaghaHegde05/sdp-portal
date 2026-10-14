"""Validation and storage of supporting-document uploads."""
import os
import uuid
from dataclasses import dataclass
from pathlib import Path

from fastapi import HTTPException, UploadFile

from app.core.config import settings

# Kept as a module name for existing imports; the value lives in settings (app/core/config.py).
MAX_FILES_PER_APPLICATION = settings.max_files_per_application

# extension -> (content type, required leading bytes). The real file type is decided from the
# file's own bytes, never from the browser-supplied content type.
_TYPES = {
    "pdf": ("application/pdf", (b"%PDF-",)),
    "jpg": ("image/jpeg", (b"\xff\xd8\xff",)),
    "jpeg": ("image/jpeg", (b"\xff\xd8\xff",)),
    "png": ("image/png", (b"\x89PNG\r\n\x1a\n",)),
}
ALLOWED_DESCRIPTION = "PDF, JPG or PNG"


def allowed_extensions() -> list[str]:
    return sorted(_TYPES)


@dataclass
class ValidatedUpload:
    original_filename: str
    extension: str
    content_type: str
    data: bytes
    category: str | None = None  # which required-document slot this file fills (set by the submit route)


def _clean_filename(name: str) -> str:
    """Keep only the base name (no directories) and cap the length."""
    base = os.path.basename(name.replace("\\", "/")).strip()
    return (base or "file")[:255]


def validate_upload(upload: UploadFile) -> ValidatedUpload:
    filename = _clean_filename(upload.filename or "")
    extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if extension not in _TYPES:
        raise HTTPException(400, f"'{filename}': only {ALLOWED_DESCRIPTION} files are allowed.")

    # Read one byte past the limit so an oversized file is detected without loading all of it.
    data = upload.file.read(settings.max_upload_bytes + 1)
    if len(data) > settings.max_upload_bytes:
        raise HTTPException(413, f"'{filename}': file is larger than {settings.max_upload_mb} MB.")
    if not data:
        raise HTTPException(400, f"'{filename}': file is empty.")

    content_type, signatures = _TYPES[extension]
    if not data.startswith(signatures):
        raise HTTPException(400, f"'{filename}': file content does not match its {extension.upper()} extension.")

    return ValidatedUpload(filename, extension, content_type, data)


def validate_uploads(uploads: list[UploadFile]) -> list[ValidatedUpload]:
    # Browsers send an empty file part when no file was chosen; ignore those.
    real = [u for u in uploads if u.filename]
    if len(real) > settings.max_files_per_application:
        raise HTTPException(400, f"At most {settings.max_files_per_application} files can be uploaded per application.")
    return [validate_upload(u) for u in real]


def store_file(application_id: int, item: ValidatedUpload) -> str:
    """Write the file under UPLOAD_DIR/<application_id>/ with a random name; return the relative path."""
    folder = settings.upload_path / str(application_id)
    folder.mkdir(parents=True, exist_ok=True)
    name = f"{uuid.uuid4().hex}.{'jpg' if item.extension == 'jpeg' else item.extension}"
    (folder / name).write_bytes(item.data)
    return f"{application_id}/{name}"


def remove_stored_files(relative_paths: list[str]) -> None:
    """Best-effort cleanup used when saving an application fails part-way."""
    for rel in relative_paths:
        try:
            (settings.upload_path / rel).unlink(missing_ok=True)
        except OSError:
            pass
    for folder in {Path(rel).parent for rel in relative_paths}:
        try:
            (settings.upload_path / folder).rmdir()  # only succeeds if empty
        except OSError:
            pass

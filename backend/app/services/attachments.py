import re
import uuid
from collections.abc import Callable
from pathlib import Path

from fastapi import UploadFile
from sqlalchemy.orm import Session

from app.config import Settings
from app.errors import NotFoundError, PayloadTooLargeError
from app.models import Attachment, AttachmentKind
from app.services.applications import get_application

MAX_UPLOAD_BYTES = 25 * 1024 * 1024
MAX_NAME_LENGTH = 120
MAX_EXT_LENGTH = 20
_CHUNK = 1024 * 1024
_DISALLOWED = re.compile(r"[^A-Za-z0-9._ \-äöüÄÖÜß]")
_RESERVED = re.compile(r"(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])", re.IGNORECASE)


def basename(name: str) -> str:
    return re.split(r"[/\\]", name)[-1]


def safe_filename(name: str) -> str:
    """Reduce an uploaded name to a harmless basename (safe on Windows and Linux)."""
    cleaned = _DISALLOWED.sub("_", basename(name)).strip(" .")
    if _RESERVED.fullmatch(cleaned.split(".", 1)[0].rstrip(" ")):
        cleaned = "_" + cleaned
    if not cleaned:
        return "datei"
    if len(cleaned) > MAX_NAME_LENGTH:
        stem, dot, ext = cleaned.rpartition(".")
        if dot and stem and len(ext) + 1 <= MAX_EXT_LENGTH:
            stem = stem[: MAX_NAME_LENGTH - len(ext) - 1].rstrip(" .")
            cleaned = f"{stem}.{ext}"
        else:
            cleaned = cleaned[:MAX_NAME_LENGTH].rstrip(" .")
    return cleaned or "datei"


def resolve_under(base: Path, stored: str) -> Path:
    """Resolve a stored (relative) path; it must stay inside `base`."""
    root = base.resolve()
    path = (root / stored).resolve()
    if not path.is_relative_to(root):
        raise ValueError(f"stored path escapes its directory: {stored!r}")
    return path


def resolve_path(settings: Settings, stored_path: str) -> Path:
    return resolve_under(settings.attachments_dir, stored_path)


def write_limited(
    upload: UploadFile, path: Path, *, code: str = "attachment_too_large", what: str = "Attachment"
) -> int:
    """Stream the upload to `path`; above MAX_UPLOAD_BYTES raise 413 `code`. Returns the byte count."""
    written = 0
    with path.open("wb") as out:
        while chunk := upload.file.read(_CHUNK):
            written += len(chunk)
            if written > MAX_UPLOAD_BYTES:
                raise PayloadTooLargeError(
                    code,
                    f"{what} exceeds the {MAX_UPLOAD_BYTES // (1024 * 1024)} MB limit",
                    {"max_bytes": MAX_UPLOAD_BYTES},
                )
            out.write(chunk)
    return written


def get_attachment(session: Session, att_id: int) -> Attachment:
    att = session.get(Attachment, att_id)
    if att is None:
        raise NotFoundError("attachment_not_found", "Attachment not found", {"attachment_id": att_id})
    return att


def _store(
    session: Session, settings: Settings, app_id: int, name: str, kind: AttachmentKind,
    write: Callable[[Path], object],
) -> Attachment:
    """Shared by `store` and `store_bytes`: name handling, stored path, row; the file goes if anything fails."""
    get_application(session, app_id)
    safe = safe_filename(name)
    display = basename(name).strip() or safe
    display = "".join(c if c.isprintable() else "_" for c in display)[:255]
    stored = f"{app_id}/{uuid.uuid4()}_{safe}"
    path = resolve_path(settings, stored)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        write(path)
        att = Attachment(
            application_id=app_id, filename=safe, display_name=display, stored_path=stored, kind=kind
        )
        session.add(att)
        session.flush()
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return att


def store(
    session: Session, settings: Settings, app_id: int, upload: UploadFile, kind: AttachmentKind
) -> Attachment:
    return _store(session, settings, app_id, upload.filename or "", kind, lambda path: write_limited(upload, path))


def store_bytes(
    session: Session, settings: Settings, app_id: int, filename: str, data: bytes, kind: AttachmentKind
) -> Attachment:
    """Like `store`, for content the app produced itself (e.g. a cover letter PDF)."""
    return _store(session, settings, app_id, filename, kind, lambda path: path.write_bytes(data))


def file_path(session: Session, settings: Settings, att_id: int) -> tuple[Attachment, Path]:
    att = get_attachment(session, att_id)
    path = resolve_path(settings, att.stored_path)
    if not path.is_file():
        raise NotFoundError(
            "attachment_not_found", "Attachment file is missing", {"attachment_id": att_id}
        )
    return att, path


def delete(session: Session, settings: Settings, att_id: int) -> None:
    att = get_attachment(session, att_id)
    path = resolve_path(settings, att.stored_path)
    session.delete(att)
    session.flush()
    path.unlink(missing_ok=True)

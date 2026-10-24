"""Profile documents: upload with local text extraction, LLM transcription, manual edits.

Kinds: `text` (txt/md), `pdf_text` (PDF with a text layer), `pdf_scan` (PDF without), `image`.
Any change marks the profile as having changed inputs since its last generation.
"""
import io
import threading
import uuid
from pathlib import Path
from typing import Any

import pypdfium2
from fastapi import UploadFile
from PIL import Image, ImageOps
from pypdf import PdfReader
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.errors import (
    ConflictError,
    NotFoundError,
    UnprocessableError,
    UnsupportedMediaTypeError,
    UpstreamError,
)
from app.llm.base import ImagePart, Message
from app.llm.factory import ConfigData
from app.llm.runner import run_call
from app.models import DocumentKind, ProfileDocument, TextSource, UserProfile
from app.services import attachments, llm_configs

Image.MAX_IMAGE_PIXELS = 50_000_000  # Pillow refuses (DecompressionBombError) above twice this
PDF_TEXT_MIN_CHARS_PER_PAGE = 50
SCAN_MAX_PAGES = 10
SCAN_DPI = 150
MAX_IMAGE_EDGE = 2000
MAX_IMAGE_BYTES = 4 * 1024 * 1024
JPEG_QUALITY = 85
EXTRACTION_MAX_TOKENS = 8192
_PDFIUM_LOCK = threading.Lock()  # pdfium is not thread-safe; sync endpoints run in a threadpool
EXTRACTION_SYSTEM = "Transcribe all text faithfully; keep structure as plain text; no commentary."
EXTRACTION_REQUEST = "Transcribe the attached document."
PROFILE_ID = 1

_TYPES = {  # extension -> mime
    "pdf": "application/pdf", "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
    "webp": "image/webp", "txt": "text/plain", "md": "text/markdown",
}
UNSET: Any = object()  # "field not given" for update(), distinct from None (= clear)


def _unsupported(reason: str) -> UnsupportedMediaTypeError:
    return UnsupportedMediaTypeError(
        "unsupported_document_type",
        f"Unsupported document: {reason}. Allowed: PDF, PNG, JPG, WEBP, TXT, MD",
        {"reason": reason},
    )


def _unreadable(reason: str) -> UnprocessableError:
    return UnprocessableError(
        "document_unreadable", f"The document could not be read: {reason}", {"reason": reason}
    )


def _sniff_mime(head: bytes) -> str | None:
    if head.startswith(b"%PDF-"):
        return "application/pdf"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    return None


def decode_text(raw: bytes) -> str | None:
    """UTF-8 (BOM allowed) with cp1252 fallback; None for binary content."""
    if b"\x00" in raw:
        return None
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        pass
    try:
        return raw.decode("cp1252")
    except UnicodeDecodeError:
        return None


def _classify(path: Path, ext: str) -> tuple[DocumentKind, str | None]:
    """(kind, locally extracted text) of a stored file; raises unsupported_document_type."""
    mime = _TYPES[ext]
    if mime.startswith("text/"):
        text = decode_text(path.read_bytes())
        if text is None:
            raise _unsupported("the file is not text")
        return DocumentKind.text, text.strip() or None
    with path.open("rb") as fh:
        sniffed = _sniff_mime(fh.read(16))
    if sniffed != mime:
        raise _unsupported("the content does not match the file extension")
    if mime.startswith("image/"):
        return DocumentKind.image, None
    try:
        reader = PdfReader(str(path))
        if reader.is_encrypted:
            raise _unreadable("the PDF is password-protected")
        pages = [(page.extract_text() or "").strip() for page in reader.pages]
    except UnprocessableError:
        raise
    except Exception:  # noqa: BLE001  (corrupt files: pypdf raises many types)
        raise _unreadable("the PDF is corrupt") from None
    if not pages:
        raise _unreadable("the PDF has no pages")
    if sum(len(p) for p in pages) / len(pages) >= PDF_TEXT_MIN_CHARS_PER_PAGE:
        return DocumentKind.pdf_text, "\n\n".join(p for p in pages if p)
    return DocumentKind.pdf_scan, None


def ensure_profile_row(session: Session) -> UserProfile:
    profile = session.get(UserProfile, PROFILE_ID)
    if profile is None:
        profile = UserProfile(id=PROFILE_ID, version=0, edited_since_generation=False,
                              inputs_changed_since_generation=False)
        session.add(profile)
        session.flush()
    return profile


def mark_inputs_changed(session: Session) -> None:
    ensure_profile_row(session).inputs_changed_since_generation = True


def get_document(session: Session, doc_id: int) -> ProfileDocument:
    doc = session.get(ProfileDocument, doc_id)
    if doc is None:
        raise NotFoundError("document_not_found", "Document not found", {"document_id": doc_id})
    return doc


def list_documents(session: Session) -> list[ProfileDocument]:
    return list(session.scalars(select(ProfileDocument).order_by(ProfileDocument.id)))


def resolve_path(settings: Settings, stored_path: str) -> Path:
    return attachments.resolve_under(settings.profile_dir, stored_path)


def discard_file(settings: Settings, doc: ProfileDocument) -> None:
    """Remove the stored file of a document (e.g. after a failed commit)."""
    resolve_path(settings, doc.stored_path).unlink(missing_ok=True)


def upload(session: Session, settings: Settings, file: UploadFile, description: str | None) -> ProfileDocument:
    original = file.filename or ""
    safe = attachments.safe_filename(original)
    ext = safe.rpartition(".")[2].lower() if "." in safe else ""
    if ext not in _TYPES:
        raise _unsupported("file extension not allowed")
    display = attachments.basename(original).strip() or safe
    display = "".join(c if c.isprintable() else "_" for c in display)[:255]
    stored = f"{uuid.uuid4()}_{safe}"
    path = resolve_path(settings, stored)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        attachments.write_limited(file, path, code="document_too_large", what="Document")
        kind, text = _classify(path, ext)
        doc = ProfileDocument(
            filename=safe, display_name=display, stored_path=stored, mime=_TYPES[ext], kind=kind,
            description=(description or "").strip() or None, text=text,
            text_source=TextSource.extracted if text else None,
        )
        session.add(doc)
        mark_inputs_changed(session)
        session.flush()
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return doc


def file_path(session: Session, settings: Settings, doc_id: int) -> tuple[ProfileDocument, Path]:
    doc = get_document(session, doc_id)
    path = resolve_path(settings, doc.stored_path)
    if not path.is_file():
        raise NotFoundError("document_not_found", "Document file is missing", {"document_id": doc_id})
    return doc, path


def update(session: Session, doc_id: int, description: str | None = UNSET, text: str | None = UNSET) -> ProfileDocument:
    doc = get_document(session, doc_id)
    if description is UNSET and text is UNSET:
        return doc  # nothing to change
    if description is not UNSET:
        doc.description = (description or "").strip() or None
    if text is not UNSET:
        cleaned = (text or "").strip()
        doc.text = cleaned or None
        doc.text_source = TextSource.manual if cleaned else None
    mark_inputs_changed(session)
    session.flush()
    return doc


def delete(session: Session, settings: Settings, doc_id: int) -> None:
    doc = get_document(session, doc_id)
    path = resolve_path(settings, doc.stored_path)
    session.delete(doc)
    mark_inputs_changed(session)
    session.flush()
    path.unlink(missing_ok=True)


def render_pdf_pages(path: Path) -> list[ImagePart]:
    """First SCAN_MAX_PAGES pages as PNG: at most SCAN_DPI, longest edge at most MAX_IMAGE_EDGE px."""
    with _PDFIUM_LOCK:
        pdf = pypdfium2.PdfDocument(str(path))
        try:
            parts = []
            for index in range(min(len(pdf), SCAN_MAX_PAGES)):
                page = pdf[index]
                try:
                    width, height = page.get_size()
                    scale = min(SCAN_DPI / 72, MAX_IMAGE_EDGE / max(width, height, 1))
                    buf = io.BytesIO()
                    page.render(scale=scale).to_pil().save(buf, format="PNG")
                finally:
                    page.close()
                parts.append(ImagePart(buf.getvalue(), "image/png"))
            return parts
        finally:
            pdf.close()


def shrink_image(data: bytes, mime: str) -> ImagePart:
    """Unchanged if upright and small enough, else EXIF-transposed, downscaled (longest edge) and re-encoded.

    Re-encoding gives PNG for images with alpha, else JPEG.
    """
    img = Image.open(io.BytesIO(data))
    rotated = img.getexif().get(0x0112, 1) not in (0, 1)  # EXIF orientation other than "normal"
    if not rotated and len(data) <= MAX_IMAGE_BYTES and max(img.size) <= MAX_IMAGE_EDGE:
        return ImagePart(data, mime)
    img = ImageOps.exif_transpose(img)
    img.thumbnail((MAX_IMAGE_EDGE, MAX_IMAGE_EDGE))
    buf = io.BytesIO()
    if img.mode in ("RGBA", "LA", "PA") or "transparency" in img.info:
        img.convert("RGBA").save(buf, format="PNG", optimize=True)
        return ImagePart(buf.getvalue(), "image/png")
    img.convert("RGB").save(buf, format="JPEG", quality=JPEG_QUALITY)
    return ImagePart(buf.getvalue(), "image/jpeg")


def _images_for(doc_kind: DocumentKind, path: Path, mime: str, doc_id: int) -> list[ImagePart]:
    try:
        if doc_kind == DocumentKind.pdf_scan:
            images = render_pdf_pages(path)
        else:
            images = [shrink_image(path.read_bytes(), mime)]
    except FileNotFoundError:
        raise NotFoundError("document_not_found", "Document file is missing", {"document_id": doc_id}) from None
    except Image.DecompressionBombError:
        raise _unreadable("the image is too large") from None
    except Exception:  # noqa: BLE001  (pdfium and Pillow raise many types)
        raise _unreadable("the file could not be rendered") from None
    if not images:
        raise _unreadable("the file has no pages")
    return images


def extract_with_llm(
    session_factory: sessionmaker[Session], settings: Settings, doc_id: int
) -> tuple[ProfileDocument, bool]:
    """Transcribe an image or scanned PDF with the `extraction` LLM. Returns (document, limit_exceeded)."""
    with session_factory() as session:
        doc, path = file_path(session, settings, doc_id)
        if doc.kind in (DocumentKind.text, DocumentKind.pdf_text):
            raise ConflictError(
                "document_extraction_not_needed",
                "This document already has text; LLM extraction is only for images and scanned PDFs",
                {"kind": doc.kind.value},
            )
        kind, mime = doc.kind, doc.mime
        cfg = llm_configs.resolve(session, "extraction")
    if not cfg.supports_images:
        raise ConflictError(
            "llm_no_image_support", "The extraction LLM configuration does not support images", {"name": cfg.name}
        )

    def build(_cfg: ConfigData) -> tuple[str, list[Message]]:
        images = _images_for(kind, path, mime, doc_id)
        return EXTRACTION_SYSTEM, [Message("user", [EXTRACTION_REQUEST, *images])]

    result, exceeded = run_call(
        session_factory, cfg, "extraction", build, max_tokens=EXTRACTION_MAX_TOKENS
    )  # no DB session is held during the request
    text = result.text.strip()
    if not text:
        raise UpstreamError(
            "llm_invalid_output", "The LLM returned an empty transcription", {"reason": "empty transcription"}
        )
    with session_factory() as session:
        doc = get_document(session, doc_id)  # deleted meanwhile -> document_not_found
        doc.text = text
        doc.text_source = TextSource.llm
        mark_inputs_changed(session)
        session.commit()
        return doc, exceeded

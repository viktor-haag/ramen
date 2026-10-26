"""Cover letter LaTeX templates: list, upload, rename, delete (spec 7.1, 7.2).

Every function works on the given session; the caller commits.
"""
from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import ConflictError, NotFoundError, PayloadTooLargeError, UnprocessableError
from app.models import CoverLetterTemplate
from app.services.attachments import basename

MAX_TEMPLATE_BYTES = 200 * 1024
_CHUNK = 64 * 1024


def list_templates(session: Session) -> list[CoverLetterTemplate]:
    return list(session.scalars(select(CoverLetterTemplate).order_by(CoverLetterTemplate.id)))


def get_template(session: Session, template_id: int) -> CoverLetterTemplate:
    template = session.get(CoverLetterTemplate, template_id)
    if template is None:
        raise NotFoundError("template_not_found", "Template not found", {"template_id": template_id})
    return template


def _invalid(reason: str, detail: str, cls=UnprocessableError):
    return cls("template_invalid", detail, {"reason": reason})


def upload(session: Session, upload: UploadFile) -> CoverLetterTemplate:
    filename = basename(upload.filename or "")
    if not filename.lower().endswith(".tex"):
        raise _invalid("extension", "Only .tex files are accepted")
    name = filename[: -len(".tex")].strip() or "Template"
    data = b""
    while chunk := upload.file.read(_CHUNK):
        data += chunk
        if len(data) > MAX_TEMPLATE_BYTES:
            raise _invalid("size", f"The template exceeds {MAX_TEMPLATE_BYTES // 1024} KB", PayloadTooLargeError)
    try:
        content = data.decode("utf-8")
    except UnicodeDecodeError:
        raise _invalid("encoding", "The template must be UTF-8 encoded") from None
    if "\\documentclass" not in content or "\\end{document}" not in content:
        raise _invalid("structure", "The template needs \\documentclass and \\end{document}")
    template = CoverLetterTemplate(name=name[:120], content=content, builtin=False)
    session.add(template)
    session.flush()
    return template


def _editable(session: Session, template_id: int) -> CoverLetterTemplate:
    template = get_template(session, template_id)
    if template.builtin:
        raise ConflictError("template_builtin", "The default template cannot be changed", {"template_id": template_id})
    return template


def rename(session: Session, template_id: int, name: str) -> CoverLetterTemplate:
    template = _editable(session, template_id)
    template.name = name
    session.flush()
    return template


def delete(session: Session, template_id: int) -> None:
    session.delete(_editable(session, template_id))
    session.flush()

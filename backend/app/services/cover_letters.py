"""Cover letter drafts: lookup, replace, delete and chat messages (spec 3.2, 5.6, 7.2).

Every function works on the given session; the caller commits.
"""
from pathlib import Path
from typing import Any

from sqlalchemy import event, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.errors import ConflictError, NotFoundError
from app.models import Application, CoverLetter, CoverLetterMessage, CoverLetterTemplate
from app.models.enums import CoverLetterFormat, CoverLetterStatus, MessageRole
from app.models.posting import utcnow
from app.services import llm_configs, usage


def get_for_application(session: Session, app_id: int) -> CoverLetter:
    cl = session.scalar(select(CoverLetter).where(CoverLetter.application_id == app_id))
    if cl is None:
        raise NotFoundError(
            "cover_letter_not_found", "This application has no cover letter", {"application_id": app_id}
        )
    return cl


def ensure_idle(cl: CoverLetter) -> None:
    if cl.status != CoverLetterStatus.idle:
        raise ConflictError("cover_letter_busy", "The cover letter is still being generated or compiled",
                            {"status": cl.status.value})


def ensure_within_limit(session: Session) -> None:
    """409 `llm_not_configured` (from `resolve`) or 409 `daily_limit_reached` (as in `api/fit.py`)."""
    config_id = llm_configs.resolve(session, "cover_letter").id
    hit = usage.limit_status(session, utcnow(), config_id)
    if hit is not None:
        raise ConflictError(
            "daily_limit_reached", "The daily LLM usage limit has been reached",
            {"scope": hit.scope, "config_name": hit.config_name},
        )


def pdf_file(settings: Settings, cl: CoverLetter) -> Path:
    return settings.cover_letters_dir / f"{cl.id}.pdf"


_UNLINK_KEY = "cover_letter_unlink"


def _unlink_pending(session: Session) -> None:
    for path in session.info.pop(_UNLINK_KEY, set()):
        path.unlink(missing_ok=True)


def _drop_pending(session: Session) -> None:
    session.info.pop(_UNLINK_KEY, None)


def unlink_after_commit(session: Session, path: Path) -> None:
    """Delete `path` once the session's current transaction commits (nothing on rollback)."""
    if not session.info.get(_UNLINK_KEY + "_hooked"):
        event.listen(session, "after_commit", _unlink_pending)
        event.listen(session, "after_rollback", _drop_pending)
        session.info[_UNLINK_KEY + "_hooked"] = True
    session.info.setdefault(_UNLINK_KEY, set()).add(path)


def remove_pdf(session: Session, settings: Settings, cl: CoverLetter) -> None:
    """Clear `pdf_path`/`compiled_at`; the compiled PDF file (if any) is deleted after the commit."""
    if cl.id is not None:
        unlink_after_commit(session, pdf_file(settings, cl))
    cl.pdf_path = None
    cl.compiled_at = None


def _context_dict(context: Any) -> dict:
    """`ContextIn` (pydantic), any object with the three attributes, or a dict -> the stored JSON."""
    if isinstance(context, dict):
        get = context.get
    else:
        def get(name, default=None):
            return getattr(context, name, default)
    return {
        "profile": bool(get("profile", True)),
        "document_ids": [int(i) for i in (get("document_ids", None) or [])],
        "notes": get("notes", "") or "",
    }


def replace(session: Session, settings: Settings, app_id: int, data: Any) -> CoverLetter:
    """Create the draft or reset all of it (history, PDF, content); `status = generating`.

    `data` is a `CoverLetterIn` (format, template_id, language, context). For latex the template's content
    is copied (`404 template_not_found`); text drafts have no template.
    """
    fmt = CoverLetterFormat(data.format)
    template = None
    if fmt == CoverLetterFormat.latex:
        template = session.get(CoverLetterTemplate, data.template_id) if data.template_id is not None else None
        if template is None:
            raise NotFoundError("template_not_found", "Template not found", {"template_id": data.template_id})
    cl = session.scalar(select(CoverLetter).where(CoverLetter.application_id == app_id))
    if cl is None:
        if session.get(Application, app_id) is None:
            raise NotFoundError("application_not_found", "Application not found", {"application_id": app_id})
        cl = CoverLetter(application_id=app_id)
        session.add(cl)
    else:
        remove_pdf(session, settings, cl)
        cl.messages.clear()
    cl.format = fmt
    cl.template_id = template.id if template is not None else None
    cl.template_content = template.content if template is not None else None
    cl.language = data.language
    cl.context = _context_dict(data.context)
    cl.content = ""
    cl.status = CoverLetterStatus.generating
    cl.error = None
    cl.compile_log = None
    cl.pdf_path = None
    cl.compiled_at = None
    session.flush()
    return cl


def delete(session: Session, settings: Settings, cl: CoverLetter) -> None:
    """Delete the draft, its history and its PDF."""
    remove_pdf(session, settings, cl)
    session.delete(cl)
    session.flush()


def add_message(session: Session, cl: CoverLetter, role: MessageRole, text: str) -> CoverLetterMessage:
    message = CoverLetterMessage(role=role, text=text)
    cl.messages.append(message)
    session.flush()
    return message

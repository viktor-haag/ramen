"""Cover letter endpoints (spec 7.2 "Anschreiben"): `/api/applications/{app_id}/cover-letter`.

Endpoints that start a job set the busy status and commit before handing the draft to the job, so the
`202` response and every following `ensure_idle` already see it.
"""
import re
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.downloads import content_disposition
from app.config import Settings
from app.cover_letters.jobs import REPAIRABLE, CoverLetterJobs
from app.db import get_session
from app.errors import ConflictError, NotFoundError
from app.models import AttachmentKind, CoverLetter, CoverLetterTemplate
from app.models.enums import CoverLetterFormat, CoverLetterStatus, MessageRole
from app.schemas.application import AttachmentOut
from app.schemas.cover_letter import ContentIn, CoverLetterIn, CoverLetterOut, MessageIn, MessageOut
from app.services import attachments, cover_letter_llm
from app.services import cover_letters as svc
from app.services.applications import get_application

router = APIRouter()

PATH = "/applications/{app_id}/cover-letter"
REPAIR_MESSAGE = "Fix the compile error"
NO_PDF = "There is no current PDF of the cover letter"
NAME_PREFIX = {"de": "Anschreiben", "en": "Cover_letter"}
_UNSAFE_COMPANY = re.compile(r"[^A-Za-z0-9äöüÄÖÜß.\-]+")

Lang = Literal["de", "en"]


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_jobs(request: Request) -> CoverLetterJobs:
    return request.app.state.cover_letter_jobs


def _pdf_path(settings: Settings, cl: CoverLetter) -> Path | None:
    """The current PDF, or None (no `pdf_path`, file missing, or a path outside the folder)."""
    if not cl.pdf_path:
        return None
    try:
        path = attachments.resolve_under(settings.cover_letters_dir, cl.pdf_path)
    except ValueError:
        return None
    return path if path.is_file() else None


def _out(session: Session, settings: Settings, jobs: CoverLetterJobs, cl: CoverLetter) -> CoverLetterOut:
    template = session.get(CoverLetterTemplate, cl.template_id) if cl.template_id is not None else None
    return CoverLetterOut(
        id=cl.id,
        application_id=cl.application_id,
        format=cl.format,
        template_id=cl.template_id,
        template_name=template.name if template is not None else None,
        language=cl.language,
        context=cl.context or {},
        content=cl.content,
        status=cl.status,
        error=cl.error,
        compile_log=cl.compile_log,
        pdf_available=_pdf_path(settings, cl) is not None,
        compiler_available=jobs.compiler.available(),
        compiled_at=cl.compiled_at,
        updated_at=cl.updated_at,
        messages=[MessageOut.model_validate(m) for m in cl.messages],
    )


def _file_name(cl: CoverLetter, lang: str, ext: str) -> str:
    """`Anschreiben_<Firma>.<ext>` / `Cover_letter_<Company>.<ext>`; the company reduced to safe characters."""
    company = _UNSAFE_COMPANY.sub("_", cl.application.posting.company or "").strip("._-")
    stem = f"{NAME_PREFIX[lang]}_{company}" if company else NAME_PREFIX[lang]
    return attachments.safe_filename(f"{stem}.{ext}")


def _start(session: Session, cl: CoverLetter, status: CoverLetterStatus) -> None:
    cl.status = status
    session.commit()


@router.get(PATH, response_model=CoverLetterOut)
def read(
    app_id: int,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
    jobs: CoverLetterJobs = Depends(get_jobs),
):
    return _out(session, settings, jobs, svc.get_for_application(session, app_id))


@router.post(PATH, response_model=CoverLetterOut, status_code=202)
def create(
    app_id: int,
    body: CoverLetterIn,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
    jobs: CoverLetterJobs = Depends(get_jobs),
):
    application = get_application(session, app_id)
    existing = session.scalar(select(CoverLetter).where(CoverLetter.application_id == app_id))
    if existing is not None:
        svc.ensure_idle(existing)
    svc.ensure_within_limit(session)
    # 422 `cover_letter_context_too_large` before anything changes: the old draft stays intact (spec 5.1)
    cover_letter_llm.build_context(session, application, body.context.model_dump())
    cl = svc.replace(session, settings, app_id, body)  # status = generating
    session.commit()
    jobs.generate(cl.id, created_at=cl.created_at)
    return _out(session, settings, jobs, cl)


@router.put(f"{PATH}/content", response_model=CoverLetterOut, status_code=202)
def save_content(
    app_id: int,
    body: ContentIn,
    response: Response,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
    jobs: CoverLetterJobs = Depends(get_jobs),
):
    cl = svc.get_for_application(session, app_id)
    svc.ensure_idle(cl)
    cl.content = body.content
    cl.error = None
    cl.compile_log = None
    svc.remove_pdf(session, settings, cl)
    if cl.format == CoverLetterFormat.latex:
        _start(session, cl, CoverLetterStatus.compiling)
        jobs.compile_only(cl.id, created_at=cl.created_at)
    else:
        session.commit()
        response.status_code = 200
    return _out(session, settings, jobs, cl)


@router.post(f"{PATH}/messages", response_model=CoverLetterOut, status_code=202)
def send_message(
    app_id: int,
    body: MessageIn,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
    jobs: CoverLetterJobs = Depends(get_jobs),
):
    cl = svc.get_for_application(session, app_id)
    svc.ensure_idle(cl)
    svc.ensure_within_limit(session)
    svc.add_message(session, cl, MessageRole.user, body.text)
    _start(session, cl, CoverLetterStatus.generating)
    jobs.revise(cl.id, body.text, created_at=cl.created_at)
    return _out(session, settings, jobs, cl)


@router.post(f"{PATH}/repair", response_model=CoverLetterOut, status_code=202)
def repair(
    app_id: int,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
    jobs: CoverLetterJobs = Depends(get_jobs),
):
    cl = svc.get_for_application(session, app_id)
    svc.ensure_idle(cl)
    if cl.format != CoverLetterFormat.latex or (cl.error or {}).get("code") not in REPAIRABLE:
        raise ConflictError("cover_letter_nothing_to_repair", "There is no compile error to repair")
    svc.ensure_within_limit(session)
    svc.add_message(session, cl, MessageRole.user, REPAIR_MESSAGE)
    _start(session, cl, CoverLetterStatus.generating)
    jobs.repair(cl.id, created_at=cl.created_at)
    return _out(session, settings, jobs, cl)


@router.delete(PATH, status_code=204)
def delete(
    app_id: int,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> Response:
    svc.delete(session, settings, svc.get_for_application(session, app_id))
    session.commit()
    return Response(status_code=204)


@router.get(f"{PATH}/pdf")
def pdf(
    app_id: int,
    lang: Lang = "en",
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> FileResponse:
    cl = svc.get_for_application(session, app_id)
    path = _pdf_path(settings, cl)
    if path is None:
        raise NotFoundError("cover_letter_no_pdf", NO_PDF, {"cover_letter_id": cl.id})
    return FileResponse(
        path, media_type="application/pdf", filename=_file_name(cl, lang, "pdf"), content_disposition_type="inline"
    )


@router.get(f"{PATH}/source")
def source(app_id: int, lang: Lang = "en", session: Session = Depends(get_session)) -> Response:
    cl = svc.get_for_application(session, app_id)
    latex = cl.format == CoverLetterFormat.latex
    name = _file_name(cl, lang, "tex" if latex else "txt")
    return Response(
        content=cl.content.encode("utf-8"),
        media_type=("text/x-tex" if latex else "text/plain") + "; charset=utf-8",
        headers={"Content-Disposition": content_disposition(name)},
    )


@router.post(f"{PATH}/attach", response_model=AttachmentOut, status_code=201)
def attach(
    app_id: int,
    lang: Lang = "en",
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
):
    """Save the PDF (latex) or the text (text) as a `cover_letter` attachment; each call adds one."""
    cl = svc.get_for_application(session, app_id)
    if cl.format == CoverLetterFormat.latex:
        path = _pdf_path(settings, cl)
        if path is None:
            raise ConflictError("cover_letter_no_pdf", NO_PDF, {"cover_letter_id": cl.id})
        data, ext = path.read_bytes(), "pdf"
    else:
        data, ext = cl.content.encode("utf-8"), "txt"
    att = attachments.store_bytes(
        session, settings, app_id, _file_name(cl, lang, ext), data, AttachmentKind.cover_letter
    )
    try:
        session.commit()
    except BaseException:
        attachments.resolve_path(settings, att.stored_path).unlink(missing_ok=True)
        raise
    return att

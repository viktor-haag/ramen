from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import ConflictError, NotFoundError
from app.models import Application, AppStatus, Posting, StatusChange, TriageStatus


def _posting(session: Session, posting_id: int) -> Posting:
    posting = session.get(Posting, posting_id)
    if posting is None:
        raise NotFoundError("posting_not_found", "Posting not found", {"posting_id": posting_id})
    return posting


def _application(session: Session, posting_id: int) -> Application | None:
    return session.scalars(select(Application).where(Application.posting_id == posting_id)).first()


def save_posting(session: Session, posting_id: int, now: datetime) -> Application:
    posting = _posting(session, posting_id)
    if posting.triage_status == TriageStatus.saved or _application(session, posting_id) is not None:
        raise ConflictError("already_saved", "Posting is already saved", {"posting_id": posting_id})
    application = Application(
        posting_id=posting.id, status=AppStatus.saved, created_at=now, updated_at=now
    )
    application.status_changes.append(
        StatusChange(from_status=None, to_status=AppStatus.saved, changed_at=now)
    )
    session.add(application)
    posting.triage_status = TriageStatus.saved
    posting.triaged_at = now
    session.flush()
    return application


def unsave_posting(session: Session, posting_id: int) -> None:
    posting = _posting(session, posting_id)
    application = _application(session, posting_id)
    if application is None:
        raise ConflictError("not_saved", "Posting is not saved", {"posting_id": posting_id})
    if (
        application.status != AppStatus.saved
        or application.attachments
        or application.contacts
        or application.appointments
    ):
        raise ConflictError(
            "application_has_data",
            "Application already has data and cannot be removed",
            {"posting_id": posting_id, "application_id": application.id},
        )
    session.delete(application)
    posting.triage_status = TriageStatus.new
    posting.triaged_at = None
    session.flush()


def dismiss_posting(session: Session, posting_id: int, now: datetime) -> None:
    posting = _posting(session, posting_id)
    if _application(session, posting_id) is not None:
        raise ConflictError(
            "has_application",
            "Posting has an application and cannot be dismissed",
            {"posting_id": posting_id},
        )
    posting.triage_status = TriageStatus.dismissed
    posting.triaged_at = now
    session.flush()


def undismiss_posting(session: Session, posting_id: int) -> None:
    posting = _posting(session, posting_id)
    if posting.triage_status != TriageStatus.dismissed:
        raise ConflictError("not_dismissed", "Posting is not dismissed", {"posting_id": posting_id})
    posting.triage_status = TriageStatus.new
    posting.triaged_at = None
    session.flush()

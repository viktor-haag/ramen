from datetime import datetime

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, contains_eager

from app.errors import ConflictError, NotFoundError
from app.models import ACTIVE_STATUSES, Application, AppStatus, Posting, StatusChange
from app.schemas.application import (
    ApplicationDetailOut,
    ApplicationOut,
    ApplicationPatch,
    AppointmentOut,
    AttachmentOut,
    ContactOut,
    StatusChangeOut,
)
from app.services.feed import _like, postings_out


def can_transition(frm: AppStatus, to: AppStatus) -> bool:
    if frm not in ACTIVE_STATUSES:
        return False  # terminal states are left only via reopen()
    if to in ACTIVE_STATUSES:
        return frm != to
    if to == AppStatus.accepted:
        return frm == AppStatus.offer
    return True  # rejected / withdrawn


def get_application(session: Session, app_id: int) -> Application:
    application = session.get(Application, app_id)
    if application is None:
        raise NotFoundError(
            "application_not_found", "Application not found", {"application_id": app_id}
        )
    return application


def _record(
    session: Session, application: Application, to: AppStatus, comment: str | None, now: datetime
) -> None:
    application.status_changes.append(
        StatusChange(from_status=application.status, to_status=to, changed_at=now, comment=comment)
    )
    application.status = to
    application.updated_at = now
    session.flush()


def _invalid(frm: AppStatus, to: AppStatus) -> ConflictError:
    return ConflictError(
        "invalid_transition",
        f"Cannot change status from {frm.value} to {to.value}",
        {"from": frm.value, "to": to.value},
    )


def change_status(
    session: Session, app_id: int, to: AppStatus, comment: str | None, now: datetime
) -> Application:
    application = get_application(session, app_id)
    if not can_transition(application.status, to):
        raise _invalid(application.status, to)
    _record(session, application, to, comment, now)
    return application


def reopen(
    session: Session, app_id: int, to: AppStatus, comment: str | None, now: datetime
) -> Application:
    application = get_application(session, app_id)
    if application.status in ACTIVE_STATUSES:
        raise ConflictError(
            "not_terminal",
            "Only finished applications can be reopened",
            {"status": application.status.value},
        )
    if to not in ACTIVE_STATUSES:
        raise _invalid(application.status, to)
    _record(session, application, to, f"Reopened: {comment}" if comment else "Reopened", now)
    return application


def list_applications(
    session: Session, statuses: list[AppStatus] | None = None, q: str | None = None
) -> list[Application]:
    stmt = (
        select(Application)
        .join(Posting, Application.posting_id == Posting.id)
        .options(contains_eager(Application.posting))
    )
    stmt = stmt.where(Application.status.in_(statuses if statuses else ACTIVE_STATUSES))
    if q:
        stmt = stmt.where(or_(_like(Posting.title, q), _like(Posting.company, q)))
    stmt = stmt.order_by(Application.updated_at.desc(), Application.id.desc())
    return list(session.scalars(stmt))


def update_application(session: Session, app_id: int, patch: ApplicationPatch, now: datetime) -> Application:
    application = get_application(session, app_id)
    for name, value in patch.model_dump(exclude_unset=True).items():
        setattr(application, name, value)
    application.updated_at = now
    session.flush()
    return application


def applications_out(session: Session, applications: list[Application]) -> list[ApplicationOut]:
    """Batch-build API models (one query each for postings' extras and last status change)."""
    if not applications:
        return []
    postings = {p.id: p for p in postings_out(session, [a.posting for a in applications])}
    last = dict(
        session.execute(
            select(StatusChange.application_id, func.max(StatusChange.changed_at))
            .where(StatusChange.application_id.in_([a.id for a in applications]))
            .group_by(StatusChange.application_id)
        ).all()
    )
    return [
        ApplicationOut.model_validate(a, from_attributes=True).model_copy(
            update={"posting": postings[a.posting_id], "last_status_change_at": last.get(a.id)}
        )
        for a in applications
    ]


def application_detail(session: Session, application: Application) -> ApplicationDetailOut:
    base = applications_out(session, [application])[0]
    return ApplicationDetailOut(
        **base.model_dump(),
        status_changes=[StatusChangeOut.model_validate(c) for c in application.status_changes],
        appointments=[AppointmentOut.model_validate(c) for c in application.appointments],
        contacts=[ContactOut.model_validate(c) for c in application.contacts],
        attachments=[AttachmentOut.model_validate(c) for c in application.attachments],
    )

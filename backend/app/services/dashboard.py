from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Appointment, Application, AppStatus, Posting, RunStatus, StatusChange, TriageStatus
from app.schemas.application import AppointmentOut
from app.schemas.dashboard import DashboardOut, UpcomingOut
from app.services import profiles
from app.services.applications import applications_out

UPCOMING_DAYS = 7
STALE_DAYS = 14
RECENT_RUNS = 10
FAILED_HOURS = 24
FAILED_LIMIT = 200


def _upcoming(session: Session, now: datetime) -> list[UpcomingOut]:
    rows = session.execute(
        select(Appointment, Posting.title, Posting.company)
        .join(Application, Application.id == Appointment.application_id)
        .join(Posting, Posting.id == Application.posting_id)
        .where(Appointment.starts_at >= now, Appointment.starts_at <= now + timedelta(days=UPCOMING_DAYS))
        .order_by(Appointment.starts_at, Appointment.id)
    )
    return [
        UpcomingOut(
            appointment=AppointmentOut.model_validate(appt),
            application_id=appt.application_id, title=title, company=company,
        )
        for appt, title, company in rows
    ]


def _stale(session: Session, now: datetime):
    last = (
        select(StatusChange.application_id, func.max(StatusChange.changed_at).label("at"))
        .group_by(StatusChange.application_id)
        .subquery()
    )
    apps = session.scalars(
        select(Application)
        .outerjoin(last, last.c.application_id == Application.id)
        .where(
            Application.status == AppStatus.applied,
            func.coalesce(last.c.at, Application.created_at) < now - timedelta(days=STALE_DAYS),
        )
        .order_by(func.coalesce(last.c.at, Application.created_at), Application.id)
    ).all()
    return applications_out(session, list(apps))


def dashboard(session: Session, now: datetime) -> DashboardOut:
    new_count = session.scalar(
        select(func.count()).select_from(Posting).where(Posting.triage_status == TriageStatus.new)
    )
    failed = profiles.list_runs(
        session, statuses=(RunStatus.error, RunStatus.timeout),
        since=now - timedelta(hours=FAILED_HOURS), limit=FAILED_LIMIT,
    )
    return DashboardOut(
        new_count=new_count or 0,
        upcoming=_upcoming(session, now),
        stale=_stale(session, now),
        recent_runs=profiles.list_runs(session, limit=RECENT_RUNS),
        failed_runs=failed,
    )

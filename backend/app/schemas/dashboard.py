from pydantic import BaseModel

from app.schemas.application import AppointmentOut, ApplicationOut
from app.schemas.run import RunOut


class UpcomingOut(BaseModel):
    appointment: AppointmentOut
    application_id: int
    title: str
    company: str | None


class DashboardOut(BaseModel):
    new_count: int
    upcoming: list[UpcomingOut]
    stale: list[ApplicationOut]
    recent_runs: list[RunOut]
    older_failed_count: int  # failed runs of the last 24 h that are not in recent_runs

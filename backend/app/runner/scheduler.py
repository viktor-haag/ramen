import logging
import threading
from datetime import UTC

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.models import RunTrigger, SearchProfile
from app.runner.service import RunService

log = logging.getLogger(__name__)

JOB_PREFIX = "profile-"
MISFIRE_GRACE_SECONDS = 30  # missed runs are not caught up


class SchedulerManager:
    """One interval job per enabled profile with a schedule; `sync()` reconciles jobs with the DB."""

    def __init__(self, run_service: RunService, session_factory: sessionmaker[Session]):
        self._run_service = run_service
        self._session_factory = session_factory
        self._lock = threading.Lock()
        self._scheduler = BackgroundScheduler(
            timezone=UTC,
            job_defaults={"coalesce": True, "max_instances": 1, "misfire_grace_time": MISFIRE_GRACE_SECONDS},
        )

    def start(self) -> None:
        self._scheduler.start()

    def shutdown(self) -> None:
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)

    def jobs(self) -> dict[str, float]:
        """Job id -> interval in hours."""
        return {job.id: job.trigger.interval.total_seconds() / 3600 for job in self._scheduler.get_jobs()}

    def sync(self) -> None:
        # Read and apply under one lock: a stale snapshot must never be applied after a newer one.
        with self._lock:
            with self._session_factory() as session:
                wanted = {
                    f"{JOB_PREFIX}{p.id}": (p.id, p.schedule_hours)
                    for p in session.scalars(
                        select(SearchProfile).where(
                            SearchProfile.enabled.is_(True), SearchProfile.schedule_hours.is_not(None)
                        )
                    )
                }
            current = self.jobs()
            for job_id in current:
                if job_id.startswith(JOB_PREFIX) and job_id not in wanted:
                    self._scheduler.remove_job(job_id)
            for job_id, (profile_id, hours) in wanted.items():
                if current.get(job_id) == hours:
                    continue  # unchanged: keep its timer
                if job_id in current:
                    self._scheduler.remove_job(job_id)
                self._scheduler.add_job(
                    self._run, IntervalTrigger(hours=hours, timezone=UTC), args=[profile_id], id=job_id,
                    replace_existing=True, coalesce=True, max_instances=1,
                    misfire_grace_time=MISFIRE_GRACE_SECONDS,
                )

    def _run(self, profile_id: int) -> None:
        try:
            self._run_service.start_runs([profile_id], RunTrigger.schedule)
        except Exception:
            log.exception("Scheduled run of profile %s failed to start", profile_id)

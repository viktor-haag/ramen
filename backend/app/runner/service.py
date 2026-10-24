import logging
import threading
from collections.abc import Callable
from concurrent.futures import Future, TimeoutError
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from app.models import PluginSetting, RunStatus, RunTrigger, SearchProfile, SearchRun
from app.models.posting import utcnow
from app.plugins.base import Capability, SearchProfileDTO
from app.plugins.loader import PluginInfo
from app.plugins.registry import PluginRegistry
from app.runner.failures import describe, failure_text, split_timeout
from app.runner.pool import RunnerPool
from app.services.ingest import ingest

log = logging.getLogger(__name__)


def _profile_dtos(profile: SearchProfile) -> list[tuple[str, SearchProfileDTO]]:
    """One plugin DTO per keyword (the plugin contract takes a single search term)."""
    return [
        (
            keyword,
            SearchProfileDTO(
                keywords=keyword,
                location=profile.location,
                radius_km=profile.radius_km,
                employment_type=profile.employment_type,
                remote=profile.remote,
            ),
        )
        for keyword in profile.keywords or []
    ]


Outcome = tuple[str, Future]


@dataclass
class _Aggregate:
    """Per-keyword futures of one run, filled by pool callbacks (guarded by `_agg_lock`)."""

    keywords: list[str]
    timeout: int
    futures: list[Future | None] = field(init=False)  # positional: one slot per keyword
    remaining: int = field(init=False)

    def __post_init__(self) -> None:
        self.futures = [None] * len(self.keywords)
        self.remaining = len(self.keywords)


class RunService:
    """Starts search runs in the process pool and records their outcome.

    One run per (profile, plugin) fans out into one pool task per keyword. Pool callbacks
    run on a pebble thread (or inline for an already-finished future); the last keyword's
    callback records the run. Every DB write (the running-pair check and insert, and each
    run completion) is serialized by one lock (SQLite: single writer); the per-run keyword
    bookkeeping has its own lock and is never held while touching the DB.
    """

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        registry: PluginRegistry,
        pool: RunnerPool,
        clock: Callable[[], datetime] = utcnow,
        *,
        on_new_postings: Callable[[list[int]], None] | None = None,
    ):
        self._session_factory = session_factory
        self._registry = registry
        self._pool = pool
        self._clock = clock
        self._on_new_postings = on_new_postings
        self._db_lock = threading.Lock()
        self._agg_lock = threading.Lock()
        self._aggregates: dict[int, _Aggregate] = {}
        self._idle = threading.Condition()
        self._pending: set[int] = set()

    @property
    def db_lock(self) -> threading.Lock:
        """The lock serializing DB writes of runs; admin operations hold it from check to commit."""
        return self._db_lock

    def effective_plugins(self, session: Session, profile: SearchProfile) -> list[PluginInfo]:
        wanted = set(profile.plugins or [])
        disabled = set(session.scalars(select(PluginSetting.plugin).where(PluginSetting.enabled.is_(False))))
        return [
            info
            for info in self._registry.usable()
            if Capability.SEARCH in info.capabilities
            and (not wanted or info.name in wanted)
            and info.name not in disabled
        ]

    def start_runs(self, profile_ids: list[int] | None, trigger: RunTrigger) -> list[int]:
        """Create one SearchRun per (profile, plugin) not already running; submit one task per keyword.

        A profile without keywords still gets its runs, finished at once as an error.
        """
        jobs: list[tuple[int, PluginInfo, list[tuple[str, SearchProfileDTO]], dict, int]] = []
        with self._db_lock, self._session_factory() as session:
            stmt = select(SearchProfile)
            if profile_ids is None:
                stmt = stmt.where(SearchProfile.enabled.is_(True))
            else:
                stmt = stmt.where(SearchProfile.id.in_(profile_ids))
            profiles = session.scalars(stmt.order_by(SearchProfile.id)).all()
            running = {
                (profile_id, plugin)
                for profile_id, plugin in session.execute(
                    select(SearchRun.profile_id, SearchRun.plugin).where(SearchRun.status == RunStatus.running)
                )
            }
            settings = {ps.plugin: ps.settings or {} for ps in session.scalars(select(PluginSetting))}
            created = []
            for profile in profiles:
                dtos = _profile_dtos(profile)
                for info in self.effective_plugins(session, profile):
                    if (profile.id, info.name) in running:
                        continue
                    now = self._clock()
                    run = SearchRun(
                        profile_id=profile.id, plugin=info.name, trigger=trigger,
                        status=RunStatus.running, started_at=now,
                    )
                    if not dtos:
                        run.status, run.error, run.finished_at = RunStatus.error, "no keywords", now
                    session.add(run)
                    timeout, plugin_settings = split_timeout(info, settings.get(info.name))
                    created.append((run, info, dtos, plugin_settings, timeout))
            session.commit()
            run_ids = [run.id for run, *_ in created]
            jobs = [(run.id, info, dtos, s, t) for run, info, dtos, s, t in created if dtos]

        # Submit outside the lock: an already-finished future runs its callback inline.
        for run_id, info, dtos, plugin_settings, timeout in jobs:
            with self._idle:
                self._pending.add(run_id)
            # register before the first submit: its callback may fire inline
            with self._agg_lock:
                self._aggregates[run_id] = _Aggregate([keyword for keyword, _ in dtos], timeout)
            for index, (_, dto) in enumerate(dtos):
                try:
                    future = self._pool.submit(info, dto, plugin_settings, timeout)
                except Exception as exc:
                    failed: Future = Future()
                    failed.set_exception(exc)
                    self._keyword_done(run_id, index, failed)
                    continue
                future.add_done_callback(lambda f, r=run_id, i=index: self._keyword_done(r, i, f))
        return run_ids

    def _keyword_done(self, run_id: int, index: int, future: Future) -> None:
        """Pool callback per keyword: the last one of a run records the whole run."""
        with self._agg_lock:
            aggregate = self._aggregates[run_id]
            aggregate.futures[index] = future
            aggregate.remaining -= 1
            if aggregate.remaining:
                return
            del self._aggregates[run_id]
        outcomes: list[Outcome] = list(zip(aggregate.keywords, aggregate.futures))
        self._finish(run_id, outcomes, aggregate.timeout)

    def _finish(self, run_id: int, outcomes: list[Outcome], timeout: int) -> None:
        """Record the outcome of all keywords. Never leaves the run `running` on own failure."""
        new_ids: list[int] | None = None
        try:
            with self._db_lock:
                try:
                    new_ids = self._record(run_id, outcomes, timeout)
                except Exception as exc:  # callback exceptions would be swallowed silently
                    log.exception("Recording outcome of search run %s failed", run_id)
                    self._mark_failed(run_id, exc)
            # After the commit and outside db_lock (the hook takes its own locks and writes to the DB);
            # still before the run counts as idle, so wait_idle covers the hook.
            if new_ids is not None and self._on_new_postings is not None:
                try:
                    self._on_new_postings(new_ids)
                except Exception:
                    log.exception("on_new_postings hook failed for search run %s", run_id)
        finally:
            with self._idle:
                self._pending.discard(run_id)
                self._idle.notify_all()

    def _record(self, run_id: int, outcomes: list[Outcome], timeout: int) -> list[int]:
        """Record the run and commit; returns the ids of the postings it created."""
        new_ids: list[int] = []
        with self._session_factory() as session:
            run = session.get(SearchRun, run_id)
            if run is None:
                log.warning("Search run %s vanished before it finished", run_id)
                return new_ids
            now = self._clock()  # fresh per completion: ingest counts first_seen_at == now as new
            items: list[dict] = []
            failures: list[tuple[str, BaseException]] = []
            succeeded = False
            problems: list[str] = []
            for keyword, future in outcomes:
                try:
                    items.extend(future.result())
                    succeeded = True
                except Exception as exc:
                    failures.append((keyword, exc))
            if succeeded:
                profile = session.get(SearchProfile, run.profile_id) if run.profile_id else None
                if profile is None:
                    run.status = RunStatus.error
                    problems.append("Search profile no longer exists")
                else:
                    result = ingest(session, profile=profile, source=run.plugin, items=items, now=now)
                    run.status = RunStatus.ok
                    run.new_count = result.new_count
                    run.total_count = result.total_count
                    run.invalid_count = result.invalid_count
                    new_ids = result.new_ids
            if failures:
                first = failures[0][1]
                run.status = RunStatus.timeout if isinstance(first, TimeoutError) else RunStatus.error
                problems.extend(f'"{keyword}": {failure_text(exc, timeout)}' for keyword, exc in failures)
            if problems:
                run.error = "; ".join(problems)
            run.finished_at = now
            session.commit()
        return new_ids

    def _mark_failed(self, run_id: int, exc: Exception) -> None:
        """Best effort, fresh session: the failed one may hold a broken transaction."""
        try:
            with self._session_factory() as session:
                session.execute(
                    update(SearchRun)
                    .where(SearchRun.id == run_id, SearchRun.status == RunStatus.running)
                    .values(status=RunStatus.error, error=describe(exc), finished_at=self._clock())
                )
                session.commit()
        except Exception:
            log.exception("Could not mark search run %s as failed", run_id)

    def wait_idle(self, timeout: float) -> bool:
        """Block until no submitted run is pending; False on timeout."""
        with self._idle:
            return self._idle.wait_for(lambda: not self._pending, timeout)

    def recover_stale_runs(self, session: Session) -> int:
        """Mark runs left `running` by a previous process as aborted. The caller commits."""
        result = session.execute(
            update(SearchRun)
            .where(SearchRun.status == RunStatus.running)
            .values(status=RunStatus.error, error="Aborted by restart", finished_at=self._clock())
        )
        return result.rowcount

"""In-process queue for fit evaluations.

One thread pool (`max_workers` threads) runs the jobs; a condition gate keeps at most `fit_concurrency`
evaluations running at once (the setting is re-read whenever a job waits for a slot). Every DB write is a
short transaction under `_lock` (SQLite: single writer), and no session is held while `evaluate` runs.
`discard_all` and `cancel_all` bump an epoch: jobs of an older epoch never start and never write. `shutdown` drops the jobs
still waiting for a slot and lets running ones write their results. Within one epoch, a circuit breaker ends
the bulk/auto jobs already queued at that moment without calling the LLM after BREAKER_THRESHOLD consecutive
provider failures; jobs queued later run normally.
"""
import itertools
import logging
import threading
import time
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Literal

from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from app.errors import AppError, ConflictError
from app.models import FitRating, FitStatus, Posting, PostingFit, UserProfile
from app.models.posting import utcnow
from app.services import fit, llm_configs, usage
from app.services.settings import get_settings

log = logging.getLogger(__name__)

Kind = Literal["single", "bulk", "auto"]
SLOT_POLL_SECONDS = 0.5  # waiting jobs re-read `fit_concurrency` at least this often
ERROR_RETRY_SECONDS = 1.0  # pause before the one retry of a failed error write
ACTIVE = (FitStatus.queued, FitStatus.running)
BREAKER_THRESHOLD = 3  # consecutive bulk/auto failures with one of BREAKER_CODES that trip the breaker
BREAKER_CODES = frozenset({"llm_timeout", "llm_unavailable", "llm_auth_failed"})


def ensure_ready(session: Session) -> None:
    """409 `profile_missing` without a non-blank profile, 409 `llm_not_configured` without a `fit` config."""
    profile = session.get(UserProfile, 1)
    if profile is None or not (profile.profile_markdown or "").strip():
        raise ConflictError("profile_missing", "There is no user profile to evaluate against", {})
    llm_configs.resolve(session, "fit")


class FitQueue:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        evaluate: Callable[..., fit.FitResult] = fit.evaluate,
        max_workers: int = 8,
    ):
        self._session_factory = session_factory
        self._evaluate = evaluate
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="fit")
        self._lock = threading.Lock()  # enqueue, epoch changes and every job write
        self._cond = threading.Condition()  # running slots and the in-memory job list
        self._epoch = 0
        self._running = 0
        self._jobs: dict[int, Future | None] = {}  # queued or running jobs of this process
        self._job_epochs: dict[int, int] = {}  # epoch each job in `_jobs` was queued in
        self._ids = itertools.count()
        self._closed = False
        self._last_seq = -1  # highest job sequence number (= job id) submitted so far
        self._streak = 0  # consecutive bulk/auto BREAKER_CODES failures in `_streak_epoch`
        self._streak_epoch = 0
        self._trip: tuple[int, int, str] | None = None  # (epoch, highest seq it covers, code) of the last trip

    # --- public API -------------------------------------------------------------------------------

    def enqueue(self, posting_ids: list[int], *, lang: str, kind: Kind) -> int:
        """Queue each posting once (skips `queued`/`running` rows and unknown postings); returns the count."""
        with self._lock:
            if self._closed:
                return 0
            wanted = list(dict.fromkeys(posting_ids))
            with self._session_factory() as session:
                existing = set(session.scalars(select(Posting.id).where(Posting.id.in_(wanted))))
                rows = {r.posting_id: r for r in session.scalars(
                    select(PostingFit).where(PostingFit.posting_id.in_(wanted)))}
                ids = []
                for pid in wanted:
                    row = rows.get(pid)
                    if pid not in existing or (row is not None and row.status in ACTIVE):
                        continue
                    if row is None:
                        session.add(PostingFit(posting_id=pid, status=FitStatus.queued))
                    else:  # R3: rating and explanation stay until the new result is written
                        row.status, row.error = FitStatus.queued, None
                    ids.append(pid)
                session.commit()
            epoch = self._epoch
            for pid in ids:
                job_id = next(self._ids)
                with self._cond:
                    self._jobs[job_id] = None  # registered before it can finish
                    self._job_epochs[job_id] = epoch
                    self._last_seq = job_id
                future = self._executor.submit(self._job, job_id, pid, lang, kind, epoch)
                with self._cond:
                    if job_id in self._jobs:
                        self._jobs[job_id] = future
            return len(ids)

    def enqueue_auto(self, posting_ids: list[int]) -> int:
        """Auto-fit after a search run: queue the postings unless disabled, not ready or over the daily limit (R1)."""
        if not posting_ids:
            return 0
        with self._session_factory() as session:
            settings = get_settings(session)
            if not settings.fit_auto:
                return 0
            try:
                ensure_ready(session)
            except ConflictError as exc:
                log.info("auto fit skipped: %s", exc.code)
                return 0
            if usage.limit_exceeded(session, utcnow()):
                log.info("auto fit skipped: daily limit reached")
                return 0
            lang = settings.fit_language
        return self.enqueue(posting_ids, lang=lang, kind="auto")

    def discard_all(self) -> None:
        """R4: queued jobs are dropped, running jobs write nothing; their rows become `error="discarded"`."""
        with self._lock:
            with self._cond:
                self._epoch += 1  # under `_cond` too: `_acquire_slot` and `_track` read it there
                for job_id, future in list(self._jobs.items()):
                    if future is not None and future.cancel():
                        del self._jobs[job_id]
                        self._job_epochs.pop(job_id, None)
                self._cond.notify_all()  # jobs waiting for a slot see the new epoch and end
            with self._session_factory() as session:
                session.execute(
                    update(PostingFit).where(PostingFit.status.in_(ACTIVE))
                    .values(status=FitStatus.error, error="discarded")
                )
                session.commit()

    def cancel_all(self) -> int:
        """User cancel: like `discard_all`, but active rows return to their previous state, not to an error.

        A row with a rating (R3 kept it while re-evaluating) becomes `done` again, a row without one is
        deleted (the posting is "not evaluated"). Returns the number of rows that were active. The breaker
        needs no reset: its trip and streak are tied to the epoch, which this bumps.
        """
        with self._lock:
            with self._cond:
                self._epoch += 1
                # Old-epoch jobs already inside `evaluate` keep their `_running` slot until the LLM call returns,
                # so a new evaluation right after a cancel may wait for them (same as `discard_all`).
                for job_id, future in list(self._jobs.items()):
                    if future is not None and future.cancel():
                        del self._jobs[job_id]
                        self._job_epochs.pop(job_id, None)
                self._cond.notify_all()
            with self._session_factory() as session:
                rows = session.scalars(select(PostingFit).where(PostingFit.status.in_(ACTIVE))).all()
                for row in rows:
                    if row.rating is None:
                        session.delete(row)
                    else:
                        row.status, row.error = FitStatus.done, None
                session.commit()
                return len(rows)

    def recover(self, session: Session) -> int:
        """At start: rows left `queued`/`running` by an earlier process become errors (caller commits)."""
        result = session.execute(
            update(PostingFit).where(PostingFit.status.in_(ACTIVE))
            .values(status=FitStatus.error, error="aborted_by_restart")
        )
        return result.rowcount

    def active_count(self) -> int:
        """Queued or running jobs of the current epoch (`wait_idle` also waits for older ones)."""
        with self._cond:
            # jobs of an older epoch (running ones after discard/cancel) are finished business for the user
            return sum(1 for e in self._job_epochs.values() if e == self._epoch)

    def wait_idle(self, timeout: float) -> bool:
        with self._cond:
            return self._cond.wait_for(lambda: not self._jobs, timeout)

    def shutdown(self) -> None:
        """Waiting jobs are dropped (their rows are recovered at the next start); running jobs finish and write."""
        with self._lock:
            with self._cond:
                self._closed = True
                self._cond.notify_all()
        self._executor.shutdown(wait=True, cancel_futures=True)

    # --- job ---------------------------------------------------------------------------------------

    def _job(self, job_id: int, posting_id: int, lang: str, kind: Kind, epoch: int) -> None:
        state = _JobState()
        try:
            if not self._acquire_slot(epoch):
                return
            try:
                self._run(job_id, posting_id, lang, kind, epoch, state)
            finally:
                with self._cond:
                    self._running -= 1
                    self._cond.notify_all()
        except Exception:  # never raise out of the executor
            log.exception("fit evaluation of posting %s failed", posting_id)
            self._record_failure(posting_id, epoch, state)
        finally:
            if state.started and not state.settled:  # the row would stay `running` until the next start
                time.sleep(ERROR_RETRY_SECONDS)
                self._record_failure(posting_id, epoch, state)
            with self._cond:
                self._jobs.pop(job_id, None)
                self._job_epochs.pop(job_id, None)
                self._cond.notify_all()

    def _record_failure(self, posting_id: int, epoch: int, state: "_JobState") -> None:
        try:
            self._write(posting_id, epoch, status=FitStatus.error, error="llm_unavailable")
            state.settled = True
        except Exception:
            log.exception("could not record the failed fit evaluation of posting %s", posting_id)

    def _concurrency(self) -> int:
        with self._session_factory() as session:
            return get_settings(session).fit_concurrency

    def _acquire_slot(self, epoch: int) -> bool:
        while True:
            limit = self._concurrency()  # re-read per attempt: a changed setting applies to waiting jobs
            with self._cond:
                if epoch != self._epoch or self._closed:
                    return False
                if self._running < limit:
                    self._running += 1
                    return True
                self._cond.wait(SLOT_POLL_SECONDS)

    def _run(self, seq: int, posting_id: int, lang: str, kind: Kind, epoch: int, state: "_JobState") -> None:
        if kind != "single":
            tripped = self._short_circuit_code(epoch, seq)
            if tripped is not None:  # the provider keeps failing: do not spend the rest of the batch on it
                self._write(posting_id, epoch, status=FitStatus.error, error=tripped)
                return
            with self._session_factory() as session:  # R1: bulk and auto respect the daily limit
                exceeded = usage.limit_exceeded(session, utcnow())
            if exceeded:
                self._write(posting_id, epoch, status=FitStatus.error, error="daily_limit")
                return
        if not self._write(posting_id, epoch, status=FitStatus.running):
            return  # discarded, or the posting / row is gone
        state.started = True
        try:
            result = self._evaluate(self._session_factory, posting_id, lang)
        except AppError as exc:
            self._track(epoch, kind, exc.code)
            self._write(posting_id, epoch, status=FitStatus.error, error=exc.code)
            state.settled = True
            return
        self._track(epoch, kind, None)
        self._write(
            posting_id, epoch, status=FitStatus.done, error=None, rating=FitRating(result.rating),
            explanation=result.explanation, profile_version=result.profile_version, evaluated_at=utcnow(),
        )
        state.settled = True

    def _short_circuit_code(self, epoch: int, seq: int) -> str | None:
        """The trip's code for a bulk/auto job of the tripped epoch that was queued before the trip, else None."""
        with self._cond:
            if self._trip is not None and self._trip[0] == epoch and seq <= self._trip[1]:
                return self._trip[2]
            return None

    def _track(self, epoch: int, kind: Kind, code: str | None) -> None:
        """Any success resets the streak; only bulk/auto failures with a BREAKER_CODES code extend it.

        On the BREAKER_THRESHOLD-th failure the breaker trips for every job submitted so far and the streak
        starts over, so jobs queued later get a fresh chance. Results of an older epoch are ignored.
        """
        with self._cond:
            if epoch != self._epoch:
                return
            if self._streak_epoch != epoch:
                self._streak_epoch, self._streak = epoch, 0
            if code is None:
                self._streak = 0
            elif kind == "single":
                return
            elif code in BREAKER_CODES:
                self._streak += 1
                if self._streak >= BREAKER_THRESHOLD:
                    self._trip = (epoch, self._last_seq, code)
                    self._streak = 0
            else:
                self._streak = 0

    def _write(self, posting_id: int, epoch: int, **fields) -> bool:
        """Update the job's row; nothing when the epoch changed or the row is gone. Returns whether it wrote."""
        with self._lock:
            if epoch != self._epoch:
                return False
            with self._session_factory() as session:
                row = session.get(PostingFit, posting_id)
                if row is None:
                    return False
                for name, value in fields.items():
                    setattr(row, name, value)
                session.commit()
                return True


class _JobState:
    """`started`: the job set its row to `running`; `settled`: a terminal write went through (or was not needed)."""

    __slots__ = ("started", "settled")

    def __init__(self) -> None:
        self.started = False
        self.settled = False

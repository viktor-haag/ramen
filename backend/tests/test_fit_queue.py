import threading
from datetime import UTC, datetime

import pytest

from app.errors import UpstreamError
from app.fit.queue import FitQueue
from app.models import AppSetting, FitRating, FitStatus, LLMUsage, Posting, PostingFit, UserProfile
from app.services.fit import FitResult

TIMEOUT = 10


class FakeEval:
    """Records calls; optionally blocks each call until `release` is set."""

    def __init__(self, *, block=False, error=None, on_call=None):
        self.calls: list[tuple[int, str]] = []
        self.block = block
        self.error = error
        self.on_call = on_call
        self.release = threading.Event()
        self.lock = threading.Lock()
        self.running = 0
        self.max_running = 0
        self.started = threading.Semaphore(0)

    def __call__(self, session_factory, posting_id, lang):
        with self.lock:
            self.calls.append((posting_id, lang))
            self.running += 1
            self.max_running = max(self.max_running, self.running)
        self.started.release()
        try:
            if self.block:
                assert self.release.wait(TIMEOUT)
            if self.on_call:
                self.on_call(posting_id)
            if self.error:
                raise self.error
            return FitResult("good", f"Fits {posting_id}.", 3, False)
        finally:
            with self.lock:
                self.running -= 1


@pytest.fixture
def sf(client, app):
    return app.state.session_factory


@pytest.fixture
def make_queue(sf):
    queues = []

    def make(fake):
        q = FitQueue(sf, evaluate=fake)
        queues.append(q)
        return q

    yield make
    for q in queues:
        q.shutdown()


def add_postings(sf, n):
    with sf() as s:
        s.add(UserProfile(id=1, profile_markdown="## Summary\nDev.", version=3,
                          edited_since_generation=False, inputs_changed_since_generation=False))
        ps = [Posting(source="src", external_id=str(i), title=f"P{i}") for i in range(n)]
        s.add_all(ps)
        s.commit()
        return [p.id for p in ps]


def set_setting(sf, key, value):
    with sf() as s:
        row = s.get(AppSetting, key)
        if row is None:
            s.add(AppSetting(key=key, value=value))
        else:
            row.value = value
        s.commit()


def fit_row(sf, posting_id) -> PostingFit | None:
    with sf() as s:
        return s.get(PostingFit, posting_id)


def test_enqueue_skips_active_and_missing(sf, make_queue):
    a, b = add_postings(sf, 2)
    with sf() as s:
        s.add(PostingFit(posting_id=a, status=FitStatus.queued))
        s.commit()
    fake = FakeEval()
    q = make_queue(fake)
    assert q.enqueue([a, b, 99999, b], lang="de", kind="single") == 1
    assert q.wait_idle(TIMEOUT)
    assert fake.calls == [(b, "de")]
    assert fit_row(sf, a).status == FitStatus.queued  # untouched
    assert fit_row(sf, 99999) is None


def test_concurrency_respected(sf, make_queue):
    ids = add_postings(sf, 5)
    set_setting(sf, "fit_concurrency", 2)
    fake = FakeEval(block=True)
    q = make_queue(fake)
    assert q.enqueue(ids, lang="en", kind="single") == 5
    assert fake.started.acquire(timeout=TIMEOUT) and fake.started.acquire(timeout=TIMEOUT)
    assert not fake.started.acquire(timeout=0.3)  # a third job does not start while two run
    assert q.active_count() == 5
    statuses = sorted(fit_row(sf, i).status for i in ids)
    assert statuses.count(FitStatus.running) == 2 and statuses.count(FitStatus.queued) == 3
    fake.release.set()
    assert q.wait_idle(TIMEOUT)
    assert fake.max_running == 2
    assert all(fit_row(sf, i).status == FitStatus.done for i in ids)
    assert q.active_count() == 0


def test_status_transitions_and_result(sf, make_queue):
    (pid,) = add_postings(sf, 1)
    seen = []
    fake = FakeEval(block=True, on_call=lambda p: seen.append(fit_row(sf, p).status))
    q = make_queue(fake)
    q.enqueue([pid], lang="en", kind="single")
    assert fake.started.acquire(timeout=TIMEOUT)
    fake.release.set()
    assert q.wait_idle(TIMEOUT)
    assert seen == [FitStatus.running]
    row = fit_row(sf, pid)
    assert row.status == FitStatus.done and row.rating == FitRating.good
    assert row.explanation == f"Fits {pid}." and row.profile_version == 3 and row.error is None
    assert (datetime.now(UTC) - row.evaluated_at).total_seconds() < 60


def test_queued_state_after_enqueue(sf, make_queue):
    (pid,) = add_postings(sf, 1)
    set_setting(sf, "fit_concurrency", 1)
    fake = FakeEval(block=True)
    q = make_queue(fake)
    with sf() as s:  # R3: an earlier result stays visible while re-evaluating
        s.add(PostingFit(posting_id=pid, status=FitStatus.error, error="llm_timeout", rating=FitRating.poor,
                         explanation="old"))
        s.commit()
    other = add_more(sf)
    q.enqueue([other], lang="en", kind="single")
    assert fake.started.acquire(timeout=TIMEOUT)
    q.enqueue([pid], lang="en", kind="single")
    row = fit_row(sf, pid)
    assert row.status == FitStatus.queued and row.error is None
    assert row.rating == FitRating.poor and row.explanation == "old"
    fake.release.set()
    assert q.wait_idle(TIMEOUT)


def add_more(sf):
    with sf() as s:
        p = Posting(source="src", external_id="extra", title="Extra")
        s.add(p)
        s.commit()
        return p.id


def test_error_code_is_stored(sf, make_queue):
    (pid,) = add_postings(sf, 1)
    with sf() as s:
        s.add(PostingFit(posting_id=pid, status=FitStatus.done, rating=FitRating.moderate, explanation="old",
                         profile_version=2))
        s.commit()
    q = make_queue(FakeEval(error=UpstreamError("llm_timeout", "timeout")))
    assert q.enqueue([pid], lang="en", kind="single") == 1
    assert q.wait_idle(TIMEOUT)
    row = fit_row(sf, pid)
    assert row.status == FitStatus.error and row.error == "llm_timeout"
    assert row.rating == FitRating.moderate and row.explanation == "old" and row.profile_version == 2


def test_unexpected_exception_marks_unavailable(sf, make_queue):
    (pid,) = add_postings(sf, 1)
    q = make_queue(FakeEval(error=RuntimeError("boom")))
    q.enqueue([pid], lang="en", kind="single")
    assert q.wait_idle(TIMEOUT)
    row = fit_row(sf, pid)
    assert row.status == FitStatus.error and row.error == "llm_unavailable"


def test_posting_deleted_while_running(sf, make_queue):
    (pid,) = add_postings(sf, 1)

    def delete(p):
        with sf() as s:
            s.delete(s.get(Posting, p))
            s.commit()

    q = make_queue(FakeEval(on_call=delete))
    q.enqueue([pid], lang="en", kind="single")
    assert q.wait_idle(TIMEOUT)
    assert fit_row(sf, pid) is None
    with sf() as s:
        assert s.get(Posting, pid) is None


def test_daily_limit_bulk_vs_single(sf, make_queue):
    a, b, c = add_postings(sf, 3)
    set_setting(sf, "daily_limit_kind", "tokens")
    set_setting(sf, "daily_limit_value", 100)
    with sf() as s:
        s.add(LLMUsage(purpose="fit", input_tokens=100, output_tokens=50, ok=True))
        s.commit()
    fake = FakeEval()
    q = make_queue(fake)
    q.enqueue([a], lang="en", kind="bulk")
    q.enqueue([b], lang="en", kind="auto")
    assert q.wait_idle(TIMEOUT)
    q.enqueue([c], lang="en", kind="single")
    assert q.wait_idle(TIMEOUT)
    assert fake.calls == [(c, "en")]
    for pid in (a, b):
        row = fit_row(sf, pid)
        assert row.status == FitStatus.error and row.error == "daily_limit"
    assert fit_row(sf, c).status == FitStatus.done


def test_recover_marks_aborted(sf, make_queue):
    a, b, c = add_postings(sf, 3)
    with sf() as s:
        s.add_all([
            PostingFit(posting_id=a, status=FitStatus.queued),
            PostingFit(posting_id=b, status=FitStatus.running, rating=FitRating.good, explanation="kept"),
            PostingFit(posting_id=c, status=FitStatus.done, rating=FitRating.poor, explanation="x"),
        ])
        s.commit()
    q = make_queue(FakeEval())
    with sf() as s:
        assert q.recover(s) == 2
        s.commit()
    for pid in (a, b):
        row = fit_row(sf, pid)
        assert row.status == FitStatus.error and row.error == "aborted_by_restart"
    assert fit_row(sf, b).rating == FitRating.good
    row = fit_row(sf, c)
    assert row.status == FitStatus.done and row.error is None


def test_discard_all(sf, make_queue):
    ids = add_postings(sf, 3)
    set_setting(sf, "fit_concurrency", 1)
    fake = FakeEval(block=True)
    q = make_queue(fake)
    q.enqueue(ids, lang="en", kind="single")
    assert fake.started.acquire(timeout=TIMEOUT)
    q.discard_all()
    assert q.active_count() == 0
    rows = {i: fit_row(sf, i) for i in ids}
    assert all(r.status == FitStatus.error and r.error == "discarded" for r in rows.values())
    fake.release.set()
    assert q.wait_idle(TIMEOUT)
    assert len(fake.calls) == 1  # queued jobs never ran
    assert all(fit_row(sf, i).error == "discarded" for i in ids)  # the running job wrote nothing
    assert q.active_count() == 0
    # the queue keeps working after a discard
    assert q.enqueue([ids[1]], lang="en", kind="single") == 1
    assert q.wait_idle(TIMEOUT)
    assert fit_row(sf, ids[1]).status == FitStatus.done


def test_cancel_all_restores_previous_state(sf, make_queue):
    ids = add_postings(sf, 4)
    rated, unrated, queued_rated, queued_unrated = ids
    when = datetime(2026, 1, 1, tzinfo=UTC)
    with sf() as s:
        for pid in (rated, queued_rated):
            s.add(PostingFit(posting_id=pid, status=FitStatus.done, rating=FitRating.good, explanation="old",
                             profile_version=2, evaluated_at=when))
        s.commit()
    set_setting(sf, "fit_concurrency", 2)
    fake = FakeEval(block=True)
    q = make_queue(fake)
    assert q.enqueue([rated, unrated, queued_rated, queued_unrated], lang="en", kind="single") == 4
    assert fake.started.acquire(timeout=TIMEOUT) and fake.started.acquire(timeout=TIMEOUT)
    assert q.cancel_all() == 4
    assert q.active_count() == 0  # the two running jobs are still blocked in evaluate
    for pid in (rated, queued_rated):
        row = fit_row(sf, pid)
        assert row.status == FitStatus.done and row.error is None
        assert row.rating == FitRating.good and row.explanation == "old" and row.profile_version == 2
    assert fit_row(sf, unrated) is None and fit_row(sf, queued_unrated) is None
    fake.release.set()
    assert q.wait_idle(TIMEOUT)
    assert len(fake.calls) == 2  # queued jobs never ran
    assert fit_row(sf, unrated) is None  # the running jobs wrote nothing
    assert fit_row(sf, rated).explanation == "old" and fit_row(sf, rated).profile_version == 2
    assert q.active_count() == 0


def test_cancel_all_nothing_active_and_queue_keeps_working(sf, make_queue):
    ids = add_postings(sf, 2)
    fake = FakeEval()
    q = make_queue(fake)
    assert q.cancel_all() == 0
    assert q.enqueue(ids, lang="en", kind="bulk") == 2
    assert q.wait_idle(TIMEOUT)
    assert all(fit_row(sf, i).status == FitStatus.done for i in ids)


def test_cancel_all_then_enqueue_runs_normally(sf, make_queue):
    ids = add_postings(sf, 3)
    set_setting(sf, "fit_concurrency", 1)
    fake = FakeEval(block=True)
    q = make_queue(fake)
    q.enqueue(ids[:2], lang="en", kind="single")
    assert fake.started.acquire(timeout=TIMEOUT)
    assert q.cancel_all() == 2
    fake.release.set()
    assert q.enqueue([ids[0], ids[2]], lang="en", kind="single") == 2  # while the old job may still be finishing
    assert q.wait_idle(TIMEOUT)
    assert fit_row(sf, ids[0]).status == FitStatus.done and fit_row(sf, ids[2]).status == FitStatus.done
    assert fit_row(sf, ids[1]) is None


def test_cancel_all_does_not_leak_breaker_state(sf, make_queue):
    ids = add_postings(sf, 4)
    set_setting(sf, "fit_concurrency", 1)
    fake = ScriptedEval([timeout_error()] * 3)  # the provider recovers after three timeouts
    q = make_queue(fake)
    assert q.enqueue(ids, lang="en", kind="bulk") == 4
    assert q.wait_idle(TIMEOUT)
    assert all(fit_row(sf, i).error == "llm_timeout" for i in ids)  # the breaker tripped
    assert q.cancel_all() == 0
    assert q.enqueue(ids, lang="en", kind="bulk") == 4  # a fresh epoch: the old trip does not apply
    assert q.wait_idle(TIMEOUT)
    assert len(fake.calls) == 7
    assert all(fit_row(sf, i).status == FitStatus.done for i in ids)


def test_concurrency_reread_per_job(sf, make_queue):
    ids = add_postings(sf, 3)
    set_setting(sf, "fit_concurrency", 1)
    fake = FakeEval(block=True)
    q = make_queue(fake)
    q.enqueue(ids, lang="en", kind="single")
    assert fake.started.acquire(timeout=TIMEOUT)
    assert not fake.started.acquire(timeout=0.3)
    set_setting(sf, "fit_concurrency", 3)
    assert fake.started.acquire(timeout=TIMEOUT) and fake.started.acquire(timeout=TIMEOUT)
    fake.release.set()
    assert q.wait_idle(TIMEOUT)


def add_llm_config(sf):
    from app.models import LLMConfig, LLMProvider
    with sf() as s:
        s.add(LLMConfig(name="L", provider=LLMProvider.openai, model="m", api_key="sk-test-1234", is_default=True))
        s.commit()


def test_enqueue_auto_conditions(sf, make_queue):
    ids = add_postings(sf, 4)
    fake = FakeEval()
    q = make_queue(fake)

    def queued():
        with sf() as s:
            return s.query(PostingFit).count()

    assert q.enqueue_auto([]) == 0
    add_llm_config(sf)
    assert q.enqueue_auto(ids) == 0 and queued() == 0  # fit_auto off
    set_setting(sf, "fit_auto", True)
    set_setting(sf, "fit_language", "de")
    with sf() as s:  # blank profile
        s.get(UserProfile, 1).profile_markdown = "  "
        s.commit()
    assert q.enqueue_auto(ids) == 0 and queued() == 0
    with sf() as s:
        s.get(UserProfile, 1).profile_markdown = "## Summary\nDev."
        s.commit()
    set_setting(sf, "daily_limit_kind", "tokens")
    set_setting(sf, "daily_limit_value", 100)
    with sf() as s:
        s.add(LLMUsage(purpose="fit", input_tokens=100, output_tokens=50, ok=True))
        s.commit()
    assert q.enqueue_auto(ids) == 0 and queued() == 0  # daily limit exceeded
    set_setting(sf, "daily_limit_kind", "none")
    assert q.enqueue_auto(ids) == 4
    assert q.wait_idle(TIMEOUT)
    assert sorted(fake.calls) == sorted((i, "de") for i in ids)


def test_enqueue_auto_without_llm_config(sf, make_queue):
    ids = add_postings(sf, 1)
    set_setting(sf, "fit_auto", True)
    q = make_queue(FakeEval())
    assert q.enqueue_auto(ids) == 0
    assert fit_row(sf, ids[0]) is None


def test_job_running_during_shutdown_still_writes_done(sf, make_queue):
    a, b = add_postings(sf, 2)
    set_setting(sf, "fit_concurrency", 1)
    fake = FakeEval(block=True)
    q = make_queue(fake)
    q.enqueue([a, b], lang="en", kind="single")
    assert fake.started.acquire(timeout=TIMEOUT)
    running = next(i for i in (a, b) if fit_row(sf, i).status == FitStatus.running)
    waiting = b if running == a else a
    stopper = threading.Thread(target=q.shutdown)
    stopper.start()
    stopper.join(0.3)
    assert stopper.is_alive()  # shutdown waits for the running evaluation
    fake.release.set()
    stopper.join(TIMEOUT)
    assert not stopper.is_alive()
    row = fit_row(sf, running)
    assert row.status == FitStatus.done and row.rating == FitRating.good
    assert len(fake.calls) == 1  # the queued job was dropped
    assert fit_row(sf, waiting).status == FitStatus.queued  # recovered at the next start
    assert q.enqueue([waiting], lang="en", kind="single") == 0  # closed


class FlakyCommits:
    """Session factory wrapper: once armed, the next `n` commits raise OperationalError."""

    def __init__(self, sf):
        self.sf = sf
        self.fail_next = 0
        self.lock = threading.Lock()

    def arm(self, n):
        with self.lock:
            self.fail_next = n

    def __call__(self):
        from sqlalchemy.exc import OperationalError
        session = self.sf()
        original = session.commit

        def commit():
            with self.lock:
                fail = self.fail_next > 0
                if fail:
                    self.fail_next -= 1
            if fail:
                session.rollback()
                raise OperationalError("COMMIT", {}, Exception("database is locked"))
            original()

        session.commit = commit
        return session


def test_error_write_is_retried_once_when_final_writes_fail(sf, monkeypatch):
    import app.fit.queue as queue_mod
    monkeypatch.setattr(queue_mod, "ERROR_RETRY_SECONDS", 0.05)
    (pid,) = add_postings(sf, 1)
    flaky = FlakyCommits(sf)
    fake = FakeEval(on_call=lambda _p: flaky.arm(2))  # the done write and the error write fail
    q = FitQueue(flaky, evaluate=fake)
    try:
        q.enqueue([pid], lang="en", kind="single")
        assert q.wait_idle(TIMEOUT)
    finally:
        q.shutdown()
    row = fit_row(sf, pid)
    assert row.status == FitStatus.error and row.error == "llm_unavailable"


class ScriptedEval(FakeEval):
    """Outcome per call index: an exception to raise, or None for success."""

    def __init__(self, outcomes):
        super().__init__()
        self.outcomes = list(outcomes)

    def __call__(self, session_factory, posting_id, lang):
        with self.lock:
            index = len(self.calls)
        self.error = self.outcomes[index] if index < len(self.outcomes) else None
        return super().__call__(session_factory, posting_id, lang)


def timeout_error():
    return UpstreamError("llm_timeout", "timeout")


@pytest.mark.parametrize("kind", ["bulk", "auto"])
def test_circuit_breaker_after_three_failures(sf, make_queue, kind):
    ids = add_postings(sf, 6)
    set_setting(sf, "fit_concurrency", 1)
    fake = ScriptedEval([timeout_error()] * 6)
    q = make_queue(fake)
    assert q.enqueue(ids, lang="en", kind=kind) == 6
    assert q.wait_idle(TIMEOUT)
    assert len(fake.calls) == 3  # the rest end without calling the LLM
    for pid in ids:
        row = fit_row(sf, pid)
        assert row.status == FitStatus.error and row.error == "llm_timeout"


def test_circuit_breaker_success_resets_streak(sf, make_queue):
    ids = add_postings(sf, 6)
    set_setting(sf, "fit_concurrency", 1)
    err = timeout_error
    fake = ScriptedEval([err(), err(), None, err(), err(), None])
    q = make_queue(fake)
    q.enqueue(ids, lang="en", kind="bulk")
    assert q.wait_idle(TIMEOUT)
    assert len(fake.calls) == 6


def test_circuit_breaker_ignores_other_errors(sf, make_queue):
    ids = add_postings(sf, 5)
    set_setting(sf, "fit_concurrency", 1)
    fake = ScriptedEval([UpstreamError("llm_invalid_output", "bad")] * 5)
    q = make_queue(fake)
    q.enqueue(ids, lang="en", kind="bulk")
    assert q.wait_idle(TIMEOUT)
    assert len(fake.calls) == 5


def test_circuit_breaker_spares_single_and_later_jobs(sf, make_queue):
    ids = add_postings(sf, 6)
    set_setting(sf, "fit_concurrency", 1)
    fake = ScriptedEval([UpstreamError("llm_unavailable", "down")] * 3 + [UpstreamError("llm_auth_failed", "x")])
    q = make_queue(fake)
    q.enqueue(ids[:3], lang="en", kind="bulk")
    assert q.wait_idle(TIMEOUT)
    assert len(fake.calls) == 3
    q.enqueue([ids[3]], lang="en", kind="single")  # single jobs are never short-circuited
    assert q.wait_idle(TIMEOUT)
    assert len(fake.calls) == 4 and fit_row(sf, ids[3]).error == "llm_auth_failed"
    q.enqueue([ids[4]], lang="en", kind="auto")  # enqueued after the trip: runs normally
    assert q.wait_idle(TIMEOUT)
    assert len(fake.calls) == 5 and fit_row(sf, ids[4]).status == FitStatus.done
    q.discard_all()  # a new epoch works as well
    q.enqueue([ids[5]], lang="en", kind="bulk")
    assert q.wait_idle(TIMEOUT)
    assert len(fake.calls) == 6 and fit_row(sf, ids[5]).status == FitStatus.done


def test_circuit_breaker_trip_only_hits_jobs_queued_before_it(sf, make_queue):
    ids = add_postings(sf, 6)
    set_setting(sf, "fit_concurrency", 1)
    fake = ScriptedEval([timeout_error()] * 3)  # the provider recovers after three timeouts
    q = make_queue(fake)
    assert q.enqueue(ids, lang="en", kind="bulk") == 6
    assert q.wait_idle(TIMEOUT)
    assert len(fake.calls) == 3
    assert all(fit_row(sf, i).error == "llm_timeout" for i in ids)
    assert q.enqueue(ids, lang="en", kind="bulk") == 6  # a later bulk run calls the LLM again
    assert q.wait_idle(TIMEOUT)
    assert len(fake.calls) == 9
    assert all(fit_row(sf, i).status == FitStatus.done for i in ids)


def test_circuit_breaker_ignores_stale_epoch_track(sf, make_queue):
    (pid,) = add_postings(sf, 1)
    set_setting(sf, "fit_concurrency", 1)
    fake = FakeEval(block=True)
    q = make_queue(fake)
    q.discard_all()  # epoch 1
    q.enqueue([pid], lang="en", kind="bulk")  # seq of a job queued before the trip
    assert fake.started.acquire(timeout=TIMEOUT)
    q._track(1, "bulk", "llm_timeout")
    q._track(1, "bulk", "llm_timeout")
    q._track(0, "bulk", None)  # a success from the old epoch must not reset the current streak
    q._track(1, "bulk", "llm_timeout")
    assert q._short_circuit_code(1, 0) == "llm_timeout"
    fake.release.set()
    assert q.wait_idle(TIMEOUT)

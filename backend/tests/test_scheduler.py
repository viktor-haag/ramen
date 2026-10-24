from pathlib import Path

import pytest

from app.db import Base, make_engine, make_session_factory
from app.models import RunTrigger, SearchProfile
from app.runner.scheduler import SchedulerManager


class FakeRunService:
    def __init__(self):
        self.calls = []

    def start_runs(self, profile_ids, trigger):
        self.calls.append((profile_ids, trigger))
        return []


@pytest.fixture
def session_factory(tmp_path: Path):
    engine = make_engine(f"sqlite:///{tmp_path / 'sched.db'}")
    Base.metadata.create_all(engine)
    yield make_session_factory(engine)
    engine.dispose()


def add(session_factory, **kw) -> int:
    with session_factory() as s:
        p = SearchProfile(name="p", plugins=[], **kw)
        s.add(p)
        s.commit()
        return p.id


def test_scheduler_sync(session_factory):
    run_service = FakeRunService()
    mgr = SchedulerManager(run_service, session_factory)  # not started: jobs stay pending
    a = add(session_factory, schedule_hours=6, enabled=True)
    add(session_factory, schedule_hours=None, enabled=True)
    add(session_factory, schedule_hours=12, enabled=False)
    mgr.sync()
    assert mgr.jobs() == {f"profile-{a}": 6}

    with session_factory() as s:
        s.get(SearchProfile, a).schedule_hours = 3
        s.commit()
    mgr.sync()
    assert mgr.jobs() == {f"profile-{a}": 3}

    mgr.sync()  # idempotent
    assert mgr.jobs() == {f"profile-{a}": 3}

    with session_factory() as s:
        s.delete(s.get(SearchProfile, a))
        s.commit()
    mgr.sync()
    assert mgr.jobs() == {}


def test_scheduler_job_triggers_scheduled_run(session_factory):
    run_service = FakeRunService()
    mgr = SchedulerManager(run_service, session_factory)
    a = add(session_factory, schedule_hours=1)
    mgr.sync()
    job = mgr._scheduler.get_jobs()[0]
    assert (job.coalesce, job.max_instances) == (True, 1) and job.misfire_grace_time <= 60
    job.func(*job.args)
    assert run_service.calls == [([a], RunTrigger.schedule)]


def test_scheduler_start_and_shutdown(session_factory):
    mgr = SchedulerManager(FakeRunService(), session_factory)
    a = add(session_factory, schedule_hours=1)
    mgr.start()
    try:
        mgr.sync()
        assert mgr.jobs() == {f"profile-{a}": 1}
        job = mgr._scheduler.get_jobs()[0]
        assert job.next_run_time is not None
    finally:
        mgr.shutdown()
    mgr.shutdown()  # idempotent

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text

import app.models  # noqa: F401  (register all tables)
from app.db import Base, make_engine, make_session_factory
from app.db_migrate import upgrade
from app.main import create_app
from app.models import PluginSetting, Posting, RunStatus, RunTrigger, SearchProfile, SearchRun
from app.plugins.base import SearchProfileDTO
from app.plugins.loader import discover_plugins
from app.plugins.registry import PluginRegistry
from app.runner.pool import RunnerPool
from app.runner.service import RunService

FAKE_PLUGINS = Path(__file__).parent / "fake_plugins"


@pytest.fixture(scope="module")
def registry() -> PluginRegistry:
    return PluginRegistry(discover_plugins([FAKE_PLUGINS]))


@pytest.fixture
def session_factory(tmp_path: Path):
    engine = make_engine(f"sqlite:///{tmp_path / 'runner.db'}")
    Base.metadata.create_all(engine)
    yield make_session_factory(engine)
    engine.dispose()


@pytest.fixture(scope="module")
def pool():
    # shared across tests: worker startup (spawn) dominates the runtime
    p = RunnerPool(2)
    yield p
    p.close()


@pytest.fixture
def service(session_factory, registry, pool):
    svc = RunService(session_factory, registry, pool)
    yield svc
    assert svc.wait_idle(30)  # no callback may outlive the test's engine


def add_profile(session_factory, plugins: list[str], **kw) -> int:
    with session_factory() as s:
        p = SearchProfile(name="p", keywords=["py"], plugins=plugins, **kw)
        s.add(p)
        s.commit()
        return p.id


def runs(session_factory) -> dict[str, SearchRun]:
    with session_factory() as s:
        return {r.plugin: r for r in s.scalars(select(SearchRun))}


def test_successful_run_ingests(service, session_factory):
    pid = add_profile(session_factory, ["good"])
    ids = service.start_runs([pid], RunTrigger.manual)
    assert len(ids) == 1
    assert service.wait_idle(30)
    run = runs(session_factory)["good"]
    assert run.status == RunStatus.ok
    assert (run.new_count, run.total_count, run.invalid_count) == (4, 4, 0)
    assert run.trigger == RunTrigger.manual
    assert run.finished_at is not None and run.error is None
    with session_factory() as s:
        assert s.scalar(select(func.count()).select_from(Posting)) == 4
        assert {p.title for p in s.scalars(select(Posting))} == {"py job 1", "py job 2", "py job 3", "shared job"}


def test_timeout_marks_run(service, session_factory):
    pid = add_profile(session_factory, ["hang"])
    service.start_runs([pid], RunTrigger.manual)
    assert service.wait_idle(30)
    run = runs(session_factory)["hang"]
    assert run.status == RunStatus.timeout
    assert run.error == '"py": Timed out after 1 s'
    assert run.finished_at is not None


def test_timeout_overridden_by_plugin_setting(service, session_factory):
    with session_factory() as s:
        s.add(PluginSetting(plugin="hang", enabled=True, settings={"timeout_seconds": 2}))
        s.commit()
    pid = add_profile(session_factory, ["hang"])
    service.start_runs([pid], RunTrigger.manual)
    assert service.wait_idle(30)
    assert runs(session_factory)["hang"].error == '"py": Timed out after 2 s'


def test_crash_marks_error(service, session_factory):
    pid = add_profile(session_factory, ["crash"])
    service.start_runs([pid], RunTrigger.manual)
    assert service.wait_idle(30)
    run = runs(session_factory)["crash"]
    assert run.status == RunStatus.error
    assert "crashed" in run.error
    assert "exit code 1" in run.error
    assert run.finished_at is not None


def test_garbage_counts_invalid(service, session_factory):
    pid = add_profile(session_factory, ["garbage"])
    service.start_runs([pid], RunTrigger.schedule)
    assert service.wait_idle(30)
    run = runs(session_factory)["garbage"]
    assert run.status == RunStatus.ok
    assert run.new_count == 2
    assert run.invalid_count == 1


def test_failure_does_not_affect_other_runs(service, session_factory):
    pid = add_profile(session_factory, ["good", "crash"])
    assert len(service.start_runs([pid], RunTrigger.manual)) == 2
    assert service.wait_idle(30)
    by_plugin = runs(session_factory)
    assert by_plugin["good"].status == RunStatus.ok
    assert by_plugin["good"].new_count == 4
    assert by_plugin["crash"].status == RunStatus.error


def test_failure_while_recording_marks_error(service, session_factory, monkeypatch, caplog):
    def boom(*args, **kwargs):
        raise RuntimeError("ingest exploded")

    monkeypatch.setattr("app.runner.service.ingest", boom)
    pid = add_profile(session_factory, ["good"])
    service.start_runs([pid], RunTrigger.manual)
    assert service.wait_idle(30)
    run = runs(session_factory)["good"]
    assert run.status == RunStatus.error
    assert run.error == "RuntimeError: ingest exploded"
    assert run.finished_at is not None
    assert "Recording outcome of search run" in caplog.text
    monkeypatch.undo()
    assert len(service.start_runs([pid], RunTrigger.manual)) == 1
    assert service.wait_idle(30)


def test_vanished_run_row_is_ignored(service, session_factory):
    from concurrent.futures import Future

    done: Future = Future()
    done.set_result([])
    service._finish(9999, [("py", done)], 1)  # must not raise
    assert runs(session_factory) == {}


def test_running_pair_not_started_twice(service, session_factory):
    pid = add_profile(session_factory, ["hang"])
    first = service.start_runs([pid], RunTrigger.manual)
    second = service.start_runs([pid], RunTrigger.manual)
    assert len(first) == 1
    assert second == []


def test_disabled_plugin_skipped(service, session_factory):
    with session_factory() as s:
        s.add(PluginSetting(plugin="good", enabled=False, settings={}))
        s.commit()
    pid = add_profile(session_factory, ["good"])
    assert service.start_runs([pid], RunTrigger.manual) == []
    assert runs(session_factory) == {}


def test_effective_plugins(service, session_factory):
    all_pid = add_profile(session_factory, [])
    with session_factory() as s:
        names = {i.name for i in service.effective_plugins(s, s.get(SearchProfile, all_pid))}
    # empty list = all usable SEARCH plugins; broken (error) is excluded
    assert names == {"good", "hang", "crash", "garbage", "httperror"}


def test_none_starts_all_enabled_profiles(service, session_factory):
    on = add_profile(session_factory, ["good"])
    add_profile(session_factory, ["good"], enabled=False)
    ids = service.start_runs(None, RunTrigger.schedule)
    assert len(ids) == 1
    assert service.wait_idle(30)
    with session_factory() as s:
        assert [r.profile_id for r in s.scalars(select(SearchRun))] == [on]


def test_recover_stale_runs(service, session_factory):
    pid = add_profile(session_factory, ["good"])
    with session_factory() as s:
        s.add(SearchRun(profile_id=pid, plugin="good", trigger=RunTrigger.manual, status=RunStatus.running))
        s.commit()
    assert service.start_runs([pid], RunTrigger.manual) == []  # pair still marked running
    with session_factory() as s:
        assert service.recover_stale_runs(s) == 1
        s.commit()
    run = runs(session_factory)["good"]
    assert run.status == RunStatus.error
    assert run.error == "Aborted by restart"
    assert run.finished_at is not None
    assert len(service.start_runs([pid], RunTrigger.manual)) == 1
    assert service.wait_idle(30)


def test_lifespan_recovers_and_exposes_service(settings):
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    upgrade(settings.db_url)
    app_ = create_app(settings)
    with app_.state.session_factory() as s:
        s.add(SearchRun(plugin="good", trigger=RunTrigger.manual, status=RunStatus.running))
        s.commit()
    with TestClient(app_):
        assert isinstance(app_.state.run_service, RunService)
        with app_.state.session_factory() as s:
            run = s.scalars(select(SearchRun)).one()
            assert run.status == RunStatus.error
            assert run.error == "Aborted by restart"


def test_engine_sets_busy_timeout(session_factory):
    with session_factory() as s:
        assert s.execute(text("PRAGMA busy_timeout")).scalar() == 10000


def test_run_calls_hook_with_new_ids_only(session_factory, registry, pool):
    calls: list[list[int]] = []
    service = RunService(session_factory, registry, pool, on_new_postings=calls.append)
    pid = add_profile(session_factory, ["good"])
    service.start_runs([pid], RunTrigger.manual)
    assert service.wait_idle(30)
    with session_factory() as s:
        first_ids = set(s.scalars(select(Posting.id)))
        profile = s.get(SearchProfile, pid)
        profile.keywords = ["py", "extra"]
        s.commit()
    assert len(calls) == 1 and set(calls[0]) == first_ids and len(first_ids) == 4
    service.start_runs([pid], RunTrigger.manual)
    assert service.wait_idle(30)
    with session_factory() as s:
        extra = set(s.scalars(select(Posting.id).where(Posting.external_id.like("extra-%"))))
    assert len(calls) == 2 and set(calls[1]) == extra and len(extra) == 3  # "shared-1" and "py-*" are not new


def test_hook_failure_does_not_fail_run(session_factory, registry, pool, caplog):
    def boom(ids):
        raise RuntimeError("hook exploded")

    service = RunService(session_factory, registry, pool, on_new_postings=boom)
    pid = add_profile(session_factory, ["good"])
    service.start_runs([pid], RunTrigger.manual)
    assert service.wait_idle(30)
    run = runs(session_factory)["good"]
    assert run.status == RunStatus.ok and run.error is None and run.new_count == 4
    assert "on_new_postings hook failed" in caplog.text


def test_hook_runs_outside_db_lock(session_factory, registry, pool):
    held: list[bool] = []
    service = RunService(session_factory, registry, pool, on_new_postings=lambda ids: held.append(service.db_lock.locked()))
    pid = add_profile(session_factory, ["good"])
    service.start_runs([pid], RunTrigger.manual)
    assert service.wait_idle(30)
    assert held == [False]


def test_http_error_from_plugin_is_reported_readably(service, session_factory, caplog):
    # httpx.HTTPStatusError does not unpickle; it used to surface as "BrokenProcessPool: Unpicklable object"
    pid = add_profile(session_factory, ["httperror"])
    service.start_runs([pid], RunTrigger.manual)
    assert service.wait_idle(30)
    run = runs(session_factory)["httperror"]
    assert run.status == RunStatus.error
    assert run.error == '"py": HTTP 429 Too Many Requests (api.example.test)'
    assert "httperror" in caplog.text and "HTTPStatusError" in caplog.text  # full traceback in the log


def test_pool_recovers_after_it_stopped(registry):
    p = RunnerPool(1)
    try:
        p._pool.stop()
        p._pool.join()
        future = p.submit(registry.get("good"), SearchProfileDTO(keywords="py"), {}, 30)
        assert len(future.result(timeout=60)) == 4
    finally:
        p.close()


class ScriptedSpacer:
    def __init__(self, delays: list[float]):
        self.delays = list(delays)
        self.calls: list[tuple[str, tuple[float, float]]] = []

    def delay(self, key: str, gap: tuple[float, float]) -> float:
        self.calls.append((key, gap))
        return self.delays.pop(0)


def test_keyword_starts_are_spaced_per_source(session_factory, registry, pool):
    spacer = ScriptedSpacer([0.0, 1.5])
    svc = RunService(session_factory, registry, pool, spacer=spacer)
    with session_factory() as s:
        p = SearchProfile(name="p", keywords=["py", "go"], plugins=["good"])
        s.add(p)
        s.commit()
        pid = p.id
    started = time.monotonic()
    svc.start_runs([pid], RunTrigger.manual)
    assert svc.wait_idle(30)
    assert time.monotonic() - started >= 1.5
    assert spacer.calls == [("good", (0.0, 0.0)), ("good", (0.0, 0.0))]  # gap from the plugin class
    assert runs(session_factory)["good"].status == RunStatus.ok


def test_close_cancels_delayed_starts(session_factory, registry, pool):
    svc = RunService(session_factory, registry, pool, spacer=ScriptedSpacer([0.0, 300.0]))
    with session_factory() as s:
        p = SearchProfile(name="p", keywords=["py", "go"], plugins=["good"])
        s.add(p)
        s.commit()
        pid = p.id
    svc.start_runs([pid], RunTrigger.manual)
    svc.close()
    assert svc.wait_idle(30)
    run = runs(session_factory)["good"]
    assert run.status == RunStatus.error
    assert run.error == '"go": Run cancelled'

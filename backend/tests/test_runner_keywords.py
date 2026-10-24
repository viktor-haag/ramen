from concurrent.futures import Future, TimeoutError
from pathlib import Path

import pytest
from sqlalchemy import select

import app.models  # noqa: F401  (register all tables)
from app.db import Base, make_engine, make_session_factory
from app.models import Posting, RunStatus, RunTrigger, SearchProfile, SearchRun
from app.plugins.loader import discover_plugins
from app.plugins.registry import PluginRegistry
from app.runner.pool import RunnerPool, execute_search
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
    p = RunnerPool(2)
    yield p
    p.close()


class StubPool:
    """Synchronous stand-in for RunnerPool: per-keyword outcome chosen by the test."""

    def __init__(self, failures: dict[str, BaseException] | None = None, hang: bool = False):
        self.failures = failures or {}
        self.hang = hang
        self.calls: list[str] = []
        self.open: list[Future] = []

    def submit(self, info, profile, settings, timeout) -> Future:
        self.calls.append(profile.keywords)
        future: Future = Future()
        if self.hang:
            self.open.append(future)
        elif profile.keywords in self.failures:
            future.set_exception(self.failures[profile.keywords])
        else:
            future.set_result(execute_search(info.module_path, info.class_name, profile.model_dump(), settings))
        return future

    def release(self) -> None:
        for future in self.open:
            future.set_result([])


def make_service(session_factory, registry, pool):
    return RunService(session_factory, registry, pool)


def add_profile(session_factory, keywords: list[str], plugins: list[str]) -> int:
    with session_factory() as s:
        p = SearchProfile(name="p", keywords=keywords, plugins=plugins)
        s.add(p)
        s.commit()
        return p.id


def all_runs(session_factory) -> list[SearchRun]:
    with session_factory() as s:
        return list(s.scalars(select(SearchRun)))


def external_ids(session_factory) -> set[str]:
    with session_factory() as s:
        return set(s.scalars(select(Posting.external_id)))


def test_two_keywords_one_run(session_factory, registry, pool):
    service = make_service(session_factory, registry, pool)
    pid = add_profile(session_factory, ["a", "b"], ["good"])
    ids = service.start_runs([pid], RunTrigger.manual)
    assert len(ids) == 1
    assert service.wait_idle(30)
    [run] = all_runs(session_factory)
    assert run.id == ids[0]
    assert run.status == RunStatus.ok and run.error is None
    assert (run.new_count, run.total_count, run.invalid_count) == (7, 7, 0)
    assert run.finished_at is not None
    assert external_ids(session_factory) == {"a-1", "a-2", "a-3", "b-1", "b-2", "b-3", "shared-1"}


def test_one_keyword_fails(session_factory, registry):
    stub = StubPool(failures={"b": RuntimeError("boom")})
    service = make_service(session_factory, registry, stub)
    pid = add_profile(session_factory, ["a", "b"], ["good"])
    assert len(service.start_runs([pid], RunTrigger.manual)) == 1
    assert service.wait_idle(5)
    assert stub.calls == ["a", "b"]
    [run] = all_runs(session_factory)
    assert run.status == RunStatus.error
    assert run.error == '"b": RuntimeError: boom'
    assert run.new_count == 4 and run.total_count == 4
    assert run.finished_at is not None
    assert external_ids(session_factory) == {"a-1", "a-2", "a-3", "shared-1"}


def test_keyword_timeout_status(session_factory, registry):
    stub = StubPool(failures={"b": TimeoutError()})
    service = make_service(session_factory, registry, stub)
    pid = add_profile(session_factory, ["a", "b"], ["good"])
    service.start_runs([pid], RunTrigger.manual)
    assert service.wait_idle(5)
    [run] = all_runs(session_factory)
    assert run.status == RunStatus.timeout
    assert run.error.startswith('"b": Timed out after')


def test_first_failure_in_keyword_order_decides_status(session_factory, registry):
    stub = StubPool(failures={"a": RuntimeError("boom"), "c": TimeoutError()})
    service = make_service(session_factory, registry, stub)
    pid = add_profile(session_factory, ["a", "b", "c"], ["good"])
    service.start_runs([pid], RunTrigger.manual)
    assert service.wait_idle(5)
    [run] = all_runs(session_factory)
    assert run.status == RunStatus.error
    assert run.error == '"a": RuntimeError: boom; "c": Timed out after 120 s'
    assert external_ids(session_factory) == {"b-1", "b-2", "b-3", "shared-1"}


def test_submit_exception_counts_as_failed_keyword(session_factory, registry):
    class Exploding(StubPool):
        def submit(self, info, profile, settings, timeout):
            if profile.keywords == "a":
                self.calls.append("a")
                raise RuntimeError("pool closed")
            return super().submit(info, profile, settings, timeout)

    stub = Exploding()
    service = make_service(session_factory, registry, stub)
    pid = add_profile(session_factory, ["a", "b"], ["good"])
    service.start_runs([pid], RunTrigger.manual)
    assert service.wait_idle(5)
    [run] = all_runs(session_factory)
    assert run.status == RunStatus.error
    assert run.error == '"a": RuntimeError: pool closed'
    assert external_ids(session_factory) == {"b-1", "b-2", "b-3", "shared-1"}


def test_profile_without_keywords(session_factory, registry):
    stub = StubPool()
    service = make_service(session_factory, registry, stub)
    pid = add_profile(session_factory, [], ["good"])
    ids = service.start_runs([pid], RunTrigger.manual)
    assert len(ids) == 1
    assert service.wait_idle(5)
    assert stub.calls == []
    [run] = all_runs(session_factory)
    assert run.status == RunStatus.error
    assert run.error == "no keywords"
    assert run.finished_at is not None


def test_running_pair_guard_still_holds(session_factory, registry):
    stub = StubPool(hang=True)
    service = make_service(session_factory, registry, stub)
    pid = add_profile(session_factory, ["a", "b"], ["good"])
    first = service.start_runs([pid], RunTrigger.manual)
    second = service.start_runs([pid], RunTrigger.manual)
    assert len(first) == 1
    assert second == []
    assert stub.calls == ["a", "b"]
    assert not service.wait_idle(0.2)  # run stays pending until the last keyword completes
    stub.open[0].set_result([])
    assert not service.wait_idle(0.2)
    assert all_runs(session_factory)[0].status == RunStatus.running
    stub.open[1].set_result([])
    assert service.wait_idle(5)
    assert all_runs(session_factory)[0].status == RunStatus.ok


def test_all_keywords_failed(session_factory, registry):
    stub = StubPool(failures={"a": TimeoutError(), "b": RuntimeError("boom")})
    service = make_service(session_factory, registry, stub)
    pid = add_profile(session_factory, ["a", "b"], ["good"])
    service.start_runs([pid], RunTrigger.manual)
    assert service.wait_idle(5)
    [run] = all_runs(session_factory)
    assert run.status == RunStatus.timeout  # status of the first failure
    assert run.error == '"a": Timed out after 120 s; "b": RuntimeError: boom'
    assert not run.new_count and not run.total_count
    assert external_ids(session_factory) == set()


def test_deleted_profile_and_failed_keyword_keep_both_messages(session_factory, registry):
    stub = StubPool(failures={"b": RuntimeError("boom")}, hang=True)
    service = make_service(session_factory, registry, stub)
    pid = add_profile(session_factory, ["a", "b"], ["good"])
    service.start_runs([pid], RunTrigger.manual)
    with session_factory() as s:
        s.delete(s.get(SearchProfile, pid))
        s.commit()
    stub.open[0].set_result([])
    stub.open[1].set_exception(RuntimeError("boom"))
    assert service.wait_idle(5)
    [run] = all_runs(session_factory)
    assert run.status == RunStatus.error
    assert run.error == 'Search profile no longer exists; "b": RuntimeError: boom'

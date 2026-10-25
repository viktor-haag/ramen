"""Version API, update_check setting, scheduled check and health (never the real GitHub)."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.db import Base, make_engine, make_session_factory
from app.main import create_app
from app.runner.scheduler import SchedulerManager
from app.services.updates import UpdateChecker
from app.version import __version__

FAKE_PLUGINS = Path(__file__).parent / "fake_plugins"
REPO = "viktor-haag/ramen"


class Recorder:
    def __init__(self, handler=None):
        self.requests: list[httpx.Request] = []
        self._handler = handler or self._ok

    @staticmethod
    def _ok(request):
        return httpx.Response(
            200,
            json={
                "tag_name": "v0.2.0",
                "html_url": f"https://github.com/{REPO}/releases/tag/v0.2.0",
                "published_at": "2026-10-24T08:30:00Z",
            },
        )

    def __call__(self, request):
        self.requests.append(request)
        return self._handler(request)


def checker_for(recorder: Recorder) -> UpdateChecker:
    return UpdateChecker(
        REPO, __version__, client_factory=lambda: httpx.Client(transport=httpx.MockTransport(recorder))
    )


def make_app(tmp_path, recorder: Recorder, *, update_check: bool = True):
    app = create_app(Settings(data_dir=tmp_path, plugin_dirs=[FAKE_PLUGINS], update_check=update_check))
    app.state.update_checker = checker_for(recorder)
    return app


SETTINGS_BODY = {"fit_auto": False, "fit_concurrency": 2, "daily_limit_kind": "none", "daily_limit_value": None}


def test_version_get_before_check(tmp_path):
    rec = Recorder()
    with TestClient(make_app(tmp_path, rec)) as c:
        body = c.get("/api/version").json()
    assert body == {
        "current": "0.1.0", "latest": None, "update_available": False, "release_url": None,
        "published_at": None, "checked_at": None, "error": None, "enabled": True, "disabled_by_env": False,
    }
    assert rec.requests == []


def test_check_now_reports_update(tmp_path):
    with TestClient(make_app(tmp_path, Recorder())) as c:
        r = c.post("/api/version/check")
        assert r.status_code == 200
        body = r.json()
        assert body["update_available"] is True and body["latest"] == "0.2.0"
        assert body["release_url"].endswith("/v0.2.0") and body["checked_at"] and body["error"] is None
        assert c.get("/api/version").json() == body


def test_disabled_by_env(tmp_path):
    rec = Recorder()
    app = make_app(tmp_path, rec, update_check=False)
    with TestClient(app) as c:
        body = c.get("/api/version").json()
        assert body["enabled"] is False and body["disabled_by_env"] is True
        r = c.post("/api/version/check")
        assert r.status_code == 409 and r.json()["code"] == "update_check_disabled"
        assert "update-check" not in app.state.scheduler.jobs()
    assert rec.requests == []


def test_scheduled_job_registered_when_enabled(tmp_path):
    app = make_app(tmp_path, Recorder())
    with TestClient(app):
        assert app.state.scheduler.jobs()["update-check"] == 12


def test_setting_off_makes_enabled_false(tmp_path):
    with TestClient(make_app(tmp_path, Recorder())) as c:
        assert c.put("/api/settings", json={**SETTINGS_BODY, "update_check": False}).status_code == 200
        body = c.get("/api/version").json()
        assert body["enabled"] is False and body["disabled_by_env"] is False


def test_setting_off_skips_scheduled_check(tmp_path):
    rec = Recorder()
    app = make_app(tmp_path, rec)
    with TestClient(app) as c:
        c.put("/api/settings", json={**SETTINGS_BODY, "update_check": False})
        app.state.run_update_check()
        assert rec.requests == []
        c.put("/api/settings", json={**SETTINGS_BODY, "update_check": True})
        app.state.run_update_check()
        assert len(rec.requests) == 1
        assert c.get("/api/version").json()["latest"] == "0.2.0"


def test_scheduled_job_never_raises(tmp_path):
    app = make_app(tmp_path, Recorder())

    class Boom:
        def check(self):
            raise RuntimeError("boom")

    with TestClient(app):
        app.state.update_checker = Boom()  # resolved at call time
        app.state.run_update_check()  # must not raise


def test_scheduled_job_swallows_network_error(tmp_path):
    def fail(request):
        raise httpx.ConnectError("unreachable")

    with TestClient(make_app(tmp_path, Recorder(fail))) as c:
        c.app.state.run_update_check()
        body = c.get("/api/version").json()
    assert body["error"] == "network" and body["update_available"] is False


def test_manual_check_works_with_setting_off(tmp_path):
    rec = Recorder()
    with TestClient(make_app(tmp_path, rec)) as c:
        c.put("/api/settings", json={**SETTINGS_BODY, "update_check": False})
        r = c.post("/api/version/check")
        assert r.status_code == 200 and r.json()["latest"] == "0.2.0"
        assert r.json()["enabled"] is False
    assert len(rec.requests) == 1


def test_health_has_version(client):
    assert client.get("/api/health").json() == {"status": "ok", "version": __version__}


def test_openapi_title_and_version(app):
    assert app.title == "RAMEN" and app.version == __version__


def test_settings_default_update_check_and_put_without_field(client):
    assert client.get("/api/settings").json()["update_check"] is True
    r = client.put("/api/settings", json={**SETTINGS_BODY, "update_check": False})
    assert r.json()["update_check"] is False
    r = client.put("/api/settings", json=SETTINGS_BODY)  # field omitted -> default True
    assert r.status_code == 200 and r.json()["update_check"] is True


@pytest.fixture
def sched(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 's.db'}")
    Base.metadata.create_all(engine)
    mgr = SchedulerManager(object(), make_session_factory(engine))
    yield mgr
    mgr.shutdown()
    engine.dispose()


def test_scheduler_add_update_check(sched):
    sched.start()
    sched.add_update_check(lambda: None)
    job = sched._scheduler.get_job("update-check")
    assert sched.jobs()["update-check"] == 12
    delta = job.next_run_time - datetime.now(UTC)
    assert timedelta(seconds=20) < delta <= timedelta(seconds=31)
    sched.sync()  # leaves it alone
    assert sched._scheduler.get_job("update-check") is job
    assert "update-check" in sched.jobs()

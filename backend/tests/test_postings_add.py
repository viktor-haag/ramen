from concurrent.futures import Future
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.models import Application, AppStatus, PluginSetting, Posting, StatusChange, TriageStatus

NOW = datetime(2026, 10, 22, 8, 0, tzinfo=UTC)


@pytest.fixture
def db(app):
    with app.state.session_factory() as s:
        yield s


class StubPool:
    def __init__(self, exc: BaseException):
        self.exc = exc
        self.timeouts: list[int] = []

    def submit_fetch(self, info, url, settings, timeout):
        self.timeouts.append(timeout)
        f: Future = Future()
        f.set_exception(self.exc)
        return f


def test_manual_creates_saved_application(client, db):
    r = client.post(
        "/api/postings",
        json={"title": "  Bauleiter ", "company": "ACME", "published_at": "2026-10-01T10:00:00", "remote": True},
    )
    assert r.status_code == 200
    app_id = r.json()["application_id"]
    application = db.get(Application, app_id)
    assert application.status == AppStatus.saved
    posting = db.get(Posting, application.posting_id)
    assert posting.source == "manual" and len(posting.external_id) == 32
    assert posting.title == "Bauleiter" and posting.company == "ACME" and posting.remote is True
    assert posting.triage_status == TriageStatus.saved
    assert posting.published_at == datetime(2026, 10, 1, 10, 0, tzinfo=UTC)
    changes = db.scalars(select(StatusChange).where(StatusChange.application_id == app_id)).all()
    assert [(c.from_status, c.to_status) for c in changes] == [(None, AppStatus.saved)]


@pytest.mark.parametrize("body", [{}, {"title": ""}, {"title": "   "}, {"company": "x"}])
def test_manual_requires_title(client, db, body):
    assert client.post("/api/postings", json=body).status_code == 422
    assert db.scalars(select(Posting)).all() == []


def test_two_manual_postings_are_distinct(client, db):
    for _ in range(2):
        assert client.post("/api/postings", json={"title": "Same"}).status_code == 200
    assert len(db.scalars(select(Posting)).all()) == 2


def test_from_url_uses_matching_plugin(client, db):
    r = client.post("/api/postings/from-url", json={"url": "https://good.test/job/1"})
    assert r.status_code == 200
    body = r.json()
    assert body["external_id"] == "g-url" and body["source"] == "good"
    assert body["title"] == "Fetched job"
    assert body["triage_status"] == "new" and body["application_id"] is None
    assert db.scalars(select(Posting).where(Posting.external_id == "g-url")).one().source == "good"


def test_from_url_no_plugin_404(client):
    r = client.post("/api/postings/from-url", json={"url": "https://nowhere.test/x"})
    assert r.status_code == 404
    assert r.json()["code"] == "no_plugin_for_url"


def test_from_url_disabled_plugin_404(client, db):
    db.add(PluginSetting(plugin="good", enabled=False, settings={}))
    db.commit()
    r = client.post("/api/postings/from-url", json={"url": "https://good.test/job/1"})
    assert r.status_code == 404
    assert r.json()["code"] == "no_plugin_for_url"


def test_from_url_existing_keeps_triage(client, db):
    existing = Posting(
        source="good", external_id="g-url", title="Old", first_seen_at=NOW, last_seen_at=NOW,
        triage_status=TriageStatus.dismissed, triaged_at=NOW,
    )
    db.add(existing)
    db.commit()
    r = client.post("/api/postings/from-url", json={"url": "https://good.test/job/1"})
    assert r.status_code == 200
    assert r.json()["id"] == existing.id
    assert r.json()["title"] == "Fetched job"
    assert r.json()["triage_status"] == "dismissed"
    db.expire_all()
    assert db.get(Posting, existing.id).triage_status == TriageStatus.dismissed
    assert len(db.scalars(select(Posting)).all()) == 1


def test_from_url_plugin_error_is_502(client, app):
    app.state.runner_pool = StubPool(RuntimeError("boom"))
    r = client.post("/api/postings/from-url", json={"url": "https://good.test/job/1"})
    assert r.status_code == 502
    assert r.json()["code"] == "fetch_failed"
    assert r.json()["params"] == {"reason": "RuntimeError: boom"}


def test_from_url_timeout_uses_plugin_setting(client, app, db):
    db.add(PluginSetting(plugin="good", enabled=True, settings={"timeout_seconds": 7}))
    db.commit()
    pool = app.state.runner_pool = StubPool(TimeoutError())
    r = client.post("/api/postings/from-url", json={"url": "https://good.test/job/1"})
    assert r.status_code == 502
    assert r.json()["params"] == {"reason": "Timed out after 7 s"}
    assert pool.timeouts == [7]

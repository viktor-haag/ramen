from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.models import AppStatus, Posting, StatusChange
from app.services import applications as svc
from app.services import triage

NOW = datetime(2026, 10, 22, 8, 0, tzinfo=UTC)
LATER = NOW + timedelta(days=1)


@pytest.fixture
def db(app, client):  # client runs the lifespan (migrations)
    with app.state.session_factory() as s:
        yield s


def make_app(db, ext="1", status=AppStatus.saved, **kw):
    p = Posting(source="src", external_id=ext, first_seen_at=NOW, last_seen_at=NOW,
                title=kw.pop("title", f"Title {ext}"), company=kw.pop("company", f"Co {ext}"))
    db.add(p)
    db.commit()
    a = triage.save_posting(db, p.id, NOW)
    if status != AppStatus.saved:
        a.status = status
        db.add(StatusChange(application_id=a.id, from_status=AppStatus.saved, to_status=status, changed_at=NOW))
    db.commit()
    return a


@pytest.mark.parametrize(
    "frm,to,ok",
    [
        (AppStatus.saved, AppStatus.applied, True),
        (AppStatus.applied, AppStatus.saved, True),
        (AppStatus.applied, AppStatus.rejected, True),
        (AppStatus.applied, AppStatus.accepted, False),
        (AppStatus.offer, AppStatus.accepted, True),
        (AppStatus.rejected, AppStatus.applied, False),
        (AppStatus.saved, AppStatus.saved, False),
    ],
)
def test_transition_table(frm, to, ok):
    assert svc.can_transition(frm, to) is ok


def test_change_status_writes_history(client, db):
    a = make_app(db)
    r = client.post(f"/api/applications/{a.id}/status", json={"to": "applied", "comment": "sent"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "applied"
    assert [c["to_status"] for c in body["status_changes"]] == ["saved", "applied"]
    last = body["status_changes"][-1]
    assert last["from_status"] == "saved" and last["comment"] == "sent"
    assert body["last_status_change_at"] == last["changed_at"]
    assert body["posting"]["id"] == a.posting_id


def test_change_status_updates_updated_at(db):
    a = make_app(db)
    svc.change_status(db, a.id, AppStatus.applied, None, LATER)
    assert a.updated_at == LATER


def test_invalid_transition_returns_409(client, db):
    a = make_app(db, status=AppStatus.applied)
    r = client.post(f"/api/applications/{a.id}/status", json={"to": "accepted"})
    assert r.status_code == 409
    assert r.json()["code"] == "invalid_transition"
    assert r.json()["params"] == {"from": "applied", "to": "accepted"}


def test_unknown_application_404(client):
    assert client.get("/api/applications/999").json()["code"] == "application_not_found"
    assert client.post("/api/applications/999/status", json={"to": "applied"}).status_code == 404
    assert client.patch("/api/applications/999", json={}).status_code == 404


def test_reopen_from_terminal(client, db):
    a = make_app(db, status=AppStatus.rejected)
    r = client.post(f"/api/applications/{a.id}/reopen", json={"to": "interviewing", "comment": "they called"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "interviewing"
    last = body["status_changes"][-1]
    assert last["from_status"] == "rejected" and last["to_status"] == "interviewing"
    assert last["comment"] == "Reopened: they called"


def test_reopen_without_comment(db):
    a = make_app(db, status=AppStatus.withdrawn)
    svc.reopen(db, a.id, AppStatus.saved, None, LATER)
    assert a.status_changes[-1].comment == "Reopened"


def test_reopen_from_active_conflict(client, db):
    a = make_app(db)
    r = client.post(f"/api/applications/{a.id}/reopen", json={"to": "applied"})
    assert r.status_code == 409
    assert r.json()["code"] == "not_terminal"


def test_reopen_to_terminal_conflict(client, db):
    a = make_app(db, status=AppStatus.rejected)
    r = client.post(f"/api/applications/{a.id}/reopen", json={"to": "withdrawn"})
    assert r.status_code == 409
    assert r.json()["code"] == "invalid_transition"
    assert r.json()["params"] == {"from": "rejected", "to": "withdrawn"}


def test_list_default_excludes_terminal(client, db):
    a = make_app(db, "1")
    make_app(db, "2", status=AppStatus.rejected)
    r = client.get("/api/applications")
    assert r.status_code == 200
    assert [i["id"] for i in r.json()] == [a.id]
    assert r.json()[0]["posting"]["application_id"] == a.id


def test_list_with_terminal_filter(client, db):
    make_app(db, "1")
    b = make_app(db, "2", status=AppStatus.rejected)
    c = make_app(db, "3", status=AppStatus.accepted)
    r = client.get("/api/applications", params=[("status", "rejected"), ("status", "accepted")])
    assert sorted(i["id"] for i in r.json()) == sorted([b.id, c.id])
    assert client.get("/api/applications", params={"status": "bogus"}).status_code == 422


def test_list_q_and_order(client, db):
    a = make_app(db, "1", title="Python Developer", company="Acme")
    b = make_app(db, "2", title="Gärtner", company="ÄRGER GmbH")
    svc.change_status(db, a.id, AppStatus.applied, None, LATER)
    db.commit()
    assert [i["id"] for i in client.get("/api/applications").json()] == [a.id, b.id]
    assert [i["id"] for i in client.get("/api/applications", params={"q": "PYTHON"}).json()] == [a.id]
    assert [i["id"] for i in client.get("/api/applications", params={"q": "ärger"}).json()] == [b.id]
    first = client.get("/api/applications").json()[0]
    assert first["last_status_change_at"].startswith("2026-10-23")


def test_get_detail_has_children_lists(client, db):
    a = make_app(db)
    body = client.get(f"/api/applications/{a.id}").json()
    assert body["appointments"] == [] and body["contacts"] == [] and body["attachments"] == []
    assert len(body["status_changes"]) == 1


def test_patch_notes(client, db):
    a = make_app(db)
    r = client.patch(f"/api/applications/{a.id}", json={"notes": "call Mon", "channel": "email"})
    assert r.status_code == 200, r.text
    assert r.json()["notes"] == "call Mon" and r.json()["channel"] == "email"
    r = client.patch(f"/api/applications/{a.id}", json={"notes": None})
    assert r.json()["notes"] is None and r.json()["channel"] == "email"
    db.expire_all()
    assert db.get(type(a), a.id).notes is None
    assert db.scalars(select(StatusChange)).all()  # history untouched by patch


def _count_statements(engine, fn):
    from sqlalchemy import event

    n = []
    def listener(*a, **k):
        n.append(1)
    event.listen(engine, "before_cursor_execute", listener)
    try:
        fn()
    finally:
        event.remove(engine, "before_cursor_execute", listener)
    return len(n)


def test_list_query_count_independent_of_size(app, db):
    engine = app.state.engine

    def run():
        db.expire_all()
        svc.applications_out(db, svc.list_applications(db))

    make_app(db, "a")
    base = _count_statements(engine, run)
    for i in range(5):
        make_app(db, f"b{i}")
    assert _count_statements(engine, run) == base

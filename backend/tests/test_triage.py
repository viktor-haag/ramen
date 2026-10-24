from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.models import Application, AppStatus, Contact, Posting, StatusChange, TriageStatus

NOW = datetime(2026, 10, 22, 8, 0, tzinfo=UTC)


def make_posting(session, ext: str = "1", **kw) -> Posting:
    p = Posting(source="src", external_id=ext, title=f"T{ext}", first_seen_at=NOW, last_seen_at=NOW, **kw)
    session.add(p)
    session.commit()
    return p


@pytest.fixture
def db(app):
    with app.state.session_factory() as s:
        yield s


def test_save_creates_application_and_history(client, db):
    p = make_posting(db)
    r = client.post(f"/api/postings/{p.id}/save")
    assert r.status_code == 200
    app_id = r.json()["application_id"]
    db.expire_all()
    application = db.get(Application, app_id)
    assert application.posting_id == p.id
    assert application.status == AppStatus.saved
    changes = db.scalars(select(StatusChange).where(StatusChange.application_id == app_id)).all()
    assert len(changes) == 1
    assert changes[0].from_status is None and changes[0].to_status == AppStatus.saved
    posting = db.get(Posting, p.id)
    assert posting.triage_status == TriageStatus.saved
    assert posting.triaged_at is not None


def test_save_twice_conflict(client, db):
    p = make_posting(db)
    assert client.post(f"/api/postings/{p.id}/save").status_code == 200
    r = client.post(f"/api/postings/{p.id}/save")
    assert r.status_code == 409
    assert r.json()["code"] == "already_saved"


def test_unknown_posting_404(client):
    for action in ("save", "unsave", "dismiss", "undismiss"):
        r = client.post(f"/api/postings/999/{action}")
        assert r.status_code == 404
        assert r.json()["code"] == "posting_not_found"


def test_unsave_only_without_data(client, db):
    p = make_posting(db)
    app_id = client.post(f"/api/postings/{p.id}/save").json()["application_id"]
    db.add(Contact(application_id=app_id, name="Frau X"))
    db.commit()
    r = client.post(f"/api/postings/{p.id}/unsave")
    assert r.status_code == 409
    assert r.json()["code"] == "application_has_data"
    db.expire_all()
    assert db.get(Application, app_id) is not None
    assert db.get(Posting, p.id).triage_status == TriageStatus.saved


def test_unsave_blocked_when_status_advanced(client, db):
    p = make_posting(db)
    app_id = client.post(f"/api/postings/{p.id}/save").json()["application_id"]
    db.get(Application, app_id).status = AppStatus.applied
    db.commit()
    r = client.post(f"/api/postings/{p.id}/unsave")
    assert r.status_code == 409
    assert r.json()["code"] == "application_has_data"


def test_unsave_resets_to_new(client, db):
    p = make_posting(db)
    app_id = client.post(f"/api/postings/{p.id}/save").json()["application_id"]
    r = client.post(f"/api/postings/{p.id}/unsave")
    assert r.status_code == 204
    db.expire_all()
    assert db.get(Application, app_id) is None
    assert db.scalars(select(StatusChange)).all() == []
    posting = db.get(Posting, p.id)
    assert posting.triage_status == TriageStatus.new
    assert posting.triaged_at is None
    # can be saved again
    assert client.post(f"/api/postings/{p.id}/save").status_code == 200


def test_unsave_without_application_conflict(client, db):
    p = make_posting(db)
    r = client.post(f"/api/postings/{p.id}/unsave")
    assert r.status_code == 409
    assert r.json()["code"] == "not_saved"


def test_dismiss_with_application_conflict(client, db):
    p = make_posting(db)
    client.post(f"/api/postings/{p.id}/save")
    r = client.post(f"/api/postings/{p.id}/dismiss")
    assert r.status_code == 409
    assert r.json()["code"] == "has_application"
    db.expire_all()
    assert db.get(Posting, p.id).triage_status == TriageStatus.saved


def test_dismiss_sets_status(client, db):
    p = make_posting(db)
    r = client.post(f"/api/postings/{p.id}/dismiss")
    assert r.status_code == 204
    db.expire_all()
    posting = db.get(Posting, p.id)
    assert posting.triage_status == TriageStatus.dismissed
    assert posting.triaged_at is not None


def test_undismiss(client, db):
    p = make_posting(db)
    client.post(f"/api/postings/{p.id}/dismiss")
    r = client.post(f"/api/postings/{p.id}/undismiss")
    assert r.status_code == 204
    db.expire_all()
    posting = db.get(Posting, p.id)
    assert posting.triage_status == TriageStatus.new
    assert posting.triaged_at is None
    r = client.post(f"/api/postings/{p.id}/undismiss")
    assert r.status_code == 409
    assert r.json()["code"] == "not_dismissed"


def test_save_from_dismissed(client, db):
    p = make_posting(db)
    client.post(f"/api/postings/{p.id}/dismiss")
    assert client.post(f"/api/postings/{p.id}/save").status_code == 200
    db.expire_all()
    assert db.get(Posting, p.id).triage_status == TriageStatus.saved

from datetime import UTC, datetime, timedelta

import pytest

from app.models import Appointment, AppStatus, Posting, RunStatus, RunTrigger, SearchRun, StatusChange, TriageStatus
from app.services import dashboard as svc
from app.services import triage

NOW = datetime(2026, 10, 22, 8, 0, tzinfo=UTC)


@pytest.fixture
def db(app, client):
    with app.state.session_factory() as s:
        yield s


def make_app(db, ext, status=AppStatus.applied, changed_at=NOW):
    p = Posting(source="src", external_id=ext, first_seen_at=NOW, last_seen_at=NOW,
                title=f"Title {ext}", company=f"Co {ext}", triage_status=TriageStatus.dismissed)
    db.add(p)
    db.commit()
    a = triage.save_posting(db, p.id, NOW)
    a.status = status
    a.status_changes.clear()  # drop the initial 'saved' entry written by save_posting
    db.flush()
    db.add(StatusChange(application_id=a.id, from_status=AppStatus.saved, to_status=status, changed_at=changed_at))
    db.commit()
    return a


def test_dashboard_upcoming_window(db):
    a = make_app(db, "1", AppStatus.interviewing)
    for days in (3, 8, -1):
        db.add(Appointment(application_id=a.id, starts_at=NOW + timedelta(days=days)))
    db.add(Appointment(application_id=a.id, starts_at=NOW + timedelta(days=1)))
    db.commit()
    out = svc.dashboard(db, NOW)
    assert [(u.appointment.starts_at - NOW).days for u in out.upcoming] == [1, 3]
    assert out.upcoming[0].application_id == a.id
    assert (out.upcoming[0].title, out.upcoming[0].company) == ("Title 1", "Co 1")


def test_dashboard_stale_14_days(db):
    old = make_app(db, "old", changed_at=NOW - timedelta(days=15))
    make_app(db, "fresh", changed_at=NOW - timedelta(days=13))
    make_app(db, "talk", AppStatus.interviewing, changed_at=NOW - timedelta(days=30))
    assert [a.id for a in svc.dashboard(db, NOW).stale] == [old.id]


def run(db, status, started_at, plugin="good"):
    r = SearchRun(plugin=plugin, trigger=RunTrigger.manual, status=status, started_at=started_at)
    db.add(r)
    db.commit()
    return r


def test_dashboard_failed_runs_24h(db):
    bad = run(db, RunStatus.error, NOW - timedelta(hours=2))
    slow = run(db, RunStatus.timeout, NOW - timedelta(hours=23))
    run(db, RunStatus.error, NOW - timedelta(hours=25))
    run(db, RunStatus.ok, NOW - timedelta(hours=1))
    out = svc.dashboard(db, NOW)
    assert {r.id for r in out.failed_runs} == {bad.id, slow.id}


def test_dashboard_recent_runs_and_new_count(db):
    for i in range(12):
        run(db, RunStatus.ok, NOW - timedelta(minutes=i))
    for ext, st in (("a", TriageStatus.new), ("b", TriageStatus.new), ("c", TriageStatus.saved)):
        db.add(Posting(source="s", external_id=ext, first_seen_at=NOW, last_seen_at=NOW, title=ext, triage_status=st))
    db.commit()
    out = svc.dashboard(db, NOW)
    assert len(out.recent_runs) == 10 and out.new_count == 2
    assert out.recent_runs[0].started_at == NOW and out.recent_runs[0].started_at.tzinfo is not None
    starts = [r.started_at for r in out.recent_runs]
    assert starts == sorted(starts, reverse=True)


def test_dashboard_endpoint(client):
    body = client.get("/api/dashboard").json()
    assert body == {"new_count": 0, "upcoming": [], "stale": [], "recent_runs": [], "failed_runs": []}


def test_dashboard_failed_runs_not_cut_off_by_newer_runs(db):
    old_fail = run(db, RunStatus.error, NOW - timedelta(hours=20))
    db.add_all(
        SearchRun(plugin="good", trigger=RunTrigger.manual, status=RunStatus.ok,
                  started_at=NOW - timedelta(minutes=i))
        for i in range(250)
    )
    db.commit()
    assert [r.id for r in svc.dashboard(db, NOW).failed_runs] == [old_fail.id]

from datetime import UTC, datetime, timedelta

import pytest

from app.models import (
    Appointment, AppStatus, Posting, RunStatus, RunTrigger, SearchProfile, SearchRun, StatusChange, TriageStatus,
)
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


def _profile(db) -> int:
    p = SearchProfile(name="p", keywords=["py"])
    db.add(p)
    db.commit()
    return p.id


def run(db, status, started_at, plugin="good", profile_id=None):
    r = SearchRun(plugin=plugin, trigger=RunTrigger.manual, status=status, started_at=started_at, profile_id=profile_id)
    db.add(r)
    db.commit()
    return r


def test_dashboard_older_failed_count_24h(db):
    # only failures of the last 24 h that are not among the 10 recent runs are counted
    pid = _profile(db)
    run(db, RunStatus.error, NOW - timedelta(hours=2), profile_id=pid)
    run(db, RunStatus.timeout, NOW - timedelta(hours=23), profile_id=pid)
    run(db, RunStatus.error, NOW - timedelta(hours=25), profile_id=pid)
    for i in range(10):
        run(db, RunStatus.ok, NOW - timedelta(minutes=i))
    out = svc.dashboard(db, NOW)
    assert out.older_failed_count == 2
    assert all(r.status == RunStatus.ok for r in out.recent_runs)


def test_dashboard_recent_failures_are_not_counted_twice(db):
    run(db, RunStatus.error, NOW - timedelta(minutes=5))
    run(db, RunStatus.ok, NOW - timedelta(minutes=1))
    out = svc.dashboard(db, NOW)
    assert out.older_failed_count == 0
    assert [r.status for r in out.recent_runs] == [RunStatus.ok, RunStatus.error]  # strictly newest first


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
    assert body == {"new_count": 0, "upcoming": [], "stale": [], "recent_runs": [], "older_failed_count": 0}


def test_dashboard_older_failed_count_not_cut_off_by_newer_runs(db):
    run(db, RunStatus.error, NOW - timedelta(hours=20), profile_id=_profile(db))
    db.add_all(
        SearchRun(plugin="good", trigger=RunTrigger.manual, status=RunStatus.ok,
                  started_at=NOW - timedelta(minutes=i))
        for i in range(250)
    )
    db.commit()
    assert svc.dashboard(db, NOW).older_failed_count == 1


def test_dashboard_older_failed_count_ignores_runs_of_deleted_profiles(db):
    # the "view history" link leads to the profiles page, where such runs cannot be found
    run(db, RunStatus.error, NOW - timedelta(hours=3))  # profile_id NULL
    with_profile = SearchRun(plugin="good", trigger=RunTrigger.manual, status=RunStatus.error,
                             started_at=NOW - timedelta(hours=4), profile_id=_profile(db))
    db.add(with_profile)
    for i in range(10):
        run(db, RunStatus.ok, NOW - timedelta(minutes=i))
    assert svc.dashboard(db, NOW).older_failed_count == 1

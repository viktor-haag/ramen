from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from app.models import Posting, PostingMatch, SearchProfile, TriageStatus
from app.services.ingest import ingest

NOW = datetime(2026, 10, 22, 8, 0, tzinfo=UTC)


def item(ext: str, **kw) -> dict:
    return {"source": "ignored", "external_id": ext, "url": f"https://x/{ext}", "title": f"T{ext}", **kw}


def make_profile(session, **kw) -> SearchProfile:
    p = SearchProfile(name="p", keywords=["k"], **kw)
    session.add(p)
    session.flush()
    return p


def test_new_postings_created_with_triage_new(session):
    p = make_profile(session)
    r = ingest(session, profile=p, source="src", items=[item("1"), item("2")], now=NOW)
    assert (r.new_count, r.total_count, r.invalid_count) == (2, 2, 0)
    rows = session.scalars(select(Posting)).all()
    assert len(rows) == 2
    for row in rows:
        assert row.source == "src"
        assert row.triage_status == TriageStatus.new
        assert row.first_seen_at == row.last_seen_at == NOW


def test_known_posting_updated_keeps_triage(session):
    p = make_profile(session)
    ingest(session, profile=p, source="src", items=[item("1")], now=NOW)
    row = session.scalars(select(Posting)).one()
    row.triage_status = TriageStatus.dismissed
    row.triaged_at = NOW
    session.flush()
    now2 = NOW + timedelta(hours=3)
    r = ingest(session, profile=p, source="src", items=[item("1", title="Changed")], now=now2)
    assert r.new_count == 0 and r.total_count == 1
    row = session.scalars(select(Posting)).one()
    assert row.title == "Changed"
    assert row.triage_status == TriageStatus.dismissed
    assert row.triaged_at == NOW
    assert row.first_seen_at == NOW
    assert row.last_seen_at == now2


def test_invalid_items_counted(session):
    p = make_profile(session)
    bad = {"external_id": "9", "url": "https://x/9"}
    r = ingest(session, profile=p, source="src", items=[item("1"), bad, item("2")], now=NOW)
    assert (r.new_count, r.total_count, r.invalid_count) == (2, 2, 1)
    assert session.scalar(select(func.count()).select_from(Posting)) == 2


def test_duplicate_in_batch(session):
    p = make_profile(session)
    r = ingest(session, profile=p, source="src", items=[item("1"), item("1", title="dup")], now=NOW)
    assert r.total_count == 1 and r.new_count == 1
    row = session.scalars(select(Posting)).one()
    assert row.title == "T1"


def test_two_profiles_same_posting(session):
    a, b = make_profile(session), make_profile(session)
    ingest(session, profile=a, source="src", items=[item("1")], now=NOW)
    r = ingest(session, profile=b, source="src", items=[item("1")], now=NOW + timedelta(hours=1))
    assert r.new_count == 0 and r.total_count == 1
    assert session.scalar(select(func.count()).select_from(Posting)) == 1
    assert session.scalar(select(func.count()).select_from(PostingMatch)) == 2


def test_post_filter_employment_type(session):
    p = make_profile(session, employment_type="fulltime")
    items = [
        item("1", employment_type="fulltime"),
        item("2", employment_type="parttime"),
        item("3", employment_type=None),
    ]
    r = ingest(session, profile=p, source="src", items=items, now=NOW)
    assert (r.new_count, r.total_count) == (2, 2)
    ids = set(session.scalars(select(Posting.external_id)))
    assert ids == {"1", "3"}


def test_post_filter_remote(session):
    p = make_profile(session, remote=True)
    items = [item("1", remote=True), item("2", remote=False), item("3")]
    r = ingest(session, profile=p, source="src", items=items, now=NOW)
    assert r.total_count == 2


def test_lost_race_is_not_counted_as_new(session):
    """Another run inserted the same key (older first_seen_at) just before our upsert."""
    p = make_profile(session)
    older = NOW - timedelta(minutes=1)
    session.add(Posting(source="src", external_id="1", title="theirs", first_seen_at=older, last_seen_at=older))
    session.flush()
    r = ingest(session, profile=p, source="src", items=[item("1")], now=NOW)
    assert (r.new_count, r.total_count) == (0, 1)
    row = session.scalars(select(Posting)).one()
    assert row.first_seen_at == older and row.last_seen_at == NOW


def test_ingest_reports_new_ids(session):
    p = make_profile(session, employment_type=None)
    first = ingest(session, profile=p, source="src", items=[item("1"), item("1"), {"bad": 1}], now=NOW)
    assert first.new_ids == [r for r in session.scalars(select(Posting.id).where(Posting.external_id == "1"))]
    later = NOW + timedelta(hours=1)
    second = ingest(session, profile=p, source="src", items=[item("1"), item("2")], now=later)
    new_row = session.scalar(select(Posting.id).where(Posting.external_id == "2"))
    assert second.new_ids == [new_row]  # the re-seen posting is not new
    assert len(second.new_ids) == second.new_count == 1

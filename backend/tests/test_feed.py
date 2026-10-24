from datetime import UTC, datetime, timedelta

import httpx
import pytest

from app.models import FitRating, FitStatus, Posting, PostingFit, PostingMatch, SearchProfile, TriageStatus, UserProfile
from app.plugins.http import make_client
from app.services.geocode import Geocoder

NOW = datetime(2026, 10, 22, 8, 0, tzinfo=UTC)
MUNICH = (48.137, 11.575)


class FakeGeocoder:
    def __init__(self, table: dict[str, tuple[float, float]] | None = None):
        self.table = table or {"München": MUNICH}
        self.calls: list[str] = []

    def lookup(self, place: str):
        self.calls.append(place)
        return self.table.get(place)


@pytest.fixture(autouse=True)
def fake_geocoder(app):
    app.state.geocoder = FakeGeocoder()


@pytest.fixture
def db(app):
    with app.state.session_factory() as s:
        yield s


def add(db, ext: str, **kw) -> Posting:
    kw.setdefault("source", "src")
    kw.setdefault("title", f"Title {ext}")
    kw.setdefault("first_seen_at", NOW)
    kw.setdefault("last_seen_at", NOW)
    p = Posting(external_id=ext, **kw)
    db.add(p)
    db.commit()
    return p


def feed(client, **params) -> dict:
    r = client.get("/api/feed", params=params)
    assert r.status_code == 200, r.text
    return r.json()


def ids(page: dict) -> list[int]:
    return [i["id"] for i in page["items"]]


def test_default_hides_dismissed(client, db):
    a = add(db, "1")
    b = add(db, "2", triage_status=TriageStatus.saved)
    add(db, "3", triage_status=TriageStatus.dismissed)
    page = feed(client)
    assert sorted(ids(page)) == sorted([a.id, b.id])
    assert page["total"] == 2


def test_triage_filter_dismissed_only(client, db):
    add(db, "1")
    d = add(db, "3", triage_status=TriageStatus.dismissed)
    assert ids(feed(client, triage="dismissed")) == [d.id]


def test_triage_filter_repeated_params(client, db):
    a = add(db, "1")
    d = add(db, "3", triage_status=TriageStatus.dismissed)
    assert sorted(ids(feed(client, triage=["new", "dismissed"]))) == sorted([a.id, d.id])


def test_filter_source_and_profile(client, db):
    a = add(db, "1", source="arbeitsagentur")
    b = add(db, "2", source="other")
    c = add(db, "3", source="arbeitsagentur")
    prof = SearchProfile(name="p", keywords=["k"])
    db.add(prof)
    db.flush()
    db.add_all([PostingMatch(posting_id=a.id, profile_id=prof.id), PostingMatch(posting_id=b.id, profile_id=prof.id)])
    db.commit()
    assert sorted(ids(feed(client, source="arbeitsagentur"))) == sorted([a.id, c.id])
    assert sorted(ids(feed(client, source=["arbeitsagentur", "other"]))) == sorted([a.id, b.id, c.id])
    assert sorted(ids(feed(client, profile_id=prof.id))) == sorted([a.id, b.id])
    assert ids(feed(client, profile_id=prof.id, source="other")) == [b.id]
    item = next(i for i in feed(client, profile_id=prof.id)["items"] if i["id"] == a.id)
    assert item["profile_ids"] == [prof.id]
    assert "raw" not in item


def test_q_matches_company_case_insensitive(client, db):
    a = add(db, "1", company="Müller GmbH")
    b = add(db, "2", description="Wir suchen Entwickler bei MÜLLER")
    add(db, "3", company="Schmidt AG")
    assert sorted(ids(feed(client, q="müller"))) == sorted([a.id, b.id])
    assert ids(feed(client, q="schmidt")) != []


def test_q_escapes_wildcards(client, db):
    a = add(db, "1", title="100% remote")
    add(db, "2", title="1000 things")
    assert ids(feed(client, q="100%")) == [a.id]
    c = add(db, "3", title="a_b")
    add(db, "4", title="axb")
    assert ids(feed(client, q="a_b")) == [c.id]


def test_found_after(client, db):
    old = add(db, "1", first_seen_at=NOW - timedelta(days=5))
    new = add(db, "2", first_seen_at=NOW)
    cutoff = (NOW - timedelta(days=1)).isoformat()
    assert ids(feed(client, found_after=cutoff)) == [new.id]
    assert ids(feed(client, found_before=cutoff)) == [old.id]


def test_published_after_employment_remote(client, db):
    a = add(db, "1", published_at=NOW, employment_type="full_time", remote=True)
    add(db, "2", published_at=NOW - timedelta(days=9), employment_type="part_time", remote=False)
    assert ids(feed(client, published_after=(NOW - timedelta(days=1)).isoformat())) == [a.id]
    assert ids(feed(client, employment_type="full_time")) == [a.id]
    assert ids(feed(client, remote="true")) == [a.id]


def test_sort_desc_and_published(client, db):
    a = add(db, "1", first_seen_at=NOW - timedelta(days=2), published_at=NOW)
    b = add(db, "2", first_seen_at=NOW, published_at=NOW - timedelta(days=2))
    c = add(db, "3", first_seen_at=NOW - timedelta(days=1), published_at=None)
    assert ids(feed(client)) == [b.id, c.id, a.id]
    assert ids(feed(client, sort="published_at")) == [a.id, b.id, c.id]


def test_radius_with_coordinates(client, db):
    inside = add(db, "1", location="Freising", lat=48.40, lon=11.74)
    add(db, "2", location="Nürnberg", lat=49.45, lon=11.08)
    page = feed(client, location="München", radius_km=50)
    assert ids(page) == [inside.id]
    assert page["total"] == 1


def test_radius_posting_without_coords_falls_back_to_text(client, db):
    p = add(db, "1", location="München-Schwabing")
    add(db, "2", location="Hamburg")
    far = add(db, "3", location="Hamburg", lat=53.55, lon=10.0)
    assert ids(feed(client, location="München", radius_km=10)) == [p.id]
    assert far.id not in ids(feed(client, location="München", radius_km=10))


def test_radius_ungeocodable_location_falls_back_to_text(client, db, app):
    app.state.geocoder = FakeGeocoder({})
    p = add(db, "1", location="Kleinkaff bei Irgendwo", lat=48.0, lon=11.0)
    add(db, "2", location="Berlin", lat=52.5, lon=13.4)
    assert ids(feed(client, location="Kleinkaff", radius_km=20)) == [p.id]


def test_location_without_radius_is_text_only(client, db, app):
    p = add(db, "1", location="München", lat=48.1, lon=11.5)
    add(db, "2", location="Freising", lat=48.40, lon=11.74)
    assert ids(feed(client, location="münchen")) == [p.id]
    assert app.state.geocoder.calls == []


def test_radius_pagination_after_filter(client, db):
    for i in range(3):
        add(db, f"in{i}", location="Freising", lat=48.40, lon=11.74, first_seen_at=NOW - timedelta(hours=i))
    for i in range(3):
        add(db, f"out{i}", location="Nürnberg", lat=49.45, lon=11.08, first_seen_at=NOW - timedelta(minutes=i))
    page = feed(client, location="München", radius_km=50, limit=2, offset=2)
    assert page["total"] == 3
    assert len(page["items"]) == 1


def test_pagination_total(client, db):
    made = [add(db, str(i), first_seen_at=NOW - timedelta(minutes=i)) for i in range(5)]
    page = feed(client, limit=2, offset=0)
    assert page["total"] == 5
    assert ids(page) == [made[0].id, made[1].id]
    assert ids(feed(client, limit=2, offset=4)) == [made[4].id]


def test_invalid_params_422(client):
    assert client.get("/api/feed", params={"limit": 500}).status_code == 422
    assert client.get("/api/feed", params={"triage": "bogus"}).status_code == 422


def test_get_posting_detail_with_raw_and_application(client, db):
    p = add(db, "1", raw={"a": 1})
    r = client.get(f"/api/postings/{p.id}")
    assert r.status_code == 200
    body = r.json()
    assert body["raw"] == {"a": 1}
    assert body["application_id"] is None and body["profile_ids"] == []
    app_id = client.post(f"/api/postings/{p.id}/save").json()["application_id"]
    assert client.get(f"/api/postings/{p.id}").json()["application_id"] == app_id
    assert feed(client)["items"][0]["application_id"] == app_id


def test_get_posting_404(client):
    r = client.get("/api/postings/999")
    assert r.status_code == 404
    assert r.json()["code"] == "posting_not_found"


# --- Geocoder (no network: MockTransport) ---------------------------------

def make_geocoder(handler) -> tuple[Geocoder, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def wrapped(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    client = make_client(retries=0, transport=httpx.MockTransport(wrapped))
    return Geocoder(client=client), seen


def test_geocoder_parses_and_caches():
    g, seen = make_geocoder(lambda r: httpx.Response(200, json=[{"lat": "48.137", "lon": "11.575"}]))
    assert g.lookup("München") == (48.137, 11.575)
    assert g.lookup("München") == (48.137, 11.575)
    assert len(seen) == 1
    req = seen[0]
    assert req.url.host == "nominatim.openstreetmap.org"
    assert req.url.params["q"] == "München"
    assert req.url.params["countrycodes"] == "de" and req.url.params["limit"] == "1"
    assert req.url.params["format"] == "json"
    assert "jobtracker" in req.headers["user-agent"]


def test_geocoder_caches_empty_result():
    g, seen = make_geocoder(lambda r: httpx.Response(200, json=[]))
    assert g.lookup("Nirgendwo") is None
    assert g.lookup("Nirgendwo") is None
    assert len(seen) == 1


def test_geocoder_network_error_returns_none():
    def boom(request):
        raise httpx.ConnectError("down")

    g, seen = make_geocoder(boom)
    assert g.lookup("München") is None


def test_geocoder_http_error_and_garbage_return_none():
    g, _ = make_geocoder(lambda r: httpx.Response(500))
    assert g.lookup("A") is None
    g, _ = make_geocoder(lambda r: httpx.Response(200, text="not json"))
    assert g.lookup("B") is None
    g, _ = make_geocoder(lambda r: httpx.Response(200, json=[{"lat": "x"}]))
    assert g.lookup("C") is None


def test_naive_and_date_only_datetimes_are_utc(client, db):
    old = add(db, "1", first_seen_at=NOW - timedelta(days=5), published_at=NOW - timedelta(days=5))
    new = add(db, "2", first_seen_at=NOW, published_at=NOW)
    assert ids(feed(client, found_after="2026-10-21T08:00:00")) == [new.id]
    assert ids(feed(client, found_before="2026-10-21T08:00:00")) == [old.id]
    assert ids(feed(client, found_after="2026-10-22")) == [new.id]
    assert ids(feed(client, found_before="2026-10-22")) == [old.id]
    assert ids(feed(client, published_after="2026-10-21T08:00:00")) == [new.id]
    assert ids(feed(client, found_after="2026-10-21T10:00:00+02:00")) == [new.id]


def test_geocoder_failure_not_retried_within_ttl(monkeypatch):
    from app.services import geocode

    now = [1000.0]
    monkeypatch.setattr(geocode.time, "monotonic", lambda: now[0])

    def boom(request):
        raise httpx.ConnectError("down")

    g, seen = make_geocoder(boom)
    assert g.lookup("München") is None
    now[0] += 59
    assert g.lookup("München") is None
    assert len(seen) == 1
    now[0] += 2
    assert g.lookup("München") is None
    assert len(seen) == 2


# --- fit in the feed -------------------------------------------------------------------------------


def add_fit(db, posting, rating=None, status=FitStatus.done, version=1):
    db.add(PostingFit(posting_id=posting.id, rating=rating, status=status, profile_version=version,
                      explanation="why" if rating else None))
    db.commit()


def test_feed_items_carry_fit(client, db):
    a = add(db, "1")
    b = add(db, "2")
    add_fit(db, a, FitRating.good, version=1)
    db.add(UserProfile(id=1, profile_markdown="## Summary\nDev.", version=2,
                       edited_since_generation=False, inputs_changed_since_generation=False))
    db.commit()
    by_id = {i["id"]: i for i in feed(client)["items"]}
    assert by_id[a.id]["fit"]["rating"] == "good"
    assert by_id[a.id]["fit"]["status"] == "done"
    assert by_id[a.id]["fit"]["explanation"] == "why"
    assert by_id[a.id]["fit"]["outdated"] is True
    assert by_id[b.id]["fit"] is None
    # posting detail and application detail carry it too
    assert client.get(f"/api/postings/{a.id}").json()["fit"]["rating"] == "good"
    app_id = client.post(f"/api/postings/{a.id}/save").json()["application_id"]
    assert client.get(f"/api/applications/{app_id}").json()["posting"]["fit"]["rating"] == "good"


def test_feed_fit_not_outdated_without_profile_row(client, db):
    a = add(db, "1")
    add_fit(db, a, FitRating.good, version=1)
    assert feed(client)["items"][0]["fit"]["outdated"] is False


def test_feed_filter_fit(client, db):
    good = add(db, "1")
    poor = add(db, "2")
    none_row = add(db, "3")  # row without a rating (e.g. queued first time)
    no_row = add(db, "4")
    add_fit(db, good, FitRating.good)
    add_fit(db, poor, FitRating.poor)
    add_fit(db, none_row, None, status=FitStatus.queued)
    assert set(ids(feed(client, fit=["good", "none"]))) == {good.id, none_row.id, no_row.id}
    assert ids(feed(client, fit="poor")) == [poor.id]
    assert feed(client, fit=["good", "none"])["total"] == 3
    assert feed(client)["total"] == 4


def _fit_sort_fixture(db):
    t = NOW
    made = {}
    for name, rating, age in [
        ("none_new", None, 0), ("poor_new", FitRating.poor, 1), ("good_old", FitRating.good, 5),
        ("good_new", FitRating.good, 2), ("mod", FitRating.moderate, 3), ("none_old", None, 9),
    ]:
        p = add(db, name, first_seen_at=t - timedelta(days=age), lat=48.1, lon=11.6, location="München")
        if rating:
            add_fit(db, p, rating)
        made[name] = p.id
    return made


EXPECTED_FIT_ORDER = ["good_new", "good_old", "mod", "poor_new", "none_new", "none_old"]


def test_feed_sort_fit(client, db):
    m = _fit_sort_fixture(db)
    assert ids(feed(client, sort="fit")) == [m[n] for n in EXPECTED_FIT_ORDER]


def test_feed_sort_fit_radius_branch(client, db):
    m = _fit_sort_fixture(db)
    page = feed(client, sort="fit", location="München", radius_km=20)
    assert ids(page) == [m[n] for n in EXPECTED_FIT_ORDER]
    assert ids(feed(client, sort="fit", location="München", radius_km=20, fit="none")) == [m["none_new"], m["none_old"]]


def test_feed_sort_fit_requeued_row_keeps_rating(client, db):
    a = add(db, "a", first_seen_at=NOW - timedelta(days=3))
    b = add(db, "b", first_seen_at=NOW - timedelta(days=2))
    c = add(db, "c", first_seen_at=NOW - timedelta(days=1))
    add_fit(db, a, FitRating.good, status=FitStatus.queued)  # R3: re-queued, old rating still shown
    add_fit(db, b, FitRating.poor)
    assert ids(feed(client, sort="fit")) == [a.id, b.id, c.id]

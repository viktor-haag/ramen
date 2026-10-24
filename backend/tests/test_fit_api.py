import pytest

from app.fit.queue import FitQueue
from app.models import AppSetting, FitRating, FitStatus, LLMUsage, Posting, PostingFit, TriageStatus, UserProfile
from test_fit_queue import TIMEOUT, FakeEval
from test_profile_docs import add_config


@pytest.fixture
def fake(client, app):
    """Replace the app's queue with one whose evaluation blocks until released."""
    f = FakeEval(block=True)
    q = FitQueue(app.state.session_factory, evaluate=f)
    original = app.state.fit_queue
    app.state.fit_queue = q
    f.queue = q
    yield f
    f.release.set()
    q.shutdown()
    app.state.fit_queue = original


def seed(app, markdown="## Summary\nDev.", version=3, postings=1):
    with app.state.session_factory() as s:
        s.add(UserProfile(id=1, profile_markdown=markdown, version=version,
                          edited_since_generation=False, inputs_changed_since_generation=False))
        ps = [Posting(source="src", external_id=str(i), title=f"P{i}") for i in range(postings)]
        s.add_all(ps)
        s.commit()
        return [p.id for p in ps]


def test_single_enqueue(client, app, fake):
    add_config(client)
    (pid,) = seed(app)
    r = client.post(f"/api/fit/{pid}", params={"lang": "de"})
    assert r.status_code == 200
    assert r.json() == {"queued": 1, "limit_exceeded": False}
    r = client.post(f"/api/fit/{pid}")  # already queued/running
    assert r.json() == {"queued": 0, "limit_exceeded": False}
    assert fake.started.acquire(timeout=TIMEOUT)
    assert fake.calls == [(pid, "de")]
    fake.release.set()
    assert fake.queue.wait_idle(TIMEOUT)


def test_single_default_lang_and_limit_warning(client, app, fake):
    add_config(client)
    (pid,) = seed(app)
    with app.state.session_factory() as s:
        s.add_all([AppSetting(key="daily_limit_kind", value="tokens"), AppSetting(key="daily_limit_value", value=10)])
        s.add(LLMUsage(purpose="fit", input_tokens=10, output_tokens=0, ok=True))
        s.commit()
    fake.release.set()
    r = client.post(f"/api/fit/{pid}")
    assert r.json() == {"queued": 1, "limit_exceeded": True}  # a warning only: still evaluated
    assert fake.queue.wait_idle(TIMEOUT)
    assert fake.calls == [(pid, "en")]


def test_single_requires_profile(client, app, fake):
    add_config(client)
    (pid,) = seed(app, markdown="  \n")
    r = client.post(f"/api/fit/{pid}")
    assert r.status_code == 409 and r.json()["code"] == "profile_missing"
    assert fake.calls == []


def test_single_requires_config(client, app, fake):
    (pid,) = seed(app)
    r = client.post(f"/api/fit/{pid}")
    assert r.status_code == 409 and r.json()["code"] == "llm_not_configured"


def test_single_unknown_posting(client, app, fake):
    add_config(client)
    seed(app, postings=0)
    r = client.post("/api/fit/9999")
    assert r.status_code == 404 and r.json()["code"] == "posting_not_found"


def test_single_invalid_lang(client, app, fake):
    add_config(client)
    (pid,) = seed(app)
    r = client.post(f"/api/fit/{pid}", params={"lang": "fr"})
    assert r.status_code == 422 and r.json()["code"] == "validation_error"


def test_get_fits(client, app):
    a, b, c = seed(app, version=3, postings=3)
    with app.state.session_factory() as s:
        s.add_all([
            PostingFit(posting_id=a, status=FitStatus.done, rating=FitRating.good, explanation="ok",
                       profile_version=2),
            PostingFit(posting_id=b, status=FitStatus.done, rating=FitRating.poor, explanation="no",
                       profile_version=3),
        ])
        s.commit()
    r = client.get("/api/fit", params={"ids": f"{a},{b},{c}"})
    assert r.status_code == 200
    items = {i["posting_id"]: i["fit"] for i in r.json()}
    assert items[c] is None
    assert items[a]["outdated"] is True and items[a]["rating"] == "good" and items[a]["status"] == "done"
    assert items[b]["outdated"] is False and items[b]["explanation"] == "no"
    assert set(items[a]) == {"rating", "status", "error", "explanation", "evaluated_at", "outdated"}


def test_get_fits_validation(client):
    assert client.get("/api/fit", params={"ids": "1,x"}).status_code == 422
    too_many = ",".join(str(i) for i in range(201))
    assert client.get("/api/fit", params={"ids": too_many}).status_code == 422
    assert client.get("/api/fit", params={"ids": ""}).json() == []


def test_status(client, app, fake):
    r = client.get("/api/fit/status")
    assert r.json() == {"profile": False, "configured": False, "active": 0}
    add_config(client)
    (pid,) = seed(app)
    client.post(f"/api/fit/{pid}")
    assert client.get("/api/fit/status").json() == {"profile": True, "configured": True, "active": 1}
    fake.release.set()
    assert fake.queue.wait_idle(TIMEOUT)
    assert client.get("/api/fit/status").json()["active"] == 0


def test_app_queue_is_wired(client, app):
    assert isinstance(app.state.fit_queue, FitQueue)


@pytest.mark.parametrize("path", ["/api/admin/clear-feed", "/api/admin/reset", "/api/admin/delete-profile"])
def test_admin_discards_fit_jobs(client, app, monkeypatch, path):
    calls = []
    monkeypatch.setattr(app.state.fit_queue, "discard_all", lambda: calls.append(True))
    assert client.post(path).status_code == 200
    assert calls == [True]


def test_cancel(client, app, fake):
    add_config(client)
    a, b = seed(app, postings=2)
    with app.state.session_factory() as s:
        s.add(PostingFit(posting_id=a, status=FitStatus.done, rating=FitRating.good, explanation="old",
                         profile_version=3))
        s.commit()
    assert client.post("/api/fit/cancel").json() == {"cancelled": 0}
    client.post(f"/api/fit/{a}")
    client.post(f"/api/fit/{b}")
    assert fake.started.acquire(timeout=TIMEOUT)
    r = client.post("/api/fit/cancel")
    assert r.status_code == 200
    assert r.json() == {"cancelled": 2}
    fits = {i["posting_id"]: i["fit"] for i in client.get("/api/fit", params={"ids": f"{a},{b}"}).json()}
    assert fits[a]["status"] == "done" and fits[a]["rating"] == "good"
    assert fits[b] is None
    fake.release.set()
    assert fake.queue.wait_idle(TIMEOUT)
    assert client.get("/api/fit/status").json()["active"] == 0


# --- bulk evaluation -----------------------------------------------------------------------------------


def bulk_setup(app):
    """Postings: 0 no row, 1 done, 2 queued, 3 running, 4 error, 5 no row but dismissed."""
    ids_ = seed(app, postings=6)
    states = {1: FitStatus.done, 2: FitStatus.queued, 3: FitStatus.running, 4: FitStatus.error}
    with app.state.session_factory() as s:
        for i, st in states.items():
            s.add(PostingFit(posting_id=ids_[i], status=st, rating=FitRating.good if st is FitStatus.done else None))
        s.get(Posting, ids_[5]).triage_status = TriageStatus.dismissed
        s.commit()
    return ids_


def test_bulk_count_and_enqueue(client, app, fake):
    add_config(client)
    ids_ = bulk_setup(app)
    assert client.get("/api/fit/bulk/count").json() == {"count": 2}  # no row + error; dismissed hidden by default
    fake.release.set()
    r = client.post("/api/fit/bulk", params={"lang": "de"})
    assert r.status_code == 200
    assert r.json() == {"queued": 2, "limit_exceeded": False}
    assert fake.queue.wait_idle(TIMEOUT)
    assert sorted(fake.calls) == sorted([(ids_[0], "de"), (ids_[4], "de")])
    assert client.get("/api/fit/bulk/count").json() == {"count": 0}


def test_bulk_applies_feed_filter(client, app, fake):
    add_config(client)
    ids_ = bulk_setup(app)
    assert client.get("/api/fit/bulk/count", params={"triage": "dismissed"}).json() == {"count": 1}
    assert client.get("/api/fit/bulk/count", params={"q": "P0"}).json() == {"count": 1}
    assert client.get("/api/fit/bulk/count", params={"q": "nomatch"}).json() == {"count": 0}
    fake.release.set()
    assert client.post("/api/fit/bulk", params={"q": "P4"}).json()["queued"] == 1
    assert fake.queue.wait_idle(TIMEOUT)
    assert fake.calls == [(ids_[4], "en")]


def test_bulk_respects_limit(client, app, fake):
    add_config(client)
    bulk_setup(app)
    with app.state.session_factory() as s:
        s.add_all([AppSetting(key="daily_limit_kind", value="tokens"), AppSetting(key="daily_limit_value", value=10)])
        s.add(LLMUsage(purpose="fit", input_tokens=10, output_tokens=0, ok=True))
        s.commit()
    r = client.post("/api/fit/bulk")
    assert r.status_code == 409 and r.json()["code"] == "daily_limit_reached"
    assert fake.calls == [] and fake.queue.active_count() == 0
    with app.state.session_factory() as s:
        assert s.query(PostingFit).count() == 4  # unchanged
    assert client.get("/api/fit/bulk/count").json() == {"count": 2}  # counting is unaffected


def test_bulk_requires_profile_and_config(client, app, fake):
    seed(app, markdown="")
    r = client.post("/api/fit/bulk")
    assert r.status_code == 409 and r.json()["code"] == "profile_missing"
    seed_profile = app.state.session_factory()
    seed_profile.get(UserProfile, 1).profile_markdown = "## Summary\nDev."
    seed_profile.commit()
    seed_profile.close()
    r = client.post("/api/fit/bulk")
    assert r.status_code == 409 and r.json()["code"] == "llm_not_configured"
    assert fake.calls == []


def test_bulk_routes_not_shadowed_by_posting_id(client, app, fake):
    add_config(client)
    seed(app)
    r = client.post("/api/fit/bulk", params={"lang": "fr"})
    assert r.status_code == 422
    # routed to /fit/bulk (a query-param error), not to /fit/{posting_id} (which would reject the path)
    assert r.json()["params"]["errors"][0]["loc"] == ["query", "lang"]
    assert client.get("/api/fit/bulk/count").status_code == 200


def fit_rows_setup(app):
    """0 no row, 1 error keeping rating=poor (R3), 2 done poor, 3 done good, 4 queued keeping rating=good, 5 error unrated."""
    ids_ = seed(app, postings=6)
    rows = [
        (1, FitStatus.error, FitRating.poor), (2, FitStatus.done, FitRating.poor), (3, FitStatus.done, FitRating.good),
        (4, FitStatus.queued, FitRating.good), (5, FitStatus.error, None),
    ]
    with app.state.session_factory() as s:
        for i, st, rating in rows:
            s.add(PostingFit(posting_id=ids_[i], status=st, rating=rating))
        s.commit()
    return ids_


def test_bulk_count_fit_filter(client, app, fake):
    add_config(client)
    ids_ = fit_rows_setup(app)
    assert client.get("/api/fit/bulk/count", params={"fit": "poor"}).json() == {"count": 1}  # only the error row
    assert client.get("/api/fit/bulk/count", params={"fit": ["poor", "good"]}).json() == {"count": 1}
    assert client.get("/api/fit/bulk/count", params={"fit": "none"}).json() == {"count": 2}  # no row + error unrated
    fake.release.set()
    assert client.post("/api/fit/bulk", params={"fit": "poor"}).json()["queued"] == 1
    assert fake.queue.wait_idle(TIMEOUT)
    assert fake.calls == [(ids_[1], "en")]


def test_bulk_enqueue_fit_none_sorted_by_fit(client, app, fake):
    add_config(client)
    ids_ = fit_rows_setup(app)
    fake.release.set()
    r = client.post("/api/fit/bulk", params={"fit": "none", "sort": "fit"})
    assert r.json()["queued"] == 2
    assert fake.queue.wait_idle(TIMEOUT)
    assert sorted(fake.calls) == sorted([(ids_[0], "en"), (ids_[5], "en")])

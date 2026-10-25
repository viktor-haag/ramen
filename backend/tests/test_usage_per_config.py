"""Per-config usage and daily limits (Paket B, section 3)."""
from datetime import UTC, datetime

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import inspect, text

from app.db import Base, make_engine
from app.db_migrate import BACKEND_DIR, upgrade
from app.fit.queue import FitQueue
from app.models import AppSetting, LLMConfig, LLMProvider, LLMUsage, Posting, UserProfile
from app.services import usage
from app.services.usage import LimitHit
from test_fit_queue import TIMEOUT, FakeEval

NOW = datetime(2026, 10, 24, 12, 0, tzinfo=UTC)


def add_config(session, name, *, kind="none", value=None, price_in=None, price_out=None, default=False):
    cfg = LLMConfig(name=name, provider=LLMProvider.anthropic, model="m", api_key="sk-test-1234",
                    price_in=price_in, price_out=price_out, is_default=default,
                    daily_limit_kind=kind, daily_limit_value=value)
    session.add(cfg)
    session.commit()
    return cfg


def add_usage(session, at, cfg_id, i, o=0):
    session.add(LLMUsage(at=at, config_id=cfg_id, purpose="fit", input_tokens=i, output_tokens=o, ok=True))
    session.commit()


def set_global(session, kind, value):
    for key, val in (("daily_limit_kind", kind), ("daily_limit_value", value)):
        row = session.get(AppSetting, key)
        if row is None:
            session.add(AppSetting(key=key, value=val))
        else:
            row.value = val
    session.commit()


def test_config_limit_tokens_and_eur(session):
    claude = add_config(session, "Claude", kind="tokens", value=100)
    other = add_config(session, "Other")
    add_usage(session, NOW, other.id, i=10_000)  # another config's usage does not count
    assert usage.limit_status(session, NOW, claude.id) is None
    add_usage(session, NOW, claude.id, i=60, o=30)
    assert usage.limit_status(session, NOW, claude.id) is None
    add_usage(session, NOW, claude.id, i=10)
    assert usage.limit_status(session, NOW, claude.id) == LimitHit("config", "Claude")
    assert usage.limit_exceeded(session, NOW, claude.id) is True
    assert usage.limit_exceeded(session, NOW, other.id) is False
    assert usage.limit_exceeded(session, NOW) is False  # no global limit
    # yesterday's usage (Berlin) does not count today
    assert usage.limit_status(session, datetime(2026, 10, 25, 12, 0, tzinfo=UTC), claude.id) is None

    paid = add_config(session, "Paid", kind="eur", value=5.0, price_in=10.0, price_out=10.0)
    add_usage(session, NOW, paid.id, i=400_000)  # 4 EUR
    assert usage.limit_status(session, NOW, paid.id) is None
    add_usage(session, NOW, paid.id, i=0, o=100_000)  # +1 EUR
    assert usage.limit_status(session, NOW, paid.id) == LimitHit("config", "Paid")
    assert usage.limit_status(session, NOW, 9999) is None  # unknown config: no own limit


def test_global_limit_reported_first(session):
    claude = add_config(session, "Claude", kind="tokens", value=10)
    add_usage(session, NOW, claude.id, i=50)
    assert usage.limit_status(session, NOW, claude.id) == LimitHit("config", "Claude")
    set_global(session, "tokens", 20)
    assert usage.limit_status(session, NOW, claude.id) == LimitHit("global", None)
    assert usage.limit_status(session, NOW) == LimitHit("global", None)


def _seed_fit(app):
    with app.state.session_factory() as s:
        s.add(UserProfile(id=1, profile_markdown="## Summary\nDev.", version=3,
                          edited_since_generation=False, inputs_changed_since_generation=False))
        ps = [Posting(source="src", external_id=str(i), title=f"P{i}") for i in range(2)]
        s.add_all(ps)
        s.commit()
        return [p.id for p in ps]


def _post_config(client, name, **extra):
    body = {"name": name, "provider": "anthropic", "model": "m", "api_key": "sk-test-1234", **extra}
    res = client.post("/api/llm/configs", json=body)
    assert res.status_code == 200, res.text
    return res.json()


def test_config_limit_blocks_only_its_purpose(client, app):
    fake = FakeEval()
    q = FitQueue(app.state.session_factory, evaluate=fake)
    original, app.state.fit_queue = app.state.fit_queue, q
    try:
        fit_cfg = _post_config(client, "Claude", daily_limit_kind="tokens", daily_limit_value=100)
        prof_cfg = _post_config(client, "Prof", daily_limit_kind="tokens", daily_limit_value=100)
        assert client.put("/api/llm/purposes", json={
            "profile": prof_cfg["id"], "fit": fit_cfg["id"], "extraction": None}).status_code == 200
        ids = _seed_fit(app)
        sf = app.state.session_factory
        with sf() as s:
            s.add(AppSetting(key="fit_auto", value=True))
            s.commit()
            add_usage(s, datetime.now(UTC), prof_cfg["id"], i=500)  # profile config full, fit config free
        assert client.post("/api/fit/bulk").json()["queued"] == 2
        assert q.wait_idle(TIMEOUT) and len(fake.calls) == 2

        with sf() as s:
            add_usage(s, datetime.now(UTC), fit_cfg["id"], i=500)  # fit config full
        assert q.enqueue_auto(ids) == 0
        r = client.post("/api/fit/bulk", params={"q": "nothing-matches-but-limit-first"})
        assert r.status_code == 409
        assert r.json()["code"] == "daily_limit_reached"
        assert r.json()["params"] == {"scope": "config", "config_name": "Claude"}
        r = client.post(f"/api/fit/{ids[0]}")  # single evaluations only warn
        assert r.status_code == 200 and r.json()["limit_exceeded"] is True
        assert q.wait_idle(TIMEOUT)
        # an already queued bulk job is stopped by the fit config's limit too
        n_calls = len(fake.calls)
        q.enqueue([ids[1]], lang="en", kind="bulk")
        assert q.wait_idle(TIMEOUT) and len(fake.calls) == n_calls
        with sf() as s:
            set_global(s, "tokens", 10)
        r = client.post("/api/fit/bulk")
        assert r.status_code == 409 and r.json()["params"] == {"scope": "global", "config_name": None}
    finally:
        q.shutdown()
        app.state.fit_queue = original


def test_per_config_includes_deleted_row(client, app):
    a = _post_config(client, "beta", price_in=1.0, price_out=2.0, daily_limit_kind="tokens", daily_limit_value=50)
    b = _post_config(client, "Alpha")
    gone = _post_config(client, "gone")
    unused = _post_config(client, "Zeta")
    now = datetime.now(UTC)
    with app.state.session_factory() as s:
        add_usage(s, now, a["id"], i=40, o=20)
        add_usage(s, now, b["id"], i=5)
        add_usage(s, now, gone["id"], i=7, o=1)
    before = client.get("/api/llm/usage").json()
    assert [r["name"] for r in before["per_config"]] == ["Alpha", "beta", "gone", "Zeta"]  # no deleted row yet
    assert client.delete(f"/api/llm/configs/{gone['id']}").status_code == 204
    out = client.get("/api/llm/usage").json()
    assert out["today"] == before["today"] and out["month"] == before["month"]  # totals unchanged
    rows = out["per_config"]
    assert [r["name"] for r in rows] == ["Alpha", "beta", "Zeta", None]
    by = {r["name"]: r for r in rows}
    assert by["beta"]["config_id"] == a["id"] and by["beta"]["deleted"] is False
    assert by["beta"]["today"] == {"input_tokens": 40, "output_tokens": 20, "eur": 40 / 1e6 + 40 / 1e6}
    assert by["beta"]["limit"] == {"kind": "tokens", "value": 50} and by["beta"]["limit_exceeded"] is True
    assert by["Alpha"]["limit"] == {"kind": "none", "value": None} and by["Alpha"]["limit_exceeded"] is False
    assert by["Zeta"]["config_id"] == unused["id"]
    assert by["Zeta"]["today"] == {"input_tokens": 0, "output_tokens": 0, "eur": None}
    deleted = rows[-1]
    assert deleted["config_id"] is None and deleted["deleted"] is True
    assert deleted["today"]["input_tokens"] == 7 and deleted["month"]["output_tokens"] == 1
    assert deleted["limit"] == {"kind": "none", "value": None} and deleted["limit_exceeded"] is False


def test_eur_limit_requires_prices(client):
    res = client.post("/api/llm/configs", json={
        "name": "A", "provider": "anthropic", "model": "m", "api_key": "k", "daily_limit_kind": "eur",
        "daily_limit_value": 2.5})
    assert res.status_code == 422 and res.json()["code"] == "limit_needs_prices"
    res = client.post("/api/llm/configs", json={
        "name": "A", "provider": "anthropic", "model": "m", "api_key": "k", "price_in": 1.0,
        "daily_limit_kind": "eur", "daily_limit_value": 2.5})
    assert res.status_code == 422 and res.json()["code"] == "limit_needs_prices"
    assert client.get("/api/llm/configs").json() == []
    cfg = _post_config(client, "B", price_in=1.0, price_out=2.0)
    url = f"/api/llm/configs/{cfg['id']}"
    base = {"name": "B", "provider": "anthropic", "model": "m"}
    # PUT without prices keeps the stored ones, so the EUR limit is accepted
    res = client.put(url, json={**base, "daily_limit_kind": "eur", "daily_limit_value": 3})
    assert res.status_code == 200, res.text
    assert (res.json()["price_in"], res.json()["price_out"], res.json()["daily_limit_value"]) == (1.0, 2.0, 3)
    # clearing a price while an EUR limit is set is rejected
    res = client.put(url, json={**base, "price_in": None, "price_out": 2.0, "daily_limit_kind": "eur",
                                "daily_limit_value": 3})
    assert res.status_code == 422 and res.json()["code"] == "limit_needs_prices"
    res = client.put(url, json={**base, "price_in": None, "price_out": None})  # limit kept -> still EUR
    assert res.status_code == 422 and res.json()["code"] == "limit_needs_prices"
    assert client.get(url).json()["price_in"] == 1.0


def test_limit_fields_roundtrip(client):
    cfg = _post_config(client, "A")
    assert (cfg["daily_limit_kind"], cfg["daily_limit_value"]) == ("none", None)
    cfg = _post_config(client, "B", daily_limit_kind="tokens", daily_limit_value=5000.0)
    assert (cfg["daily_limit_kind"], cfg["daily_limit_value"]) == ("tokens", 5000)
    url = f"/api/llm/configs/{cfg['id']}"
    base = {"name": "B", "provider": "anthropic", "model": "m"}
    assert client.get(url).json()["daily_limit_value"] == 5000
    res = client.put(url, json={**base, "daily_limit_kind": "tokens", "daily_limit_value": 7})
    assert res.json()["daily_limit_value"] == 7
    res = client.put(url, json={**base, "model": "m2"})  # limit fields omitted: kept
    assert (res.json()["daily_limit_kind"], res.json()["daily_limit_value"]) == ("tokens", 7)
    res = client.put(url, json={**base, "daily_limit_kind": "none", "daily_limit_value": 99})
    assert (res.json()["daily_limit_kind"], res.json()["daily_limit_value"]) == ("none", None)
    assert client.get(url).json()["daily_limit_value"] is None
    for bad in ({"daily_limit_kind": "weekly"}, {"daily_limit_kind": "tokens", "daily_limit_value": None},
                {"daily_limit_kind": "tokens", "daily_limit_value": -1},
                {"daily_limit_kind": "tokens", "daily_limit_value": 0},
                {"daily_limit_kind": "tokens", "daily_limit_value": 1.5}):
        res = client.put(url, json={**base, **bad})
        assert res.status_code == 422, bad
    assert client.get(url).json()["daily_limit_kind"] == "none"


def test_migration_0005(tmp_path):
    url = f"sqlite:///{tmp_path / 'm.db'}"
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "0004_posting_fit")
    engine = make_engine(url)
    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO llm_config (name, provider, model, thinking, supports_images, extra_body, extra_headers,"
            " is_default, created_at, updated_at) VALUES ('old', 'anthropic', 'm', 'off', 1, '{}', '{}', 1,"
            " '2026-10-24 08:00:00', '2026-10-24 08:00:00')"))
    engine.dispose()
    upgrade(url)
    engine = make_engine(url)
    with engine.connect() as conn:
        row = conn.execute(text("SELECT name, daily_limit_kind, daily_limit_value FROM llm_config")).one()
        assert tuple(row) == ("old", "none", None)
        ctx = MigrationContext.configure(conn, opts={"compare_type": True, "render_as_batch": True})
        assert compare_metadata(ctx, Base.metadata) == []
    engine.dispose()
    command.downgrade(cfg, "0004_posting_fit")
    engine = make_engine(url)
    cols = {c["name"] for c in inspect(engine).get_columns("llm_config")}
    assert "daily_limit_kind" not in cols and "daily_limit_value" not in cols
    engine.dispose()


def test_single_actions_report_config_limit_when_global_is_fine(client, app, monkeypatch):
    from app.llm.base import LLMResult, Message
    from app.llm.runner import llm_call

    fake = FakeEval()
    q = FitQueue(app.state.session_factory, evaluate=fake)
    original, app.state.fit_queue = app.state.fit_queue, q
    try:
        cfg = _post_config(client, "Claude", daily_limit_kind="tokens", daily_limit_value=100)
        assert client.put("/api/llm/purposes", json={"profile": cfg["id"], "fit": cfg["id"], "extraction": cfg["id"]}).status_code == 200
        ids = _seed_fit(app)
        sf = app.state.session_factory
        with sf() as s:
            set_global(s, "tokens", 1_000_000)  # global limit far away
            add_usage(s, datetime.now(UTC), cfg["id"], i=40)
        r = client.post(f"/api/fit/{ids[0]}")
        assert r.status_code == 200 and r.json()["limit_exceeded"] is False
        assert q.wait_idle(TIMEOUT)
        with sf() as s:
            add_usage(s, datetime.now(UTC), cfg["id"], i=100)  # config limit reached, global fine
            assert usage.limit_status(s, datetime.now(UTC), cfg["id"]) == LimitHit("config", "Claude")
        r = client.post(f"/api/fit/{ids[1]}")
        assert r.status_code == 200 and r.json()["limit_exceeded"] is True
        assert q.wait_idle(TIMEOUT)

        class _Client:
            def complete(self, system, messages, *, json_schema=None, max_tokens=4096):
                return LLMResult("ok", 1, 1, False)

        monkeypatch.setattr("app.llm.runner.make_client", lambda cfg, **_: _Client())
        result, exceeded = llm_call(sf, "profile", lambda c: ("sys", [Message("user", ["hi"])]))
        assert result.text == "ok" and exceeded is True
    finally:
        q.shutdown()
        app.state.fit_queue = original

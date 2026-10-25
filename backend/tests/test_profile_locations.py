"""Several cities per search profile (Paket B, section 4)."""
import json

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import inspect, text

from app.db import Base, make_engine
from app.db_migrate import BACKEND_DIR, upgrade
from app.models import RunTrigger
from test_runner_keywords import (  # noqa: F401  (fixtures)
    StubPool, add_profile, all_runs, make_service, pool, registry, session_factory,
)


def test_migration_0006_location_to_list(tmp_path):
    url = f"sqlite:///{tmp_path / 'm.db'}"
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "0005_llm_config_limit")
    engine = make_engine(url)
    with engine.begin() as conn:
        for name, loc in (("a", "'München'"), ("b", "'  '"), ("c", "NULL")):
            conn.execute(text(
                "INSERT INTO search_profile (name, keywords, location, enabled, plugins)"
                f" VALUES ('{name}', '[\"k\"]', {loc}, 1, '[]')"))
    engine.dispose()
    upgrade(url)
    engine = make_engine(url)
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT name, locations FROM search_profile ORDER BY name")).all()
        assert [(n, json.loads(l)) for n, l in rows] == [("a", ["München"]), ("b", []), ("c", [])]
        assert "location" not in {c["name"] for c in inspect(conn).get_columns("search_profile")}
        ctx = MigrationContext.configure(conn, opts={"compare_type": True, "render_as_batch": True})
        assert compare_metadata(ctx, Base.metadata) == []
    engine.dispose()
    command.downgrade(cfg, "0005_llm_config_limit")
    engine = make_engine(url)
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT name, location FROM search_profile ORDER BY name")).all()
        assert [tuple(r) for r in rows] == [("a", "München"), ("b", None), ("c", None)]
    engine.dispose()


def _post(client, **kw):
    return client.post("/api/profiles", json={"name": "P", "keywords": ["py"], "plugins": ["good"], **kw})


def test_locations_normalized_and_limited(client):
    res = _post(client, locations=[" München ", "münchen", "", "Augsburg"], radius_km=30)
    assert res.status_code == 200, res.text
    assert res.json()["locations"] == ["München", "Augsburg"] and res.json()["radius_km"] == 30
    assert "location" not in res.json()
    assert _post(client, locations=[f"c{i}" for i in range(21)]).status_code == 422
    assert _post(client, locations=["x" * 101]).status_code == 422
    assert _post(client, locations=["x" * 100]).status_code == 200
    no_city = _post(client, locations=[" "], radius_km=30)
    assert no_city.json()["locations"] == [] and no_city.json()["radius_km"] is None
    assert _post(client, radius_km=10).json()["radius_km"] is None


class CityPool(StubPool):
    def __init__(self, failures=None):
        super().__init__()
        self.city_failures = failures or {}
        self.pairs: list[tuple[str, str | None]] = []

    def submit(self, info, profile, settings, timeout):
        self.pairs.append((profile.keywords, profile.location))
        key = (profile.keywords, profile.location)
        if key in self.city_failures:
            from concurrent.futures import Future
            f: Future = Future()
            f.set_exception(self.city_failures[key])
            return f
        return super().submit(info, profile, settings, timeout)


def _add(session_factory, keywords, locations, radius=None):
    pid = add_profile(session_factory, keywords, ["good"])
    from app.models import SearchProfile
    with session_factory() as s:
        p = s.get(SearchProfile, pid)
        p.locations, p.radius_km = locations, radius
        s.commit()
    return pid


def test_runner_fans_out_keyword_by_city(session_factory, registry):
    stub = CityPool()
    service = make_service(session_factory, registry, stub)
    pid = _add(session_factory, ["py", "go"], ["A", "B"], 20)
    assert len(service.start_runs([pid], RunTrigger.manual)) == 1
    assert service.wait_idle(5)
    assert stub.pairs == [("py", "A"), ("py", "B"), ("go", "A"), ("go", "B")]


def test_runner_without_city_passes_none(session_factory, registry):
    stub = CityPool()
    service = make_service(session_factory, registry, stub)
    pid = _add(session_factory, ["py", "go"], [])
    service.start_runs([pid], RunTrigger.manual)
    assert service.wait_idle(5)
    assert stub.pairs == [("py", None), ("go", None)]


def test_error_text_names_city(session_factory, registry):
    stub = CityPool({("py", "A"): ValueError("boom")})
    service = make_service(session_factory, registry, stub)
    pid = _add(session_factory, ["py"], ["A", "B"])
    service.start_runs([pid], RunTrigger.manual)
    assert service.wait_idle(5)
    [run] = all_runs(session_factory)
    assert run.error == '"py" @ A: ValueError: boom'


def test_error_text_without_city_unchanged(session_factory, registry):
    stub = CityPool({("py", None): ValueError("boom")})
    service = make_service(session_factory, registry, stub)
    pid = _add(session_factory, ["py"], [])
    service.start_runs([pid], RunTrigger.manual)
    assert service.wait_idle(5)
    [run] = all_runs(session_factory)
    assert run.error == '"py": ValueError: boom'

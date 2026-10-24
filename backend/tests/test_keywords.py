import json
import sqlite3

from alembic import command
from alembic.config import Config

from app.db_migrate import BACKEND_DIR
from app.models import SearchProfile
from app.schemas.profile import normalize_keywords


def _post(client, keywords):
    return client.post("/api/profiles", json={"name": "P", "keywords": keywords, "plugins": []})


def test_normalize_keywords():
    assert normalize_keywords(["Python", " python ", "PYTHON", "", "Data Engineer"]) == ["Python", "Data Engineer"]


def test_profile_requires_keyword(client):
    for kw in ([], ["  "]):
        res = _post(client, kw)
        assert res.status_code == 422
        assert res.json()["code"] == "validation_error"
    res = client.post("/api/profiles", json={"name": "P"})
    assert res.status_code == 422


def test_profile_keyword_limits(client):
    assert _post(client, [f"k{i}" for i in range(21)]).status_code == 422
    assert _post(client, ["x" * 101]).status_code == 422
    ok = _post(client, [f"{i:02d}" + "x" * 98 for i in range(20)])
    assert ok.status_code == 200
    assert len(ok.json()["keywords"]) == 20


def test_profile_roundtrip_list(client):
    created = _post(client, ["Python", "python", "Backend"])
    assert created.status_code == 200
    got = client.get(f"/api/profiles/{created.json()['id']}")
    assert got.json()["keywords"] == ["Python", "Backend"]
    put = client.put(f"/api/profiles/{created.json()['id']}", json={"name": "P", "keywords": [" Go "]})
    assert put.json()["keywords"] == ["Go"]


def test_migration_0002_converts(tmp_path):
    db = tmp_path / "m.db"
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db}")
    command.upgrade(cfg, "0001")
    con = sqlite3.connect(db)
    for name, kw in (("a", "Python, Data Engineer"), ("b", ""), ("c", None), ("d", " , ,x,, ")):
        con.execute(
            "INSERT INTO search_profile (name, keywords, enabled, plugins) VALUES (?, ?, 1, '[]')", (name, kw)
        )
    con.commit()
    con.close()

    command.upgrade(cfg, "head")
    con = sqlite3.connect(db)
    rows = {n: json.loads(k) for n, k in con.execute("SELECT name, keywords FROM search_profile")}
    con.close()
    assert rows == {"a": ["Python", "Data Engineer"], "b": [], "c": [], "d": ["x"]}

    command.downgrade(cfg, "0001")
    con = sqlite3.connect(db)
    back = dict(con.execute("SELECT name, keywords FROM search_profile"))
    con.close()
    assert back == {"a": "Python, Data Engineer", "b": "", "c": "", "d": "x"}


def test_duplicates_collapse_before_limit(client):
    words = [f"k{i}" for i in range(20)] + ["K0"]
    res = _post(client, words)
    assert res.status_code == 200
    assert res.json()["keywords"] == words[:20]


def test_empty_keywords_profile_serializes(client, app):
    with app.state.session_factory() as s:
        p = SearchProfile(name="legacy", keywords=[], plugins=[])
        s.add(p)
        s.commit()
        pid = p.id
    one = client.get(f"/api/profiles/{pid}")
    assert one.status_code == 200 and one.json()["keywords"] == []
    lst = client.get("/api/profiles")
    assert lst.status_code == 200 and lst.json()[0]["keywords"] == []

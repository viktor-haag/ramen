from pathlib import Path

from app.config import Settings
from app.errors import ConflictError
from app.version import __version__


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "version": __version__}


def test_settings_from_env(monkeypatch):
    monkeypatch.setenv("JOBTRACKER_PLUGIN_DIRS", "a;b")
    assert Settings().plugin_dirs == [Path("a"), Path("b")]


def test_error_shape(app):
    from fastapi.testclient import TestClient

    @app.get("/api/_boom")
    def boom():
        raise ConflictError("x_code", "X", {"a": 1})

    with TestClient(app) as c:
        r = c.get("/api/_boom")
    assert r.status_code == 409
    assert r.json() == {"code": "x_code", "params": {"a": 1}, "detail": "X"}


def test_validation_error_shape(app):
    from fastapi.testclient import TestClient

    @app.get("/api/_num")
    def num(n: int):
        return n

    with TestClient(app) as c:
        r = c.get("/api/_num?n=abc")
    assert r.status_code == 422
    body = r.json()
    assert body["code"] == "validation_error"
    assert body["params"]["errors"]


def test_default_dirs_resolve_relative_to_repo(monkeypatch, tmp_path):
    monkeypatch.delenv("JOBTRACKER_PLUGIN_DIRS", raising=False)
    monkeypatch.delenv("JOBTRACKER_DATA_DIR", raising=False)
    monkeypatch.chdir(tmp_path)  # defaults must not depend on the cwd
    s = Settings()
    repo = Path(__file__).resolve().parents[2]
    assert s.plugin_dirs == [repo / "plugins"]
    assert (repo / "plugins" / "arbeitsagentur").is_dir()
    assert s.data_dir == repo / "data"


def test_missing_plugin_dir_logs_warning(tmp_path, caplog):
    import logging

    from app.main import create_app

    with caplog.at_level(logging.INFO, logger="app.main"):
        create_app(Settings(data_dir=tmp_path, plugin_dirs=[tmp_path / "nope"]))
    assert any("nope" in r.getMessage() and r.levelno == logging.WARNING for r in caplog.records)
    assert any("loaded plugins" in r.getMessage() for r in caplog.records)

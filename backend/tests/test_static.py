from fastapi.testclient import TestClient

from app.config import Settings
from app.main import _static_file, create_app
from app.version import __version__


def _client(tmp_path, dist):
    settings = Settings(data_dir=tmp_path / "data", plugin_dirs=[], frontend_dist=dist, update_check=False)
    return TestClient(create_app(settings))


def test_spa_fallback(tmp_path):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>spa</html>", encoding="utf-8")
    (dist / "assets" / "app.js").write_text("console.log(1)", encoding="utf-8")
    with _client(tmp_path, dist) as client:
        r = client.get("/feed")
        assert r.status_code == 200
        assert r.text == "<html>spa</html>"
        assert client.get("/").text == "<html>spa</html>"
        assert client.get("/assets/app.js").text == "console.log(1)"
        assert client.get("/assets/missing.js").status_code == 404
        r = client.get("/api/unknown")
        assert r.status_code == 404
        assert r.headers["content-type"].startswith("application/json")
        assert r.json()["code"] == "not_found"
        for method in ("post", "put", "patch", "delete"):
            r = getattr(client, method)("/api/unknown")
            assert r.status_code == 404, method
            assert r.json()["code"] == "not_found"
        assert client.get("/api/health").json() == {"status": "ok", "version": __version__}


def test_no_frontend_dist_means_no_fallback(tmp_path):
    with _client(tmp_path, None) as client:
        assert client.get("/feed").status_code == 404


def test_root_file_served_and_traversal_blocked(tmp_path):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("idx", encoding="utf-8")
    (dist / "favicon.svg").write_text("<svg/>", encoding="utf-8")
    (tmp_path / "secret.txt").write_text("secret", encoding="utf-8")
    assert _static_file(dist.resolve(), "favicon.svg") == (dist / "favicon.svg").resolve()
    assert _static_file(dist.resolve(), "../secret.txt") is None  # exercises the guard directly
    assert _static_file(dist.resolve(), "a\0b") is None
    with _client(tmp_path, dist) as client:
        assert client.get("/favicon.svg").text == "<svg/>"
        assert client.get("/%2e%2e/secret.txt").text == "idx"
        assert client.get("/foo%00bar").text == "idx"


def test_api_unknown_404_without_frontend(tmp_path):
    with _client(tmp_path, None) as client:
        r = client.post("/api/unknown")
        assert r.status_code == 404
        assert r.json()["code"] == "not_found"

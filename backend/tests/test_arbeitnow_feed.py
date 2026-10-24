import json
import re
import sqlite3
import subprocess
import threading
import sys
from pathlib import Path

import httpx
import pytest
import respx

from app.plugins import http as plugin_http
from app.plugins.http import make_client
from app.plugins.loader import load_extractor

REPO = Path(__file__).resolve().parents[2]
PLUGIN_DIR = REPO / "plugins" / "arbeitnow"
FIXTURES = PLUGIN_DIR / "fixtures"
PAGES = {
    1: json.loads((FIXTURES / "page1.json").read_text(encoding="utf-8")),
    2: json.loads((FIXTURES / "page2.json").read_text(encoding="utf-8")),
}


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(plugin_http, "_sleep", lambda s: None)


@pytest.fixture(scope="module")
def extractor():
    return load_extractor(str(PLUGIN_DIR / "__init__.py"), "ArbeitnowExtractor")


@pytest.fixture(scope="module")
def feed(extractor):
    return sys.modules["jobtracker_plugin_arbeitnow.feed"]


@pytest.fixture(scope="module")
def cache_mod(extractor):
    return sys.modules["jobtracker_plugin_arbeitnow.cache"]


def _paged(pages):
    def side_effect(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params.get("page", "1"))
        return httpx.Response(200, json=pages.get(page, {"data": [], "links": {"next": None}}))

    return side_effect


# --- feed download ---------------------------------------------------------------------


@respx.mock
def test_iter_feed_stops_at_last_page(feed):
    route = respx.get(feed.FEED_URL).mock(side_effect=_paged(PAGES))
    with make_client() as client:
        items = list(feed.iter_feed(client, 30))
    assert len(items) == 6 and route.call_count == 2


@respx.mock
def test_iter_feed_respects_max_pages(feed):
    route = respx.get(feed.FEED_URL).mock(side_effect=_paged(PAGES))
    with make_client() as client:
        items = list(feed.iter_feed(client, 1))
    assert len(items) == 3 and route.call_count == 1


@respx.mock
def test_iter_feed_stops_on_empty_data(feed):
    pages = {1: PAGES[1], 2: {"data": [], "links": {"next": "x"}}}
    route = respx.get(feed.FEED_URL).mock(side_effect=_paged(pages))
    with make_client() as client:
        items = list(feed.iter_feed(client, 30))
    assert len(items) == 3 and route.call_count == 2


@respx.mock
def test_iter_feed_http_error_raises(feed):
    def side_effect(request):
        if request.url.params.get("page") == "2":
            return httpx.Response(500)
        return httpx.Response(200, json=PAGES[1])

    respx.get(feed.FEED_URL).mock(side_effect=side_effect)
    with make_client(retries=0) as client:
        with pytest.raises(httpx.HTTPStatusError):
            list(feed.iter_feed(client, 30))


# --- cache -----------------------------------------------------------------------------


def _item(slug, title="Some job", tags=(), description=None):
    return {"slug": slug, "title": title, "tags": list(tags), "description": description}


class _Fetch:
    def __init__(self, items):
        self.items = items
        self.calls = 0

    def __call__(self):
        self.calls += 1
        return list(self.items)


@pytest.fixture
def clock(monkeypatch, cache_mod):
    state = {"now": 1_000_000.0}
    monkeypatch.setattr(cache_mod, "_now", lambda: state["now"])
    return state


def _slugs(cache, kw="python", desc=True):
    return [item["slug"] for item, _ in cache.matching(re.compile(kw, re.I), desc)]


def test_fresh_cache_is_reused(cache_mod, clock, tmp_path):
    fetch = _Fetch([_item("a", "Python Dev")])
    with cache_mod.Cache(tmp_path / "c.sqlite") as cache:
        cache.ensure_feed(60, fetch)
        cache.ensure_feed(60, fetch)
        assert fetch.calls == 1
        clock["now"] += 61
        cache.ensure_feed(60, fetch)
        assert fetch.calls == 2


def test_max_age_zero_always_fetches(cache_mod, clock, tmp_path):
    fetch = _Fetch([_item("a", "Python Dev")])
    with cache_mod.Cache(tmp_path / "c.sqlite") as cache:
        cache.ensure_feed(0, fetch)
        cache.ensure_feed(0, fetch)
    assert fetch.calls == 2


def test_matching_title_tags_and_description(cache_mod, clock, tmp_path):
    items = [
        _item("a", "Python Dev"),
        _item("b", "Dev", tags=["Python"]),
        _item("c", "Dev", description="<p>We use Python</p>"),
        _item("d", "Java Dev", description="<p>Java</p>"),
    ]
    with cache_mod.Cache(tmp_path / "c.sqlite") as cache:
        cache.ensure_feed(60, _Fetch(items))
        with_desc = cache.matching(re.compile("python", re.I), True)
        assert [i["slug"] for i, _ in with_desc] == ["a", "b", "c"]
        assert with_desc[2][1] == "We use Python"
        assert with_desc[2][0]["description"] == "<p>We use Python</p>"
        assert _slugs(cache, desc=False) == ["a", "b"]


def test_duplicate_slugs_first_wins(cache_mod, clock, tmp_path):
    items = [_item("a", "Python first"), _item("a", "Python second")]
    with cache_mod.Cache(tmp_path / "c.sqlite") as cache:
        cache.ensure_feed(60, _Fetch(items))
        hits = cache.matching(re.compile("python", re.I), False)
    assert [i["title"] for i, _ in hits] == ["Python first"]


def test_refresh_replaces_old_items(cache_mod, clock, tmp_path):
    with cache_mod.Cache(tmp_path / "c.sqlite") as cache:
        cache.ensure_feed(60, _Fetch([_item("a", "Python Dev")]))
        clock["now"] += 61
        cache.ensure_feed(60, _Fetch([_item("d", "Java Dev")]))
        assert _slugs(cache) == []
        assert _slugs(cache, "java") == ["d"]


def test_fetch_error_keeps_old_cache(cache_mod, clock, tmp_path):
    def broken():
        raise httpx.ConnectError("down")

    with cache_mod.Cache(tmp_path / "c.sqlite") as cache:
        with pytest.raises(httpx.ConnectError):
            cache.ensure_feed(60, broken)  # empty cache -> propagates
        cache.ensure_feed(60, _Fetch([_item("a", "Python Dev")]))
        clock["now"] += 61
        cache.ensure_feed(60, broken)  # stale cache -> swallowed
        assert _slugs(cache) == ["a"]


def test_empty_refresh_keeps_old_feed(cache_mod, clock, tmp_path):
    with cache_mod.Cache(tmp_path / "c.sqlite") as cache:
        cache.ensure_feed(60, _Fetch([_item("a", "Python Dev")]))
        old = cache._fetched_at()
        clock["now"] += 61
        cache.ensure_feed(60, _Fetch([]))
        assert _slugs(cache) == ["a"]
        assert cache._fetched_at() == old  # still stale: retried next time
        assert not cache._conn.in_transaction


def test_empty_first_load_is_stored(cache_mod, clock, tmp_path):
    fetch = _Fetch([])
    with cache_mod.Cache(tmp_path / "c.sqlite") as cache:
        cache.ensure_feed(60, fetch)
        cache.ensure_feed(60, fetch)
        assert fetch.calls == 1
        assert cache._fetched_at() is not None
        assert _slugs(cache) == []


def test_partial_fetch_error_rolls_back(cache_mod, clock, tmp_path):
    def partial():
        yield _item("x", "Python partial")
        raise httpx.ConnectError("cut off")

    path = tmp_path / "c.sqlite"
    with cache_mod.Cache(path) as cache:
        cache.ensure_feed(60, _Fetch([_item("a", "Python Dev")]))
        clock["now"] += 61
        cache.ensure_feed(60, partial)
        assert _slugs(cache) == ["a"]
        assert not cache._conn.in_transaction
    # an empty cache with a partial fetch leaves nothing behind and no open transaction
    with cache_mod.Cache(tmp_path / "d.sqlite") as cache:
        with pytest.raises(httpx.ConnectError):
            cache.ensure_feed(60, partial)
        assert not cache._conn.in_transaction
        assert _slugs(cache) == []


def test_broken_cache_file_is_recreated(cache_mod, clock, tmp_path):
    path = tmp_path / "c.sqlite"
    path.write_bytes(b"not a database")
    with cache_mod.Cache(path) as cache:
        cache.ensure_feed(60, _Fetch([_item("a", "Python Dev")]))
        assert _slugs(cache) == ["a"]

    other = tmp_path / "o.sqlite"
    conn = sqlite3.connect(other)
    conn.execute("CREATE TABLE foreign_table (x)")
    conn.execute("PRAGMA user_version = 0")
    conn.commit()
    conn.close()
    with cache_mod.Cache(other) as cache:
        cache.ensure_feed(60, _Fetch([_item("a", "Python Dev")]))
        assert _slugs(cache) == ["a"]
    conn = sqlite3.connect(other)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == cache_mod.SCHEMA_VERSION
    assert conn.execute("SELECT name FROM sqlite_master WHERE name = 'foreign_table'").fetchone() is None
    conn.close()


CODE = """
import sys, time
from pathlib import Path
from app.plugins.loader import load_extractor
load_extractor({init!r}, 'ArbeitnowExtractor')
Cache = sys.modules['jobtracker_plugin_arbeitnow.cache'].Cache
import re
cache_path, counter_path = sys.argv[1], sys.argv[2]

def fake():
    with open(counter_path, 'a') as f:
        f.write('x\\n')
    time.sleep(2)
    return [{{'slug': 'a', 'title': 'Python A', 'tags': []}}, {{'slug': 'b', 'title': 'Python B', 'tags': []}}]

with Cache(Path(cache_path)) as cache:
    cache.ensure_feed(60, fake)
    print(len(cache.matching(re.compile('python', re.I), False)))
"""


def test_concurrent_processes_fetch_once(tmp_path):
    cache_path = tmp_path / "c.sqlite"
    counter = tmp_path / "counter.txt"
    code = CODE.format(init=str(PLUGIN_DIR / "__init__.py"))
    procs = [
        subprocess.Popen(
            [sys.executable, "-c", code, str(cache_path), str(counter)],
            cwd="/", stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        for _ in range(2)
    ]
    results = []
    for p in procs:
        try:
            out, err = p.communicate(timeout=120)
        except subprocess.TimeoutExpired:
            p.kill()
            raise
        results.append((p.returncode, out.strip(), err))
    for rc, out, err in results:
        assert rc == 0, err
        assert out == "2"
    assert len(counter.read_text().splitlines()) == 1


def test_items_without_slug_are_skipped(cache_mod, clock, tmp_path):
    items = [{"title": "Python none"}, {"slug": "", "title": "Python empty"}, {"slug": 5, "title": "Python int"},
             _item("a", "Python ok")]
    with cache_mod.Cache(tmp_path / "c.sqlite") as cache:
        cache.ensure_feed(60, _Fetch(items))
        assert _slugs(cache) == ["a"]


def test_future_fetched_at_is_stale(cache_mod, clock, tmp_path):
    fetch = _Fetch([_item("a", "Python Dev")])
    with cache_mod.Cache(tmp_path / "c.sqlite") as cache:
        cache.ensure_feed(60, fetch)
        clock["now"] -= 3600  # clock went backwards
        cache.ensure_feed(60, fetch)
    assert fetch.calls == 2


def _locked_valid_cache(cache_mod, tmp_path):
    path = tmp_path / "c.sqlite"
    with cache_mod.Cache(path) as cache:
        cache.ensure_feed(60, _Fetch([_item("a", "Python Dev")]))
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=DELETE")  # back to the cold-start state (no WAL yet)
    conn.close()
    holder = sqlite3.connect(path, isolation_level=None)
    holder.execute("BEGIN EXCLUSIVE")
    return path, holder


def test_locked_file_is_not_deleted_and_open_waits(cache_mod, tmp_path):
    path, holder = _locked_valid_cache(cache_mod, tmp_path)
    inode = path.stat().st_ino
    box = {}

    def open_cache():
        try:
            with cache_mod.Cache(path, busy_timeout=20) as cache:  # connection lives in this thread
                box["slugs"] = _slugs(cache)
        except Exception as exc:  # noqa: BLE001
            box["error"] = exc

    t = threading.Thread(target=open_cache)
    t.start()
    t.join(0.7)
    assert t.is_alive()  # still waiting for the lock
    holder.execute("COMMIT")
    holder.close()
    t.join(30)
    assert "error" not in box, box.get("error")
    assert box["slugs"] == ["a"]  # old content preserved
    assert path.stat().st_ino == inode


def test_lock_timeout_propagates_without_deleting(cache_mod, tmp_path):
    path, holder = _locked_valid_cache(cache_mod, tmp_path)
    inode = path.stat().st_ino
    with pytest.raises(sqlite3.OperationalError):
        cache_mod.Cache(path, busy_timeout=0.3)
    holder.execute("COMMIT")
    holder.close()
    assert path.stat().st_ino == inode
    with cache_mod.Cache(path) as cache:
        assert _slugs(cache) == ["a"]

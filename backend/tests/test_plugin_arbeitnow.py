import sys
from pathlib import Path

import httpx
import pytest
import respx

from app.plugins import http as plugin_http
from app.plugins.base import JobPosting, SearchProfileDTO
from app.plugins.http import make_client
from app.plugins.loader import load_extractor
from app.runner.pool import execute_search

REPO = Path(__file__).resolve().parents[2]
PLUGIN_DIR = REPO / "plugins" / "arbeitnow"

PLACES = {
    "münchen": (48.137, 11.575),
    "gilching": (48.109, 11.293),
    "berlin": (52.52, 13.40),
    "london": (51.5, -0.12),
}


@pytest.fixture(autouse=True)
def _env(monkeypatch, tmp_path):
    monkeypatch.setenv("JOBTRACKER_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(plugin_http, "_sleep", lambda s: None)


@pytest.fixture(scope="module")
def extractor():
    return load_extractor(str(PLUGIN_DIR / "__init__.py"), "ArbeitnowExtractor")


@pytest.fixture(scope="module")
def mods(extractor):
    pkg = "jobtracker_plugin_arbeitnow"
    return {n: sys.modules[f"{pkg}.{n}"] for n in ("cache", "geo", "feed")} | {"init": sys.modules[pkg]}


@pytest.fixture(autouse=True)
def _no_cache_sleep(monkeypatch, mods):
    monkeypatch.setattr(mods["cache"], "_sleep", lambda s: None)


def _item(slug, location, title="Python Dev", remote=False, description="<p>text</p>"):
    return {
        "slug": slug, "company_name": "ACME", "title": title, "description": description,
        "remote": remote, "url": f"https://www.arbeitnow.com/jobs/{slug}", "tags": [],
        "job_types": [], "location": location, "created_at": 1761300000,
    }


ITEMS = [
    _item("ber", "Berlin"),
    _item("gil", "Gilching"),
    _item("rem", "London", remote=True),
    _item("none", ""),
    _item("java", "Hamburg", title="Java Dev"),
]


def _mock(mods, items=None):
    items = ITEMS if items is None else items
    feed = respx.get(mods["feed"].FEED_URL).mock(
        return_value=httpx.Response(200, json={"data": items, "links": {"next": None}})
    )

    def nominatim(request):
        coords = PLACES.get(request.url.params["q"].casefold())
        if coords is None:
            return httpx.Response(200, json=[])
        return httpx.Response(200, json=[{"lat": str(coords[0]), "lon": str(coords[1])}])

    geo = respx.get(mods["geo"].NOMINATIM_URL).mock(side_effect=nominatim)
    return feed, geo


def _slugs(postings):
    return {p.external_id for p in postings}


def _asked(geo_route):
    return [c.request.url.params["q"] for c in geo_route.calls]


@respx.mock
def test_search_radius_filter(extractor, mods):
    feed, geo = _mock(mods)
    profile = SearchProfileDTO(keywords="python", location="München", radius_km=30)
    result = extractor.search(profile, mods["init"].ArbeitnowSettings())
    assert _slugs(result) == {"gil", "rem"}
    by_slug = {p.external_id: p for p in result}
    assert by_slug["gil"].lat is not None and by_slug["gil"].lon is not None
    assert by_slug["rem"].location == "London"
    asked = _asked(geo)
    assert "Gilching" in asked and "München" in asked
    assert all(q not in ("London",) for q in asked)
    assert asked.count("Gilching") == 1
    assert "Hamburg" not in asked  # keyword filtering happens before geocoding


@respx.mock
def test_geocoding_outage_trips_breaker_and_keeps_remote(extractor, mods):
    items = [_item(f"p{i}", f"Place{i}") for i in range(5)] + [_item("rem", "London", remote=True)]
    respx.get(mods["feed"].FEED_URL).mock(
        return_value=httpx.Response(200, json={"data": items, "links": {"next": None}})
    )
    calls = []

    def nominatim(request):
        calls.append(request.url.params["q"])
        if request.url.params["q"] == "München":
            return httpx.Response(200, json=[{"lat": "48.137", "lon": "11.575"}])
        raise httpx.ReadTimeout("slow")

    respx.get(mods["geo"].NOMINATIM_URL).mock(side_effect=nominatim)
    profile = SearchProfileDTO(keywords="python", location="München", radius_km=30)
    result = extractor.search(profile, mods["init"].ArbeitnowSettings())
    assert _slugs(result) == {"rem"}
    assert calls == ["München", "Place0"]  # one failed posting lookup, then no more network


@respx.mock
def test_default_radius_used(extractor, mods):
    _mock(mods)
    profile = SearchProfileDTO(keywords="python", location="München")
    small = mods["init"].ArbeitnowSettings(default_radius_km=10)
    assert "gil" not in _slugs(extractor.search(profile, small))
    large = mods["init"].ArbeitnowSettings(default_radius_km=25)
    assert "gil" in _slugs(extractor.search(profile, large))


@respx.mock
def test_no_location_returns_all_keyword_hits(extractor, mods):
    from app.config import Settings

    _, geo = _mock(mods)
    path = mods["init"].cache_path()
    assert path == Settings().data_dir / "plugin_cache" / "arbeitnow.sqlite"
    with mods["cache"].Cache(path) as cache:
        cache.geocode_put(mods["geo"].place_key("Berlin"), (52.52, 13.40))
    result = extractor.search(SearchProfileDTO(keywords="python"), mods["init"].ArbeitnowSettings())
    assert _slugs(result) == {"ber", "gil", "rem", "none"}
    assert geo.call_count == 0
    by_slug = {p.external_id: p for p in result}
    assert by_slug["ber"].lat == 52.52
    assert by_slug["gil"].lat is None and by_slug["rem"].lat is None and by_slug["none"].lat is None


@respx.mock
def test_unknown_profile_location_fails(extractor, mods):
    _mock(mods)
    profile = SearchProfileDTO(keywords="python", location="Atlantis")
    with pytest.raises(ValueError, match="location not found: Atlantis"):
        extractor.search(profile, mods["init"].ArbeitnowSettings())


@respx.mock
def test_budget_drops_unresolved_for_this_run(extractor, mods):
    _mock(mods)
    profile = SearchProfileDTO(keywords="python", location="München", radius_km=30)
    result = extractor.search(profile, mods["init"].ArbeitnowSettings(max_new_geocodes=0))
    assert _slugs(result) == {"rem"}
    result = extractor.search(profile, mods["init"].ArbeitnowSettings(max_new_geocodes=60))
    assert _slugs(result) == {"gil", "rem"}


@respx.mock
def test_feed_loaded_once_per_cache_window(extractor, mods):
    feed, _ = _mock(mods)
    settings = mods["init"].ArbeitnowSettings()
    extractor.search(SearchProfileDTO(keywords="python"), settings)
    extractor.search(SearchProfileDTO(keywords="java"), settings)
    assert feed.call_count == 1


@respx.mock
def test_search_description_setting(extractor, mods):
    _mock(mods, [_item("d1", "Berlin", title="Dev", description="<p>We use Python daily</p>")])
    profile = SearchProfileDTO(keywords="python")
    assert _slugs(extractor.search(profile, mods["init"].ArbeitnowSettings())) == {"d1"}
    off = mods["init"].ArbeitnowSettings(search_description=False)
    assert extractor.search(profile, off) == []


@respx.mock
def test_blank_keywords_return_nothing_without_network(extractor, mods):
    feed, geo = _mock(mods)
    assert extractor.search(SearchProfileDTO(keywords="   "), mods["init"].ArbeitnowSettings()) == []
    assert feed.call_count == 0 and geo.call_count == 0


@respx.mock
def test_runs_in_worker_entrypoint(mods):
    _mock(mods)
    profile = SearchProfileDTO(keywords="python", location="München", radius_km=30)
    out = execute_search(str(PLUGIN_DIR / "__init__.py"), "ArbeitnowExtractor", profile.model_dump(), {})
    postings = [JobPosting.model_validate(d) for d in out]
    assert {p.external_id for p in postings} == {"gil", "rem"}


@pytest.mark.live
def test_live_feed_page(mods):
    with make_client() as client:
        items = list(mods["feed"].iter_feed(client, 1))
    assert len(items) >= 1
    for key in ("slug", "title", "url", "created_at"):
        assert items[0].get(key)

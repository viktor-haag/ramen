import sys
from pathlib import Path

import httpx
import pytest
import respx

from app.plugins.http import make_client
from app.plugins.loader import load_extractor

REPO = Path(__file__).resolve().parents[2]
PLUGIN_DIR = REPO / "plugins" / "arbeitnow"


@pytest.fixture(scope="module")
def extractor():
    return load_extractor(str(PLUGIN_DIR / "__init__.py"), "ArbeitnowExtractor")


@pytest.fixture(scope="module")
def geo(extractor):
    return sys.modules["jobtracker_plugin_arbeitnow.geo"]


@pytest.fixture(scope="module")
def cache_mod(extractor):
    return sys.modules["jobtracker_plugin_arbeitnow.cache"]


@pytest.fixture
def sleeps(monkeypatch, cache_mod):
    calls: list[float] = []
    monkeypatch.setattr(cache_mod, "_sleep", calls.append)
    return calls


@pytest.fixture
def client():
    with make_client(retries=0, timeout=5) as c:
        yield c


def _geocoder(geo, cache_mod, tmp_path, client, budget=60):
    return geo.Geocoder(cache_mod.Cache(tmp_path / "c.sqlite"), client, budget)


def _hit(lat="48.1", lon="11.3"):
    return httpx.Response(200, json=[{"lat": lat, "lon": lon}])


@respx.mock
def test_lookup_caches_hit_and_miss(geo, cache_mod, tmp_path, client, sleeps):
    def answer(request):
        return _hit() if request.url.params["q"] == "Gilching" else httpx.Response(200, json=[])

    route = respx.get(geo.NOMINATIM_URL).mock(side_effect=answer)
    g = _geocoder(geo, cache_mod, tmp_path, client)
    assert g.lookup("Gilching") == (48.1, 11.3)
    assert g.lookup("Nowhere") is None
    assert route.call_count == 2
    assert g.lookup("Gilching") == (48.1, 11.3)
    assert g.lookup("Nowhere") is None
    assert route.call_count == 2
    params = route.calls[0].request.url.params
    assert params["format"] == "jsonv2" and params["limit"] == "1" and params["q"] == "Gilching"
    assert "countrycodes" not in params
    assert g.cached("Gilching") == (48.1, 11.3)


@respx.mock
def test_cache_survives_new_instances(geo, cache_mod, tmp_path, client, sleeps):
    route = respx.get(geo.NOMINATIM_URL).mock(return_value=_hit())
    _geocoder(geo, cache_mod, tmp_path, client).lookup("Gilching")
    assert route.call_count == 1
    assert _geocoder(geo, cache_mod, tmp_path, client).lookup("Gilching") == (48.1, 11.3)
    assert route.call_count == 1


@respx.mock
def test_case_and_whitespace_share_entry(geo, cache_mod, tmp_path, client, sleeps):
    route = respx.get(geo.NOMINATIM_URL).mock(return_value=_hit("48.137", "11.575"))
    g = _geocoder(geo, cache_mod, tmp_path, client)
    assert g.lookup("MÜNCHEN ") == (48.137, 11.575)
    assert g.lookup("München") == (48.137, 11.575)
    assert route.call_count == 1


@respx.mock
@pytest.mark.parametrize("place", [None, "", "  ", "Remote job", "ANYWHERE", "remote"])
def test_placeless_never_requested(geo, cache_mod, tmp_path, client, sleeps, place):
    route = respx.get(geo.NOMINATIM_URL).mock(return_value=_hit())
    g = _geocoder(geo, cache_mod, tmp_path, client)
    assert g.lookup(place) is None
    assert g.cached(place) is None
    assert route.call_count == 0


@respx.mock
def test_transient_failures_not_cached(geo, cache_mod, tmp_path, client, sleeps):
    bad = [
        httpx.Response(500),
        httpx.Response(200, json={"error": "x"}),
        httpx.Response(200, json=[{"lon": "1"}]),
        httpx.Response(200, text="not json"),
        httpx.Response(200, json=[{"lat": "abc", "lon": "1"}]),
    ]
    route = respx.get(geo.NOMINATIM_URL)
    for response in bad:
        g = _geocoder(geo, cache_mod, tmp_path, client)  # a failure trips the breaker: one instance each
        route.mock(return_value=response)
        assert g.lookup("Gilching") is None
        assert g.cached("Gilching") is None
    g = _geocoder(geo, cache_mod, tmp_path, client)
    before = route.call_count
    route.mock(return_value=_hit())
    assert g.lookup("Gilching") == (48.1, 11.3)
    assert route.call_count == before + 1
    assert g.lookup("Gilching") == (48.1, 11.3)
    assert route.call_count == before + 1


@respx.mock
def test_network_error_not_cached(geo, cache_mod, tmp_path, client, sleeps):
    route = respx.get(geo.NOMINATIM_URL).mock(side_effect=httpx.ConnectError("down"))
    g = _geocoder(geo, cache_mod, tmp_path, client)
    assert g.lookup("Gilching") is None
    route.mock(return_value=_hit())
    g = _geocoder(geo, cache_mod, tmp_path, client)  # new instance: the old one is tripped
    assert g.lookup("Gilching") == (48.1, 11.3)


@respx.mock
def test_budget_limits_new_lookups(geo, cache_mod, tmp_path, client, sleeps):
    route = respx.get(geo.NOMINATIM_URL).mock(return_value=_hit())
    g = _geocoder(geo, cache_mod, tmp_path, client, budget=2)
    assert g.lookup("A") is not None
    assert g.lookup("B") is not None
    assert g.lookup("C") is None
    assert route.call_count == 2
    assert g.lookup("A") == (48.1, 11.3)  # cached place still resolves
    assert route.call_count == 2
    assert g.lookup("C", use_budget=False) == (48.1, 11.3)  # ignores the spent budget
    assert route.call_count == 3
    g2 = _geocoder(geo, cache_mod, tmp_path / "other", client, budget=1)
    assert g2.lookup("X", use_budget=False) is not None  # does not consume
    assert g2.lookup("Y") is not None
    assert g2.lookup("Z") is None


@respx.mock
def test_failed_attempts_consume_budget(geo, cache_mod, tmp_path, client, sleeps):
    route = respx.get(geo.NOMINATIM_URL).mock(return_value=httpx.Response(500))
    g = _geocoder(geo, cache_mod, tmp_path, client, budget=1)
    assert g.lookup("A") is None
    assert g.lookup("B") is None
    assert route.call_count == 1


@respx.mock
def test_circuit_breaker_stops_new_lookups_after_failure(geo, cache_mod, tmp_path, client, sleeps):
    route = respx.get(geo.NOMINATIM_URL).mock(side_effect=httpx.ReadTimeout("slow"))
    g = _geocoder(geo, cache_mod, tmp_path, client)
    g.cache.geocode_put(geo.place_key("Cached"), (1.0, 2.0))
    assert g.lookup("A") is None
    assert route.call_count == 1
    assert g.lookup("B") is None
    assert g.lookup("C", use_budget=False) is None  # the profile lookup stops too
    assert route.call_count == 1
    assert g.lookup("Cached") == (1.0, 2.0)  # cached reads still work
    assert _geocoder(geo, cache_mod, tmp_path, client).budget == 60  # a new instance starts untripped


@respx.mock
def test_cached_never_requests(geo, cache_mod, tmp_path, client, sleeps):
    route = respx.get(geo.NOMINATIM_URL).mock(return_value=_hit())
    g = _geocoder(geo, cache_mod, tmp_path, client)
    assert g.cached("Gilching") is None
    assert route.call_count == 0


@respx.mock
def test_rate_slot_spaces_requests(geo, cache_mod, tmp_path, client, monkeypatch):
    sleeps: list[float] = []
    monkeypatch.setattr(cache_mod, "_sleep", sleeps.append)
    monkeypatch.setattr(cache_mod, "_now", lambda: 1_000_000.0)
    respx.get(geo.NOMINATIM_URL).mock(return_value=_hit())
    g = _geocoder(geo, cache_mod, tmp_path, client)
    g.lookup("A")
    assert sleeps == []
    g.lookup("B")
    assert sleeps == [pytest.approx(1.0)]


def test_haversine_km(geo):
    assert geo.haversine_km(48.137, 11.575, 48.109, 11.293) == pytest.approx(21, abs=1)

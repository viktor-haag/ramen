import base64
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
import respx

from app.plugins import http as plugin_http
from app.plugins.base import Capability, SearchProfileDTO
from app.plugins.loader import discover_plugins, load_extractor

REPO = Path(__file__).resolve().parents[2]
PLUGIN_DIR = REPO / "plugins" / "arbeitsagentur"
FIXTURES = PLUGIN_DIR / "fixtures"
BASE = "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc"
JOBS_URL = f"{BASE}/v6/jobs"
DETAIL_URL = f"{BASE}/v4/jobdetails/"


def _fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(plugin_http, "_sleep", lambda s: None)


NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"


@pytest.fixture
def extractor():
    return load_extractor(str(PLUGIN_DIR / "__init__.py"), "ArbeitsagenturExtractor")


@pytest.fixture(autouse=True)
def _clean_location_cache(extractor):
    module = sys.modules[type(extractor).__module__]
    module._reset_location_cache()
    yield
    module._reset_location_cache()


@pytest.fixture
def profile():
    return SearchProfileDTO(keywords="python", location="München", radius_km=25)


def _settings(extractor, **kw):
    kw.setdefault("fetch_details_for_new", False)
    kw.setdefault("normalize_location", False)  # keeps unrelated tests free of Nominatim calls
    return extractor.settings_schema(**kw)


def _paged(pages: dict[int, dict]):
    """respx side effect serving fixture pages by `page` query param (empty page otherwise)."""

    def handler(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params["page"])
        return httpx.Response(200, json=pages.get(page, {"maxErgebnisse": 344, "ergebnisliste": []}))

    return handler


PAGES = {1: _fixture("search_page1.json"), 2: _fixture("search_page2.json")}


def test_plugin_metadata_and_discovery(extractor):
    assert extractor.name == "arbeitsagentur"
    assert extractor.display_name == "Bundesagentur für Arbeit"
    assert extractor.capabilities == {Capability.SEARCH, Capability.FETCH}
    infos = discover_plugins([REPO / "plugins"])
    assert infos["arbeitsagentur"].error is None
    schema = extractor.settings_schema.model_json_schema()
    for prop in schema["properties"].values():
        assert prop["title"] and prop["description"]


@respx.mock
def test_search_maps_fields(extractor, profile):
    respx.get(JOBS_URL).mock(side_effect=_paged(PAGES))
    postings = extractor.search(profile, _settings(extractor, max_results=3, page_size=3))
    assert len(postings) == 3
    p = postings[0]
    item = PAGES[1]["ergebnisliste"][0]
    assert p.source == "arbeitsagentur"
    assert p.external_id == item["referenznummer"] == "10000-1183300826-S"
    assert p.url == "https://www.arbeitsagentur.de/jobsuche/jobdetail/10000-1183300826-S"
    assert p.title == "Programmierung mit Python"
    assert p.company == "alfatraining Bildungszentrum GmbH"
    assert p.location == "80637 München"
    assert (p.lat, p.lon) == (48.1484534, 11.5373018)
    assert p.published_at == datetime(2026, 9, 29, tzinfo=UTC)
    assert p.employment_type == "fulltime"
    assert p.remote is True
    assert p.contract_type is None  # vertragsdauer == KEINE_ANGABE
    assert p.description is None
    assert p.raw == item
    assert postings[2].contract_type == "permanent"  # UNBEFRISTET
    assert postings[2].remote is None  # no homeoffice flag -> unknown


@respx.mock
def test_search_params(extractor):
    route = respx.get(JOBS_URL).mock(side_effect=_paged({}))
    profile = SearchProfileDTO(
        keywords="python", location="München", radius_km=25, employment_type="fulltime", remote=True
    )
    extractor.search(profile, _settings(extractor, include_zeitarbeit=False, published_since_days=7))
    request = route.calls[0].request
    params = request.url.params
    assert params["was"] == "python"
    assert params["wo"] == "München"
    assert params["umkreis"] == "25"
    assert params["arbeitszeit"] == "vz"  # never "ho": live it yields zero hits
    assert params["angebotsart"] == "1"
    assert params["veroeffentlichtseit"] == "7"
    assert params["zeitarbeit"] == "false"
    assert params["page"] == "1"
    assert params["size"] == "50"
    assert request.headers["X-API-Key"] == "jobboerse-jobsuche"


@respx.mock
def test_search_params_minimal(extractor):
    route = respx.get(JOBS_URL).mock(side_effect=_paged({}))
    extractor.search(SearchProfileDTO(keywords="go"), _settings(extractor))
    params = route.calls[0].request.url.params
    assert "wo" not in params and "umkreis" not in params and "arbeitszeit" not in params
    assert "zeitarbeit" not in params  # included by default -> no filter


@respx.mock
def test_pagination_stops_at_max_results(extractor, profile):
    route = respx.get(JOBS_URL).mock(side_effect=_paged(PAGES))
    postings = extractor.search(profile, _settings(extractor, max_results=4, page_size=3))
    assert route.call_count == 2
    assert len(postings) == 4
    assert [c.request.url.params["page"] for c in route.calls] == ["1", "2"]


@respx.mock
def test_pagination_stops_on_empty_page(extractor, profile):
    route = respx.get(JOBS_URL).mock(side_effect=_paged({1: PAGES[1]}))
    postings = extractor.search(profile, _settings(extractor, max_results=200, page_size=3))
    assert route.call_count == 2  # page 2 empty -> stop
    assert len(postings) == 3


@respx.mock
def test_pagination_stops_at_total(extractor, profile):
    page = {**PAGES[1], "maxErgebnisse": 3}
    route = respx.get(JOBS_URL).mock(side_effect=_paged({1: page}))
    assert len(extractor.search(profile, _settings(extractor, page_size=3))) == 3
    assert route.call_count == 1  # total reached; asking for more pages would be a 400


@respx.mock
def test_details_loaded_for_postings_without_description(extractor, profile):
    respx.get(JOBS_URL).mock(side_effect=_paged({1: PAGES[1]}))
    detail = _fixture("details.json")
    route = respx.get(url__startswith=DETAIL_URL).mock(return_value=httpx.Response(200, json=detail))
    postings = extractor.search(profile, _settings(extractor, page_size=3, fetch_details_for_new=True))
    assert route.call_count == 3
    expected = base64.b64encode(b"10000-1183300826-S").decode()
    assert route.calls[0].request.url.path.endswith("/v4/jobdetails/" + expected)
    assert route.calls[0].request.headers["X-API-Key"] == "jobboerse-jobsuche"
    assert all(p.description == detail["stellenangebotsBeschreibung"] for p in postings)
    # identity (title, id) stays that of the list result
    assert postings[0].external_id == "10000-1183300826-S"


@respx.mock
def test_detail_failure_keeps_posting(extractor, profile):
    respx.get(JOBS_URL).mock(side_effect=_paged({1: PAGES[1]}))
    respx.get(url__startswith=DETAIL_URL).mock(return_value=httpx.Response(500))
    postings = extractor.search(profile, _settings(extractor, page_size=3, fetch_details_for_new=True))
    assert len(postings) == 3
    assert all(p.description is None for p in postings)


@respx.mock
def test_fetch_by_url(extractor):
    assert extractor.matches_url("https://www.arbeitsagentur.de/jobsuche/jobdetail/10001-1000911926-S")
    assert not extractor.matches_url("https://example.com/jobsuche/jobdetail/10001-1000911926-S")
    detail = _fixture("details.json")
    refnr = "10001-1000911926-S"
    route = respx.get(DETAIL_URL + base64.b64encode(refnr.encode()).decode()).mock(
        return_value=httpx.Response(200, json=detail)
    )
    posting = extractor.fetch(
        f"https://www.arbeitsagentur.de/jobsuche/jobdetail/{refnr}?foo=1", _settings(extractor)
    )
    assert route.call_count == 1
    assert posting.external_id == refnr
    assert posting.url == f"https://www.arbeitsagentur.de/jobsuche/jobdetail/{refnr}"
    assert posting.title == "Python Advanced"
    assert posting.description.startswith("Lehrauftrag")
    assert posting.location == "10247 Berlin"


@respx.mock
def test_fetch_error_propagates(extractor):
    respx.get(url__startswith=DETAIL_URL).mock(return_value=httpx.Response(404))
    with pytest.raises(httpx.HTTPStatusError):
        extractor.fetch("https://www.arbeitsagentur.de/jobsuche/jobdetail/nope", _settings(extractor))


def test_employment_type_mapping(extractor):
    mod = sys.modules["jobtracker_plugin_arbeitsagentur"]
    base = {"referenznummer": "x", "stellenangebotsTitel": "T"}
    full = {**base, "arbeitszeitVollzeit": True, "arbeitszeitTeilzeitFlexibel": False}
    part = {**base, "arbeitszeitVollzeit": False, "arbeitszeitTeilzeitVormittag": True}
    both = {**base, "arbeitszeitVollzeit": True, "arbeitszeitTeilzeitVormittag": True}
    assert mod._map_item(full).employment_type == "fulltime"
    assert mod._map_item(part).employment_type == "parttime"
    assert mod._map_item(both).employment_type is None
    assert mod._map_item(base).employment_type is None
    assert mod._map_item({**base, "vertragsdauer": "BEFRISTET"}).contract_type == "temporary"
    assert mod._map_item({**base, "stellenlokationen": []}).location is None


def test_max_results_capped_at_200(extractor):
    from pydantic import ValidationError

    assert extractor.settings_schema(max_results=200).max_results == 200
    with pytest.raises(ValidationError):
        extractor.settings_schema(max_results=201)


def test_fetch_unsupported_url(extractor):
    with pytest.raises(ValueError, match="unsupported URL"):
        extractor.fetch("https://example.com/job/1", _settings(extractor))


@respx.mock
def test_non_dict_detail_response_keeps_posting(extractor, profile):
    respx.get(JOBS_URL).mock(side_effect=_paged({1: PAGES[1]}))
    respx.get(url__startswith=DETAIL_URL).mock(return_value=httpx.Response(200, json=["unexpected"]))
    postings = extractor.search(profile, _settings(extractor, page_size=3, fetch_details_for_new=True))
    assert len(postings) == 3
    assert all(p.description is None for p in postings)


@pytest.mark.live
def test_live_search(extractor):
    postings = extractor.search(
        SearchProfileDTO(keywords="python", location="München", radius_km=25),
        extractor.settings_schema(max_results=5, page_size=5, fetch_details_for_new=True),
    )
    assert len(postings) >= 1
    for p in postings:
        assert p.source == "arbeitsagentur" and p.external_id and p.title
        assert p.url.endswith(p.external_id)
    assert any(p.description for p in postings)


@respx.mock
def test_remote_profile_never_sends_ho(extractor):
    route = respx.get(JOBS_URL).mock(side_effect=_paged({}))
    extractor.search(SearchProfileDTO(keywords="python", remote=True), _settings(extractor))
    assert "arbeitszeit" not in route.calls[0].request.url.params


def test_homeoffice_mapping(extractor):
    base = {"referenznummer": "1-A", "stellenangebotsTitel": "T"}
    mapper = sys.modules[type(extractor).__module__]._map_item
    assert mapper({**base, "homeofficemoeglich": True}).remote is True
    assert mapper({**base, "homeofficemoeglich": False}).remote is False
    assert mapper(base).remote is None


@pytest.mark.parametrize(
    "url",
    [
        "http://www.arbeitsagentur.de/jobsuche/jobdetail/10001-1-S",
        "https://arbeitsagentur.de/jobsuche/jobdetail/10001-1-S",
        "http://arbeitsagentur.de/jobsuche/jobdetail/10001-1-S?x=1",
    ],
)
def test_url_patterns_accept_http_and_no_www(extractor, url):
    assert extractor.matches_url(url)


@respx.mock
def test_location_normalized(extractor):
    nominatim = respx.get(NOMINATIM_URL).mock(return_value=httpx.Response(200, json=[{"name": "München"}]))
    jobs = respx.get(JOBS_URL).mock(side_effect=_paged({}))
    profile = SearchProfileDTO(keywords="python", location="Munich", radius_km=25)
    extractor.search(profile, _settings(extractor, normalize_location=True))
    params = nominatim.calls[0].request.url.params
    assert params["q"] == "Munich"
    assert params["accept-language"] == "de"
    assert params["format"] == "jsonv2" and params["limit"] == "1"
    assert jobs.calls[0].request.url.params["wo"] == "München"
    assert jobs.calls[0].request.url.params["umkreis"] == "25"


@respx.mock
@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(500),
        httpx.Response(200, json=[]),
        httpx.Response(200, json={"x": 1}),
        httpx.Response(200, json=["Munich"]),
        httpx.Response(200, json=[{"name": ""}]),
        httpx.Response(200, json=[{"name": 5}]),
        httpx.Response(200, text="not json"),
        httpx.ConnectError("boom"),
    ],
)
def test_location_normalization_failure_keeps_original(extractor, response):
    if isinstance(response, Exception):
        respx.get(NOMINATIM_URL).mock(side_effect=response)
    else:
        respx.get(NOMINATIM_URL).mock(return_value=response)
    jobs = respx.get(JOBS_URL).mock(side_effect=_paged({1: PAGES[1]}))
    postings = extractor.search(
        SearchProfileDTO(keywords="python", location="Munich"), _settings(extractor, normalize_location=True)
    )
    assert jobs.calls[0].request.url.params["wo"] == "Munich"
    assert len(postings) == 3


@respx.mock
def test_location_normalization_disabled(extractor):
    nominatim = respx.get(NOMINATIM_URL).mock(return_value=httpx.Response(200, json=[{"name": "München"}]))
    jobs = respx.get(JOBS_URL).mock(side_effect=_paged({}))
    extractor.search(
        SearchProfileDTO(keywords="python", location="Munich"), _settings(extractor, normalize_location=False)
    )
    assert nominatim.call_count == 0
    assert jobs.calls[0].request.url.params["wo"] == "Munich"


@respx.mock
def test_location_normalization_skipped_without_location(extractor):
    nominatim = respx.get(NOMINATIM_URL).mock(return_value=httpx.Response(200, json=[{"name": "München"}]))
    respx.get(JOBS_URL).mock(side_effect=_paged({}))
    extractor.search(SearchProfileDTO(keywords="python"), _settings(extractor, normalize_location=True))
    assert nominatim.call_count == 0


@respx.mock
def test_location_normalization_cached(extractor):
    nominatim = respx.get(NOMINATIM_URL).mock(return_value=httpx.Response(200, json=[{"name": "München"}]))
    jobs = respx.get(JOBS_URL).mock(side_effect=_paged({}))
    settings = _settings(extractor, normalize_location=True)
    extractor.search(SearchProfileDTO(keywords="python", location="Munich"), settings)
    extractor.search(SearchProfileDTO(keywords="java", location=" munich "), settings)
    assert nominatim.call_count == 1
    assert [c.request.url.params["wo"] for c in jobs.calls] == ["München", "München"]


def test_settings_schema_has_normalize_location(extractor):
    prop = extractor.settings_schema.model_json_schema()["properties"]["normalize_location"]
    assert prop["default"] is True
    assert prop["title"] == "Normalize location"
    assert prop["description"] == "Translate the location to its German name via OpenStreetMap before searching"


@respx.mock
def test_failed_location_lookup_is_not_retried_within_ttl(extractor, monkeypatch):
    module = sys.modules[type(extractor).__module__]
    nominatim = respx.get(NOMINATIM_URL).mock(side_effect=httpx.ConnectError("boom"))
    jobs = respx.get(JOBS_URL).mock(side_effect=_paged({}))
    settings = _settings(extractor, normalize_location=True)
    extractor.search(SearchProfileDTO(keywords="python", location="Munich"), settings)
    extractor.search(SearchProfileDTO(keywords="java", location="Munich"), settings)
    assert nominatim.call_count == 1
    assert [c.request.url.params["wo"] for c in jobs.calls] == ["Munich", "Munich"]
    # after the TTL the lookup is attempted again
    key = "munich"
    module._LOCATION_FAILURES[key] -= module._FAILURE_TTL + 1
    extractor.search(SearchProfileDTO(keywords="go", location="Munich"), settings)
    assert nominatim.call_count == 2

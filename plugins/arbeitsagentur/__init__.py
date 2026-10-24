"""Extractor plugin for the job search of the Bundesagentur fuer Arbeit (public API).

API facts (verified live on 2026-10-22):

* Search: ``GET /pc/v6/jobs`` with header ``X-API-Key: jobboerse-jobsuche``. (``/pc/v4/jobs``
  answers 403.) The response holds the hit list under ``ergebnisliste`` and the total hit
  count under ``maxErgebnisse``. A page beyond the last one is answered with HTTP 400, so
  pagination also stops once ``page * size >= maxErgebnisse``.
* Detail: ``GET /pc/v4/jobdetails/{base64(referenznummer)}`` works (the ``v6`` equivalents
  answer 403). It returns the same fields as a search hit plus
  ``stellenangebotsBeschreibung`` (the description). Search hits never carry a description.
* Remote work: the ``arbeitszeit`` value ``ho`` must never be sent (``ho`` alone yields zero
  hits, ``vz;ho`` equals ``vz``). A remote-only profile is handled by the core post-filter on
  ``JobPosting.remote``, which is taken from ``homeofficemoeglich`` (absent -> unknown).
* The public detail page is ``https://www.arbeitsagentur.de/jobsuche/jobdetail/<refnr>``.
  (It is a JavaScript app and could not be fetched from the verification VM, so the pattern
  stays as given in the task brief.)

If the detail endpoint ever stops working, postings are still returned, with
``description=None`` (a failing detail call never aborts a search); ``fetch`` then raises.

All field names of the API live in the constants below and in ``_map_item``: API drift is a
one-spot fix.
"""

import base64
import re
import time
from datetime import UTC, date, datetime

import httpx
from pydantic import BaseModel, Field

from app.plugins.base import Capability, Extractor, JobPosting, SearchProfileDTO
from app.plugins.http import make_client

API_BASE = "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc"
SEARCH_PATH = "/v6/jobs"
DETAIL_PATH = "/v4/jobdetails/"
API_KEY = "jobboerse-jobsuche"
JOB_PAGE_URL = "https://www.arbeitsagentur.de/jobsuche/jobdetail/"

# --- response field names -------------------------------------------------------------
F_LIST = "ergebnisliste"
F_TOTAL = "maxErgebnisse"
F_REFNR = "referenznummer"
F_TITLE = "stellenangebotsTitel"
F_COMPANY = "firma"
F_DESCRIPTION = "stellenangebotsBeschreibung"  # detail endpoint only
F_LOCATIONS = "stellenlokationen"
F_ADDRESS = "adresse"
F_ZIP = "plz"
F_CITY = "ort"
F_LAT = "breite"
F_LON = "laenge"
F_PUBLISHED = ("veroeffentlichungszeitraum", "von")  # nested; falls back to F_FIRST_PUBLISHED
F_FIRST_PUBLISHED = "datumErsteVeroeffentlichung"
F_FULLTIME = "arbeitszeitVollzeit"
F_PARTTIME_PREFIX = "arbeitszeitTeilzeit"  # Vormittag/Nachmittag/Abend/Flexibel
F_HOMEOFFICE = "homeofficemoeglich"
F_CONTRACT = "vertragsdauer"
CONTRACT_TYPES = {"BEFRISTET": "temporary", "UNBEFRISTET": "permanent"}  # others: unknown

# --- request parameter values ---------------------------------------------------------
OFFER_TYPE_JOB = "1"  # angebotsart=1: ARBEIT (no self-employment/training/internship)
WORKTIME_PARAMS = {"fulltime": "vz", "parttime": "tz"}

# --- location normalisation (OpenStreetMap Nominatim) -----------------------------------
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
_LOCATION_CACHE: dict[str, str] = {}  # casefolded input place -> German place name (per process)


_FAILURE_TTL = 60.0  # seconds a failed lookup is not retried (keyword tasks run in parallel)
_LOCATION_FAILURES: dict[str, float] = {}  # casefolded input place -> monotonic time of the failure


def _reset_location_cache() -> None:
    _LOCATION_CACHE.clear()
    _LOCATION_FAILURES.clear()


def normalize_location(place: str, client: httpx.Client) -> str:
    """Return the German name of ``place`` via Nominatim; any failure returns ``place`` unchanged."""
    key = place.strip().casefold()
    if key in _LOCATION_CACHE:
        return _LOCATION_CACHE[key]
    failed_at = _LOCATION_FAILURES.get(key)
    if failed_at is not None:
        if time.monotonic() - failed_at < _FAILURE_TTL:
            return place
        _LOCATION_FAILURES.pop(key, None)
    try:
        response = client.get(
            NOMINATIM_URL,
            params={"format": "jsonv2", "limit": "1", "accept-language": "de", "q": place},
        )
        response.raise_for_status()
        body = response.json()
    except (httpx.HTTPError, ValueError):
        _LOCATION_FAILURES[key] = time.monotonic()
        return place
    first = body[0] if isinstance(body, list) and body else None
    name = first.get("name") if isinstance(first, dict) else None
    if not isinstance(name, str) or not name.strip():
        return place
    _LOCATION_CACHE[key] = name
    return name


class ArbeitsagenturSettings(BaseModel):
    max_results: int = Field(
        200, ge=1, le=200, title="Maximum results",
        description="Maximum number of job postings fetched per search run.",
    )
    published_since_days: int = Field(
        30, ge=0, le=100, title="Published within (days)",
        description="Only return postings published within this many days (0 = today only, max. 100).",
    )
    page_size: int = Field(
        50, ge=1, le=100, title="Page size",
        description="Number of results requested per API call (max. 100).",
    )
    include_zeitarbeit: bool = Field(
        True, title="Include temporary-agency jobs",
        description="If disabled, postings from temporary employment agencies (Zeitarbeit) are excluded.",
    )
    fetch_details_for_new: bool = Field(
        True, title="Fetch descriptions",
        description="Load the full description for results that come without one (one extra API call per posting).",
    )
    normalize_location: bool = Field(
        True, title="Normalize location",
        description="Translate the location to its German name via OpenStreetMap before searching",
    )


def _get(value: dict, *path: str):
    for key in path:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def _parse_date(value) -> datetime | None:
    """Date-only ('2026-09-29') -> midnight UTC; datetime strings without zone are taken as UTC."""
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        try:
            parsed = datetime.combine(date.fromisoformat(value[:10]), datetime.min.time())
        except ValueError:
            return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed


def _employment_type(item: dict) -> str | None:
    fulltime = item.get(F_FULLTIME) is True
    parttime = any(v is True for k, v in item.items() if k.startswith(F_PARTTIME_PREFIX))
    if fulltime and not parttime:
        return "fulltime"
    if parttime and not fulltime:
        return "parttime"
    return None  # both or neither: not determinable


def _number(value) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _map_item(item: dict) -> JobPosting:
    """Map one API result (search hit or job detail) to a JobPosting."""
    refnr = item[F_REFNR]
    locations = item.get(F_LOCATIONS)
    first = locations[0] if isinstance(locations, list) and locations and isinstance(locations[0], dict) else {}
    zip_code, city = _get(first, F_ADDRESS, F_ZIP), _get(first, F_ADDRESS, F_CITY)
    location = " ".join(str(p) for p in (zip_code, city) if p) or None
    published = _parse_date(_get(item, *F_PUBLISHED)) or _parse_date(item.get(F_FIRST_PUBLISHED))
    return JobPosting(
        source=ArbeitsagenturExtractor.name,
        external_id=refnr,
        url=JOB_PAGE_URL + refnr,
        title=item[F_TITLE],
        company=item.get(F_COMPANY) or None,
        location=location,
        lat=_number(first.get(F_LAT)),
        lon=_number(first.get(F_LON)),
        description=item.get(F_DESCRIPTION) or None,
        published_at=published,
        employment_type=_employment_type(item),
        remote=item[F_HOMEOFFICE] if isinstance(item.get(F_HOMEOFFICE), bool) else None,
        contract_type=CONTRACT_TYPES.get(item.get(F_CONTRACT)),
        raw=item,
    )


def _search_params(profile: SearchProfileDTO, settings: ArbeitsagenturSettings) -> dict[str, str]:
    params = {
        "was": profile.keywords,
        "angebotsart": OFFER_TYPE_JOB,
        "veroeffentlichtseit": str(settings.published_since_days),
        "size": str(settings.page_size),
    }
    if profile.location:
        params["wo"] = profile.location
        if profile.radius_km is not None:
            params["umkreis"] = str(profile.radius_km)
    worktime = [WORKTIME_PARAMS[profile.employment_type]] if profile.employment_type in WORKTIME_PARAMS else []
    if worktime:
        params["arbeitszeit"] = ";".join(worktime)
    if not settings.include_zeitarbeit:
        params["zeitarbeit"] = "false"
    return params


def _detail_url(refnr: str) -> str:
    return API_BASE + DETAIL_PATH + base64.b64encode(refnr.encode()).decode()


class ArbeitsagenturExtractor(Extractor):
    name = "arbeitsagentur"
    display_name = "Bundesagentur für Arbeit"
    capabilities = {Capability.SEARCH, Capability.FETCH}
    url_patterns = [r"https?://(?:www\.)?arbeitsagentur\.de/jobsuche/jobdetail/(?P<refnr>[^/?#]+)"]
    settings_schema = ArbeitsagenturSettings

    @staticmethod
    def _client() -> httpx.Client:
        return make_client(headers={"X-API-Key": API_KEY, "Accept": "application/json"}, min_interval=0.2)

    def search(self, profile: SearchProfileDTO, settings: ArbeitsagenturSettings) -> list[JobPosting]:
        params = _search_params(profile, settings)
        if settings.normalize_location and profile.location:
            with make_client(min_interval=1.0, retries=0, timeout=5) as geo_client:
                params["wo"] = normalize_location(profile.location, geo_client)
        postings: list[JobPosting] = []
        with self._client() as client:
            page = 1
            while len(postings) < settings.max_results:
                response = client.get(API_BASE + SEARCH_PATH, params={**params, "page": str(page)})
                response.raise_for_status()
                body = response.json()
                items = body.get(F_LIST) or []
                if not items:
                    break
                postings.extend(_map_item(i) for i in items if i.get(F_REFNR) and i.get(F_TITLE))
                total = body.get(F_TOTAL)
                if isinstance(total, int) and page * settings.page_size >= total:
                    break  # a page beyond the last one is a 400
                page += 1
            postings = postings[: settings.max_results]
            if settings.fetch_details_for_new:
                for i, posting in enumerate(postings):
                    if posting.description is None:
                        postings[i] = self._with_description(client, posting)
        return postings

    @staticmethod
    def _with_description(client: httpx.Client, posting: JobPosting) -> JobPosting:
        try:
            response = client.get(_detail_url(posting.external_id))
            response.raise_for_status()
            body = response.json()
        except (httpx.HTTPError, ValueError):
            return posting  # keep the posting without description; never abort the run
        description = body.get(F_DESCRIPTION) if isinstance(body, dict) else None
        if not isinstance(description, str) or not description:
            return posting
        return posting.model_copy(update={"description": description})

    def fetch(self, url: str, settings: ArbeitsagenturSettings) -> JobPosting:
        match = next((m for p in self.url_patterns if (m := re.match(p, url))), None)
        if match is None:
            raise ValueError("unsupported URL")
        refnr = match.group("refnr")
        with self._client() as client:
            response = client.get(_detail_url(refnr))
            response.raise_for_status()
            item = response.json()
        if not isinstance(item, dict):
            raise ValueError("unexpected detail response")
        item.setdefault(F_REFNR, refnr)
        return _map_item(item)

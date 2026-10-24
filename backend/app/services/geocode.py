"""Place name -> coordinates via Nominatim (needed for the feed's radius filter)."""

import logging
import threading
import time

import httpx

from app.plugins.http import make_client

log = logging.getLogger(__name__)

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
FAILURE_TTL = 60.0  # seconds a failed lookup is not retried
TIMEOUT = 5.0


class Geocoder:
    """Nominatim lookup with an in-memory cache (empty results included).

    Nominatim's usage policy allows one request per second and requires an
    identifying User-Agent; both are handled by the shared http helper.
    Transient failures (network, HTTP errors) return None and are remembered for
    FAILURE_TTL seconds only, so a down geocoder is not hammered (no retries, short timeout).
    """

    def __init__(self, client: httpx.Client | None = None) -> None:
        self._client = client
        self._cache: dict[str, tuple[float, float] | None] = {}
        self._failed: dict[str, float] = {}  # key -> monotonic time of the failure
        self._lock = threading.Lock()

    def lookup(self, place: str) -> tuple[float, float] | None:
        key = place.strip().casefold()
        if not key:
            return None
        with self._lock:  # also serialises requests across threads (1 req/s)
            if key in self._cache:
                return self._cache[key]
            failed_at = self._failed.get(key)
            if failed_at is not None:
                if time.monotonic() - failed_at < FAILURE_TTL:
                    return None
                del self._failed[key]
            if self._client is None:
                self._client = make_client(retries=0, timeout=TIMEOUT, min_interval=1.0)
            try:
                response = self._client.get(
                    NOMINATIM_URL,
                    params={"format": "json", "limit": 1, "countrycodes": "de", "q": place.strip()},
                )
                response.raise_for_status()
                data = response.json()
            except (httpx.HTTPError, ValueError) as exc:
                log.warning("geocoding %r failed: %s", place, exc)
                self._failed[key] = time.monotonic()
                return None
            result: tuple[float, float] | None = None
            if isinstance(data, list) and data:
                try:
                    result = (float(data[0]["lat"]), float(data[0]["lon"]))
                except (KeyError, TypeError, ValueError):
                    log.warning("geocoding %r: unexpected response shape", place)
                    self._failed[key] = time.monotonic()
                    return None
            self._cache[key] = result
            return result

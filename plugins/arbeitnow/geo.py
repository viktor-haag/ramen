"""Geocoding of posting locations via OpenStreetMap Nominatim, with a persistent shared cache.

Results (including 'no result') are stored in the SQLite cache; transient failures are never stored.
Requests are spaced across processes by the cache's rate slot, and each Geocoder has a budget of new lookups and stops
looking up new places after the first transient failure (circuit breaker).
"""

import logging
import math

import httpx

from .cache import MISSING, Cache

log = logging.getLogger(__name__)

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
PLACELESS = {"", "remote", "remote job", "anywhere"}
_EARTH_RADIUS_KM = 6371.0088


def place_key(place: str | None) -> str | None:
    """Normalised cache key (trimmed, casefolded); ``None`` for empty or placeless values."""
    if not isinstance(place, str):
        return None
    key = place.strip().casefold()
    return None if key in PLACELESS else key


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    a = (
        math.sin((phi2 - phi1) / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    )
    return 2 * _EARTH_RADIUS_KM * math.asin(math.sqrt(a))


class Geocoder:
    def __init__(self, cache: Cache, client: httpx.Client, budget: int) -> None:
        self.cache = cache
        self.client = client
        self.budget = budget  # remaining network attempts (failed ones count)
        self.tripped = False  # set by the first transient failure: no further network lookups

    def cached(self, place: str | None) -> tuple[float, float] | None:
        """Coordinates from the cache only; never touches the network."""
        key = place_key(place)
        if key is None:
            return None
        hit = self.cache.geocode_get(key)
        return None if hit is MISSING else hit

    def lookup(self, place: str | None, *, use_budget: bool = True) -> tuple[float, float] | None:
        key = place_key(place)
        if key is None:
            return None
        hit = self.cache.geocode_get(key)
        if hit is not MISSING:
            return hit
        if self.tripped:
            return None
        if use_budget:
            if self.budget <= 0:
                return None
            self.budget -= 1
        self.cache.wait_rate_slot()
        try:
            response = self.client.get(
                NOMINATIM_URL, params={"format": "jsonv2", "limit": "1", "q": place.strip()}
            )
            response.raise_for_status()
            body = response.json()
            if not isinstance(body, list):
                raise ValueError("unexpected Nominatim response shape")
            coords = None
            if body:
                first = body[0]
                if not isinstance(first, dict):
                    raise ValueError("unexpected Nominatim result shape")
                coords = (float(first["lat"]), float(first["lon"]))
                if not all(math.isfinite(v) for v in coords):
                    raise ValueError("non-finite coordinates")
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            self.tripped = True
            log.warning("Geocoding of %r failed (not cached), stopping further lookups: %s", place, exc)
            return None
        self.cache.geocode_put(key, coords)
        return coords

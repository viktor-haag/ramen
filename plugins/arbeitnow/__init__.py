"""Extractor plugin for the job board Arbeitnow (free public API, no key).

API facts (verified live on 2026-10-24):

* ``GET https://www.arbeitnow.com/api/job-board-api?page=N``, no authentication. Response:
  ``{data: [...], links: {first, last, prev, next}, meta: {...}}``.
* There is no server-side search: ``search``/``location`` parameters are ignored, so the plugin
  filters client-side.
* Pagination: ``links.next`` is ``null`` on the last page, ``links.last`` is always ``null``;
  pages beyond the end return ``data: []``.
* Size: ~25 pages of 150-300 postings (2-4 MB per page), roughly one week back, refreshed hourly.
  Pages overlap in time, so the whole feed is loaded (capped by ``max_pages``).
* Fields per posting: ``slug``, ``company_name``, ``title``, ``description`` (HTML), ``remote``
  (bool), ``url``, ``tags`` (list), ``job_types`` (list, inconsistent, multilingual), ``location``
  (free text, may be empty) and ``created_at`` (Unix seconds).
* ``meta.terms``: free public API, "please do not abuse", link back to arbeitnow.com. Every posting
  links to arbeitnow.com; the feed is fetched politely (cache, minimum request interval).

All API field names live in ``mapping.py``.
"""

from pathlib import Path

from pydantic import BaseModel, Field

from app.config import Settings
from app.plugins.base import Capability, Extractor, JobPosting, SearchProfileDTO
from app.plugins.http import make_client

from . import cache, feed, geo, mapping  # noqa: F401  (registers jobtracker_plugin_arbeitnow.<sub>)


def cache_path() -> Path:
    """SQLite file shared by all runs (feed cache, geocode cache, request rate)."""
    return Settings().data_dir / "plugin_cache" / "arbeitnow.sqlite"


class ArbeitnowSettings(BaseModel):
    max_pages: int = Field(
        30, ge=1, le=100, title="Maximum pages",
        description="Upper limit of feed pages loaded per refresh (about 25 pages hold the whole feed).",
    )
    cache_minutes: int = Field(
        30, ge=0, le=1440, title="Cache (minutes)",
        description="How long the loaded feed is reused (0 = always reload).",
    )
    search_description: bool = Field(
        True, title="Search descriptions",
        description="Also look for the keyword in the posting description, not only in title and tags.",
    )
    default_radius_km: int = Field(
        25, ge=0, le=500, title="Default radius (km)",
        description="Search radius when the search profile has none.",
    )
    max_new_geocodes: int = Field(
        60, ge=0, le=1000, title="Location lookups per search",
        description="Maximum number of new location lookups (OpenStreetMap, about one per second) per keyword search.",
    )


class ArbeitnowExtractor(Extractor):
    name = "arbeitnow"
    display_name = "Arbeitnow"
    capabilities = {Capability.SEARCH}
    settings_schema = ArbeitnowSettings
    timeout_seconds = 300

    def search(self, profile: SearchProfileDTO, settings: ArbeitnowSettings) -> list[JobPosting]:
        if not profile.keywords.strip():
            return []
        with (
            cache.Cache(cache_path()) as db,
            make_client(min_interval=1.0, headers={"Accept": "application/json"}) as feed_client,
            make_client(retries=0, timeout=5) as geo_client,
        ):
            db.ensure_feed(
                settings.cache_minutes * 60, lambda: feed.iter_feed(feed_client, settings.max_pages)
            )
            hits = db.matching(mapping.keyword_pattern(profile.keywords), settings.search_description)
            geocoder = geo.Geocoder(db, geo_client, settings.max_new_geocodes)

            postings: list[JobPosting | None] = []
            if not profile.location:
                for item, text in hits:
                    postings.append(
                        mapping.to_posting(item, text, geocoder.cached(item.get(mapping.F_LOCATION)))
                    )
            else:
                center = geocoder.lookup(profile.location, use_budget=False)
                if center is None:
                    raise ValueError(f"location not found: {profile.location}")
                radius = profile.radius_km if profile.radius_km is not None else settings.default_radius_km
                for item, text in hits:
                    location = item.get(mapping.F_LOCATION)
                    if item.get(mapping.F_REMOTE) is True:
                        postings.append(mapping.to_posting(item, text, geocoder.cached(location)))
                        continue
                    coords = geocoder.lookup(location)
                    if coords and geo.haversine_km(*center, *coords) <= radius:
                        postings.append(mapping.to_posting(item, text, coords))
            return [p for p in postings if p is not None]

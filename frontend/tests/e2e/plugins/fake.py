"""Deterministic plugin for the end-to-end tests: five fixed postings per search term, no network."""
from urllib.parse import urlparse

from app.plugins.base import Capability, Extractor, JobPosting, SearchProfileDTO


def _posting(ext_id: str, title: str, url: str) -> JobPosting:
    return JobPosting(
        source="fake", external_id=ext_id, url=url, title=title,
        company="Fake GmbH", location="Berlin", description=f"Description of {title}.",
    )


class FakeExtractor(Extractor):
    name = "fake"
    display_name = "Fake"
    capabilities = {Capability.SEARCH, Capability.FETCH}
    start_spacing_seconds = (0.0, 0.0)  # e2e runs must not wait between keyword starts
    url_patterns = [r"https://fake\.test/.*"]

    def search(self, profile: SearchProfileDTO, settings) -> list[JobPosting]:
        kw = profile.keywords
        where = f" @ {profile.location}" if profile.location else ""
        return [_posting(f"{kw}-{i}", f"{kw} job {i}{where}", f"https://fake.test/job/{kw}-{i}") for i in range(1, 6)]

    def fetch(self, url: str, settings) -> JobPosting:
        # The external id follows the URL, so every URL yields its own posting.
        slug = urlparse(url).path.strip("/").replace("/", "-") or "root"
        return _posting(f"url-{slug}", f"Fetched {slug}", url)

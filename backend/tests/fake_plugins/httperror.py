import httpx

from app.plugins.base import Capability, EmptySettings, Extractor, JobPosting, SearchProfileDTO


class HttpErrorExtractor(Extractor):
    """Fails like a rate-limited job board: raises httpx.HTTPStatusError, which does not unpickle."""

    name = "httperror"
    display_name = "HTTP error"
    capabilities = {Capability.SEARCH}

    def search(self, profile: SearchProfileDTO, settings: EmptySettings) -> list[JobPosting]:
        request = httpx.Request("GET", "https://api.example.test/jobs")
        response = httpx.Response(429, request=request)
        response.raise_for_status()
        return []

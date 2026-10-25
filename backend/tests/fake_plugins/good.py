from pydantic import BaseModel

from app.plugins.base import Capability, Extractor, JobPosting, SearchProfileDTO


class GoodSettings(BaseModel):
    max: int = 3


def _posting(ext_id: str, title: str) -> JobPosting:
    return JobPosting(
        source="good", external_id=ext_id, url=f"https://good.test/job/{ext_id}",
        title=title, company="Good GmbH", location="Berlin",
    )


class GoodExtractor(Extractor):
    name = "good"
    display_name = "Good"
    capabilities = {Capability.SEARCH, Capability.FETCH}
    start_spacing_seconds = (0.0, 0.0)
    url_patterns = [r"https://good\.test/.*"]
    settings_schema = GoodSettings

    def search(self, profile: SearchProfileDTO, settings: GoodSettings) -> list[JobPosting]:
        kw = profile.keywords
        found = [_posting(f"{kw}-{i}", f"{kw} job {i}") for i in range(1, settings.max + 1)]
        return [*found, _posting("shared-1", "shared job")]  # same in every keyword's result

    def fetch(self, url: str, settings: GoodSettings) -> JobPosting:
        return _posting("g-url", "Fetched job")

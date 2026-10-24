import time

from app.plugins.base import Capability, EmptySettings, Extractor, JobPosting, SearchProfileDTO


class HangExtractor(Extractor):
    name = "hang"
    display_name = "Hang"
    capabilities = {Capability.SEARCH}
    timeout_seconds = 1

    def search(self, profile: SearchProfileDTO, settings: EmptySettings) -> list[JobPosting]:
        time.sleep(60)
        return []

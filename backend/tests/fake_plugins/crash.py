import os

from app.plugins.base import Capability, EmptySettings, Extractor, JobPosting, SearchProfileDTO


class CrashExtractor(Extractor):
    name = "crash"
    display_name = "Crash"
    capabilities = {Capability.SEARCH}

    def search(self, profile: SearchProfileDTO, settings: EmptySettings) -> list[JobPosting]:
        os._exit(1)

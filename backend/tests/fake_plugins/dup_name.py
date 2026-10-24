from app.plugins.base import Capability, EmptySettings, Extractor, JobPosting, SearchProfileDTO


class DupNameExtractor(Extractor):
    name = "good"
    display_name = "Duplicate"
    capabilities = {Capability.SEARCH}

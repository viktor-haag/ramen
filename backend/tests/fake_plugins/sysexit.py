import sys

from app.plugins.base import Capability, EmptySettings, Extractor, JobPosting, SearchProfileDTO


class SysExitExtractor(Extractor):
    """Raises a BaseException (not an Exception) inside the worker."""

    name = "sysexit"
    display_name = "SysExit"
    capabilities = {Capability.SEARCH}
    start_spacing_seconds = (0.0, 0.0)

    def search(self, profile: SearchProfileDTO, settings: EmptySettings) -> list[JobPosting]:
        sys.exit(3)

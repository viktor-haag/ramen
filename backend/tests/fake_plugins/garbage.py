from app.plugins.base import Capability, EmptySettings, Extractor, JobPosting, SearchProfileDTO


class GarbageExtractor(Extractor):
    name = "garbage"
    display_name = "Garbage"
    capabilities = {Capability.SEARCH}

    def search(self, profile: SearchProfileDTO, settings: EmptySettings) -> list[JobPosting]:
        def ok(i: int) -> JobPosting:
            return JobPosting(source="garbage", external_id=f"x{i}", url=f"https://garbage.test/{i}", title=f"Valid {i}")

        # model_construct skips validation: no title, so it reaches the core invalid.
        bad = JobPosting.model_construct(source="garbage", external_id="x3", url="https://garbage.test/3")
        return [ok(1), ok(2), bad]

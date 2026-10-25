from app.plugins.base import Capability, EmptySettings, Extractor, JobPosting, SearchProfileDTO


class OptinExtractor(Extractor):
    name = "optin"
    display_name = "Opt-in"
    capabilities = {Capability.SEARCH}
    enabled_by_default = False
    notice = {"de": "Achtung", "en": "Careful"}

    def search(self, profile: SearchProfileDTO, settings: EmptySettings) -> list[JobPosting]:
        return [JobPosting(source="optin", external_id="o1", url="https://optin.test/1", title="Optin job")]

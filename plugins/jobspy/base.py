"""Shared base class, settings models and notice texts of the JobSpy plugins.

``jobspy`` (and with it pandas) is imported lazily inside ``search()``: plugin discovery runs in
the API process and must stay light. The country lists below therefore mirror python-jobspy 1.4.1
(``jobspy.model.Country`` for Indeed, ``jobspy.glassdoor.constant.domains`` for Glassdoor); a test
checks them against the installed package.
"""

import logging
import re
from enum import StrEnum
from typing import ClassVar

from pydantic import BaseModel, Field

from app.plugins.base import Capability, Extractor, JobPosting, SearchProfileDTO

from . import mapping

log = logging.getLogger(__name__)

KM_PER_MILE = 1.609344
ERROR_MAX_CHARS = 300

NOTICE = {
    "de": (
        "Diese Börse wird über JobSpy abgefragt (Scraping). Das kann gegen die Nutzungsbedingungen "
        "der Börse verstoßen. Häufige Anfragen können zur Sperre deiner IP-Adresse oder deines "
        "Kontos führen – vor allem bei LinkedIn. Ein VPN oder ein Proxy (Einstellung unten) ist "
        "ratsam; halte die Trefferzahl und die Suchhäufigkeit niedrig."
    ),
    "en": (
        "This job board is queried through JobSpy (scraping). This may violate the board's terms "
        "of use. Frequent requests can get your IP address or your account blocked – especially "
        "on LinkedIn. A VPN or a proxy (setting below) is advisable; keep the number of results "
        "and the search frequency low."
    ),
}

INDEED_COUNTRIES = (
    "argentina", "australia", "austria", "bahrain", "belgium", "brazil", "canada", "chile",
    "china", "colombia", "costa rica", "czech republic", "denmark", "ecuador", "egypt", "finland",
    "france", "germany", "greece", "hong kong", "hungary", "india", "indonesia", "ireland",
    "israel", "italy", "japan", "kuwait", "luxembourg", "malaysia", "mexico", "morocco",
    "netherlands", "new zealand", "nigeria", "norway", "oman", "pakistan", "panama", "peru",
    "philippines", "poland", "portugal", "qatar", "romania", "saudi arabia", "singapore",
    "south africa", "south korea", "spain", "sweden", "switzerland", "taiwan", "thailand",
    "türkiye", "ukraine", "united arab emirates", "uk", "usa", "uruguay", "venezuela", "vietnam",
)
GLASSDOOR_COUNTRIES = (
    "argentina", "australia", "austria", "belgium", "brazil", "canada", "france", "germany",
    "hong kong", "india", "ireland", "italy", "malaysia", "mexico", "netherlands", "new zealand",
    "singapore", "spain", "switzerland", "uk", "usa", "vietnam",
)


def _country_enum(name: str, values: tuple[str, ...]) -> type[StrEnum]:
    members = {re.sub(r"\W", "_", v.upper()): v for v in values}
    return StrEnum(name, members, module=__name__, qualname=name)


IndeedCountry = _country_enum("IndeedCountry", INDEED_COUNTRIES)
GlassdoorCountry = _country_enum("GlassdoorCountry", GLASSDOOR_COUNTRIES)


def parse_proxies(text: str | None) -> list[str]:
    """Proxy entries separated by newlines or commas; blanks are ignored."""
    return [p.strip() for p in re.split(r"[\n,]", text or "") if p.strip()]


class JobSpySettings(BaseModel):
    results_wanted: int = Field(25, ge=1, le=200, title="Results per search")
    hours_old: int | None = Field(
        72, ge=1, title="Posted within (hours)",
        description="Only postings of the last … hours (empty = all).",
    )
    proxies: str | None = Field(
        None, title="Proxies",
        description="Optional; several entries separated by commas or line breaks, "
        "e.g. user:password@host:port.",
        json_schema_extra={"format": "password"},
    )


class JobSpyFetchSettings(JobSpySettings):
    fetch_description: bool = Field(
        False, title="Load full description",
        description="Slower, more requests per search.",
    )


class IndeedSettings(JobSpySettings):
    country: IndeedCountry = Field(IndeedCountry("germany"), title="Country")


class GlassdoorSettings(JobSpyFetchSettings):
    country: GlassdoorCountry = Field(GlassdoorCountry("germany"), title="Country")


class JobSpyExtractor(Extractor):
    """One JobSpy site per subclass. Not registered itself (the loader drops intermediate bases)."""

    site: ClassVar[str]
    has_country: ClassVar[bool] = False
    has_fetch_description: ClassVar[bool] = False
    capabilities = {Capability.SEARCH}
    settings_schema = JobSpySettings
    timeout_seconds = 180
    enabled_by_default = False
    notice = NOTICE

    def scrape_kwargs(self, profile: SearchProfileDTO, settings: JobSpySettings) -> dict:
        kwargs = dict(
            site_name=[self.site],
            search_term=profile.keywords,
            location=profile.location or None,
            distance=round(profile.radius_km / KM_PER_MILE) if profile.radius_km else None,
            is_remote=profile.remote is True,
            job_type=profile.employment_type if profile.employment_type in ("fulltime", "parttime") else None,
            results_wanted=settings.results_wanted,
            hours_old=settings.hours_old,
            proxies=parse_proxies(settings.proxies),
            description_format="plain",
            fetch_description=bool(getattr(settings, "fetch_description", False))
            if self.has_fetch_description else False,
            verbose=0,
        )
        if self.has_country:
            kwargs["country_indeed"] = settings.country.value
        return kwargs

    def search(self, profile: SearchProfileDTO, settings: JobSpySettings) -> list[JobPosting]:
        if not profile.keywords.strip():
            return []
        import jobspy  # lazy: pulls in pandas, only needed in the worker process

        df = jobspy.scrape_jobs(**self.scrape_kwargs(profile, settings))
        rows = df.to_dict("records")
        errors = (getattr(df, "attrs", None) or {}).get("errors") or {}
        error = errors.get(self.site) or "; ".join(str(v) for v in errors.values() if v)
        postings = [p for row in rows if (p := mapping.to_posting(row, self.name)) is not None]
        if len(postings) < len(rows):
            log.info("%s: skipped %d rows without title or URL", self.name, len(rows) - len(postings))
        if error:
            if not postings:
                raise RuntimeError(f"{self.display_name}: {str(error)[:ERROR_MAX_CHARS]}")
            log.warning("%s: partial results (%d), JobSpy reported: %s", self.name, len(postings), error)
        return postings

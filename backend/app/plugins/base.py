import re
from abc import ABC
from datetime import datetime
from enum import StrEnum
from typing import ClassVar

from pydantic import BaseModel, Field


def url_matches(patterns: list[str], url: str) -> bool:
    return any(re.match(p, url) for p in patterns)


class Capability(StrEnum):
    SEARCH = "search"
    FETCH = "fetch"


class SearchProfileDTO(BaseModel):
    keywords: str
    location: str | None = None
    radius_km: int | None = None
    employment_type: str | None = None  # "fulltime" | "parttime" | None
    remote: bool | None = None


class JobPosting(BaseModel):
    source: str
    external_id: str = Field(min_length=1)
    url: str
    title: str = Field(min_length=1)
    company: str | None = None
    location: str | None = None
    lat: float | None = None
    lon: float | None = None
    description: str | None = None
    published_at: datetime | None = None
    employment_type: str | None = None
    remote: bool | None = None
    contract_type: str | None = None  # "permanent" | "temporary" | None
    raw: dict = Field(default_factory=dict)


class EmptySettings(BaseModel):
    pass


class Extractor(ABC):
    name: ClassVar[str]
    display_name: ClassVar[str]
    capabilities: ClassVar[set[Capability]]
    url_patterns: ClassVar[list[str]] = []
    settings_schema: ClassVar[type[BaseModel]] = EmptySettings
    timeout_seconds: ClassVar[int] = 120

    def search(self, profile: SearchProfileDTO, settings: BaseModel) -> list[JobPosting]:
        raise NotImplementedError

    def fetch(self, url: str, settings: BaseModel) -> JobPosting:
        raise NotImplementedError

    @classmethod
    def matches_url(cls, url: str) -> bool:
        return url_matches(cls.url_patterns, url)

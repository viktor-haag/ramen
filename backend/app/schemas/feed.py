from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models import TriageStatus
from app.schemas.fit import FitOut


class FeedFilter(BaseModel):
    triage: list[TriageStatus] = Field(default_factory=lambda: [TriageStatus.new, TriageStatus.saved])
    source: list[str] = Field(default_factory=list)
    profile_id: int | None = None
    q: str | None = None
    location: str | None = None
    radius_km: int | None = Field(default=None, ge=1)
    found_after: datetime | None = None
    found_before: datetime | None = None
    published_after: datetime | None = None
    employment_type: str | None = None
    remote: bool | None = None
    fit: list[Literal["good", "moderate", "poor", "none"]] = Field(default_factory=list)
    sort: Literal["first_seen_at", "published_at", "fit"] = "first_seen_at"
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=50, ge=1, le=200)

    @field_validator("found_after", "found_before", "published_after")
    @classmethod
    def _naive_is_utc(cls, value: datetime | None) -> datetime | None:
        # The DB layer rejects naive datetimes; interpret them (and date-only values) as UTC.
        if value is not None and value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value


class PostingOut(BaseModel):
    """A posting as the API shows it (everything except the raw plugin payload)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    source: str
    external_id: str
    url: str | None
    title: str | None
    company: str | None
    location: str | None
    lat: float | None
    lon: float | None
    description: str | None
    published_at: datetime | None
    first_seen_at: datetime
    last_seen_at: datetime
    employment_type: str | None
    remote: bool | None
    contract_type: str | None
    triage_status: TriageStatus
    triaged_at: datetime | None
    profile_ids: list[int] = Field(default_factory=list)
    application_id: int | None = None
    fit: FitOut | None = None


class PostingDetail(PostingOut):
    raw: dict | None = None


class FeedPage(BaseModel):
    items: list[PostingOut]
    total: int


class ManualPostingIn(BaseModel):
    title: str = Field(min_length=1)
    company: str | None = None
    location: str | None = None
    url: str | None = None
    description: str | None = None
    published_at: datetime | None = None
    employment_type: str | None = None
    remote: bool | None = None
    contract_type: str | None = None

    @field_validator("title")
    @classmethod
    def _title_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("title must not be blank")
        return value.strip()

    @field_validator("published_at")
    @classmethod
    def _naive_is_utc(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value


class FromUrlIn(BaseModel):
    url: str = Field(min_length=1)

from datetime import datetime

from pydantic import BaseModel, Field, field_validator, model_validator

MAX_KEYWORDS = 20
MAX_KEYWORD_LENGTH = 100
MAX_LOCATIONS = 20
MAX_LOCATION_LENGTH = 100


def normalize_keywords(values: list[str]) -> list[str]:
    """Trim, drop empty entries and case-insensitive duplicates (first occurrence wins)."""
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        word = value.strip()
        if word and word.casefold() not in seen:
            seen.add(word.casefold())
            result.append(word)
    return result


def normalize_locations(values: list[str]) -> list[str]:
    """Same rules as the keywords: trim, drop blanks and case-insensitive duplicates."""
    return normalize_keywords(values)


class _ProfileBase(BaseModel):
    name: str = Field(min_length=1)
    keywords: list[str]
    locations: list[str] = Field(default_factory=list)
    radius_km: int | None = None
    employment_type: str | None = None
    remote: bool | None = None
    enabled: bool = True
    schedule_hours: int | None = Field(default=None, ge=1)
    plugins: list[str] = Field(default_factory=list)


class ProfileIn(_ProfileBase):
    @field_validator("keywords")
    @classmethod
    def _check_keywords(cls, values: list[str]) -> list[str]:
        words = normalize_keywords(values)
        if not words:
            raise ValueError("at least one keyword is required")
        if len(words) > MAX_KEYWORDS:
            raise ValueError(f"at most {MAX_KEYWORDS} keywords are allowed")
        if any(len(w) > MAX_KEYWORD_LENGTH for w in words):
            raise ValueError(f"keywords may have at most {MAX_KEYWORD_LENGTH} characters")
        return words


    @field_validator("locations")
    @classmethod
    def _check_locations(cls, values: list[str]) -> list[str]:
        cities = normalize_locations(values)
        if len(cities) > MAX_LOCATIONS:
            raise ValueError(f"at most {MAX_LOCATIONS} cities are allowed")
        if any(len(c) > MAX_LOCATION_LENGTH for c in cities):
            raise ValueError(f"cities may have at most {MAX_LOCATION_LENGTH} characters")
        return cities

    @model_validator(mode="after")
    def _radius_needs_city(self) -> "ProfileIn":
        if not self.locations:
            self.radius_km = None
        return self


class ProfileOut(_ProfileBase):
    # No keyword validation on output: legacy rows (migration) may have an empty list.
    id: int
    last_run_at: datetime | None = None

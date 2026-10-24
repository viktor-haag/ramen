from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models import AppointmentKind, AppStatus, AttachmentKind
from app.schemas.feed import PostingOut


class StatusChangeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    application_id: int
    from_status: AppStatus | None
    to_status: AppStatus
    changed_at: datetime
    comment: str | None


class AppointmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    application_id: int
    kind: AppointmentKind
    starts_at: datetime
    note: str | None


def _utc(value: datetime) -> datetime:
    """Naive input is interpreted as UTC (same convention as the feed filters)."""
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


class AppointmentIn(BaseModel):
    kind: AppointmentKind = AppointmentKind.other
    starts_at: datetime
    note: str | None = None

    _starts_at_utc = field_validator("starts_at")(_utc)


class AppointmentPatch(BaseModel):
    kind: AppointmentKind | None = None
    starts_at: datetime | None = None
    note: str | None = None

    @field_validator("kind", "starts_at")
    @classmethod
    def _not_null(cls, v):
        if v is None:
            raise ValueError("must not be null")
        return v

    @field_validator("starts_at")
    @classmethod
    def _to_utc(cls, v: datetime) -> datetime:
        return _utc(v)


class ContactOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    application_id: int
    name: str
    role: str | None
    email: str | None
    phone: str | None


class ContactIn(BaseModel):
    name: str = Field(min_length=1)
    role: str | None = None
    email: str | None = None
    phone: str | None = None


class ContactPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1)
    role: str | None = None
    email: str | None = None
    phone: str | None = None

    @field_validator("name")
    @classmethod
    def _not_null(cls, v):
        if v is None:
            raise ValueError("must not be null")
        return v


class AttachmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    application_id: int
    filename: str
    display_name: str
    stored_path: str
    kind: AttachmentKind
    created_at: datetime


class ApplicationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    status: AppStatus
    created_at: datetime
    updated_at: datetime
    salary_expectation: str | None
    channel: str | None
    notes: str | None
    posting: PostingOut
    last_status_change_at: datetime | None = None


class ApplicationDetailOut(ApplicationOut):
    status_changes: list[StatusChangeOut] = []
    appointments: list[AppointmentOut] = []
    contacts: list[ContactOut] = []
    attachments: list[AttachmentOut] = []


class ApplicationPatch(BaseModel):
    salary_expectation: str | None = None
    channel: str | None = None
    notes: str | None = None


class StatusChangeIn(BaseModel):
    to: AppStatus
    comment: str | None = None

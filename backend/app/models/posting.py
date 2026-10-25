from datetime import UTC, datetime

from sqlalchemy import JSON, ForeignKey, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, UTCDateTime
from app.models._types import str_enum
from app.models.enums import RunStatus, RunTrigger, TriageStatus


def utcnow() -> datetime:
    return datetime.now(UTC)


class Posting(Base):
    __tablename__ = "job_posting"
    __table_args__ = (
        UniqueConstraint("source", "external_id", name="uq_job_posting_source_external_id"),
        Index("ix_job_posting_first_seen_at", "first_seen_at"),
        Index("ix_job_posting_triage_status", "triage_status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str]
    external_id: Mapped[str]
    url: Mapped[str | None]
    title: Mapped[str | None]
    company: Mapped[str | None]
    location: Mapped[str | None]
    lat: Mapped[float | None]
    lon: Mapped[float | None]
    description: Mapped[str | None]
    published_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    first_seen_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    employment_type: Mapped[str | None]
    remote: Mapped[bool | None]
    contract_type: Mapped[str | None]
    raw: Mapped[dict | None] = mapped_column(JSON)
    triage_status: Mapped[TriageStatus] = mapped_column(
        str_enum(TriageStatus, "triage_status"), default=TriageStatus.new
    )
    triaged_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class SearchProfile(Base):
    __tablename__ = "search_profile"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]
    keywords: Mapped[list[str]] = mapped_column(JSON, default=list)
    locations: Mapped[list[str]] = mapped_column(JSON, default=list)
    radius_km: Mapped[int | None]
    employment_type: Mapped[str | None]
    remote: Mapped[bool | None]
    enabled: Mapped[bool] = mapped_column(default=True)
    schedule_hours: Mapped[int | None]
    plugins: Mapped[list[str]] = mapped_column(JSON, default=list)


class PostingMatch(Base):
    __tablename__ = "posting_match"

    posting_id: Mapped[int] = mapped_column(
        ForeignKey("job_posting.id", ondelete="CASCADE"), primary_key=True
    )
    profile_id: Mapped[int] = mapped_column(
        ForeignKey("search_profile.id", ondelete="CASCADE"), primary_key=True
    )
    matched_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class SearchRun(Base):
    __tablename__ = "search_run"

    id: Mapped[int] = mapped_column(primary_key=True)
    profile_id: Mapped[int | None] = mapped_column(
        ForeignKey("search_profile.id", ondelete="SET NULL")
    )
    plugin: Mapped[str]
    trigger: Mapped[RunTrigger] = mapped_column(str_enum(RunTrigger, "run_trigger"))
    started_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    status: Mapped[RunStatus] = mapped_column(
        str_enum(RunStatus, "run_status"), default=RunStatus.running
    )
    new_count: Mapped[int] = mapped_column(default=0)
    total_count: Mapped[int] = mapped_column(default=0)
    invalid_count: Mapped[int] = mapped_column(default=0)
    error: Mapped[str | None]

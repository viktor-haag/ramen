from datetime import datetime

from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, UTCDateTime
from app.models._types import str_enum
from app.models.enums import FitRating, FitStatus


class PostingFit(Base):
    """LLM fit evaluation of one posting against the user profile (at most one row per posting)."""

    __tablename__ = "posting_fit"

    posting_id: Mapped[int] = mapped_column(
        ForeignKey("job_posting.id", ondelete="CASCADE"), primary_key=True
    )
    rating: Mapped[FitRating | None] = mapped_column(str_enum(FitRating, "fit_rating"))
    explanation: Mapped[str | None]
    status: Mapped[FitStatus] = mapped_column(str_enum(FitStatus, "fit_status"))
    error: Mapped[str | None]
    profile_version: Mapped[int | None]
    evaluated_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

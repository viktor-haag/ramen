from datetime import datetime

from pydantic import BaseModel

from app.models import FitRating, FitStatus, PostingFit


class FitOut(BaseModel):
    rating: FitRating | None
    status: FitStatus
    error: str | None
    explanation: str | None
    evaluated_at: datetime | None
    outdated: bool  # evaluated against an older profile version (display only)


class FitItemOut(BaseModel):
    posting_id: int
    fit: FitOut | None


class FitStatusOut(BaseModel):
    profile: bool  # a non-blank profile exists
    configured: bool  # an LLM config resolves for the `fit` purpose
    active: int  # jobs queued or running in this process


class EnqueueOut(BaseModel):
    queued: int
    limit_exceeded: bool


class CancelOut(BaseModel):
    cancelled: int  # rows that were queued or running


class CountOut(BaseModel):
    count: int


def fit_out(row: PostingFit | None, current_version: int | None) -> FitOut | None:
    if row is None:
        return None
    outdated = (
        row.profile_version is not None and current_version is not None and row.profile_version < current_version
    )
    return FitOut(
        rating=row.rating, status=row.status, error=row.error, explanation=row.explanation,
        evaluated_at=row.evaluated_at, outdated=outdated,
    )

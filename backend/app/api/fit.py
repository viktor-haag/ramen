from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_session
from app.errors import AppError, ConflictError, NotFoundError, UnprocessableError
from app.fit.queue import FitQueue, ensure_ready
from app.models import FitStatus, Posting, PostingFit, UserProfile
from app.models.posting import utcnow
from app.schemas.feed import FeedFilter
from app.schemas.fit import CancelOut, CountOut, EnqueueOut, FitItemOut, FitStatusOut, fit_out
from app.services import feed as feed_service
from app.services import llm_configs, usage

router = APIRouter()

MAX_IDS = 200


def get_queue(request: Request) -> FitQueue:
    return request.app.state.fit_queue


@router.get("/fit/status", response_model=FitStatusOut)
def fit_status(session: Session = Depends(get_session), queue: FitQueue = Depends(get_queue)):
    profile = session.get(UserProfile, 1)
    try:
        llm_configs.resolve(session, "fit")
        configured = True
    except AppError:
        configured = False
    return FitStatusOut(
        profile=bool(profile and (profile.profile_markdown or "").strip()),
        configured=configured,
        active=queue.active_count(),
    )


@router.get("/fit", response_model=list[FitItemOut])
def get_fits(ids: str = "", session: Session = Depends(get_session)):
    try:
        wanted = list(dict.fromkeys(int(part) for part in ids.split(",") if part.strip()))
    except ValueError:
        raise UnprocessableError("validation_error", "ids must be comma-separated integers", {"field": "ids"})
    if len(wanted) > MAX_IDS:
        raise UnprocessableError("validation_error", f"At most {MAX_IDS} ids", {"field": "ids", "max": MAX_IDS})
    profile = session.get(UserProfile, 1)
    version = profile.version if profile else None
    rows = {r.posting_id: r for r in session.scalars(select(PostingFit).where(PostingFit.posting_id.in_(wanted)))}
    return [FitItemOut(posting_id=pid, fit=fit_out(rows.get(pid), version)) for pid in wanted]


def _bulk_candidates(session: Session, request: Request, f: FeedFilter) -> list[int]:
    """Feed matches without a fit row or with a failed one, in feed order (offset and limit ignored)."""
    matching = feed_service.matching_ids(session, f, request.app.state.geocoder)
    if not matching:
        return []
    blocked = set(
        session.scalars(
            select(PostingFit.posting_id).where(
                PostingFit.posting_id.in_(matching), PostingFit.status != FitStatus.error
            )
        )
    )
    return [pid for pid in matching if pid not in blocked]


@router.get("/fit/bulk/count", response_model=CountOut)
def bulk_count(request: Request, f: Annotated[FeedFilter, Query()], session: Session = Depends(get_session)):
    return CountOut(count=len(_bulk_candidates(session, request, f)))


@router.post("/fit/bulk", response_model=EnqueueOut)
def evaluate_bulk(
    request: Request,
    f: Annotated[FeedFilter, Query()],
    lang: Literal["en", "de"] = "en",
    session: Session = Depends(get_session),
    queue: FitQueue = Depends(get_queue),
):
    config_id = ensure_ready(session)
    hit = usage.limit_status(session, utcnow(), config_id)
    if hit is not None:  # R1: nothing is enqueued
        raise ConflictError(
            "daily_limit_reached", "The daily LLM usage limit has been reached",
            {"scope": hit.scope, "config_name": hit.config_name},
        )
    ids = _bulk_candidates(session, request, f)
    session.close()  # no session held while enqueueing (it writes in its own transaction)
    return EnqueueOut(queued=queue.enqueue(ids, lang=lang, kind="bulk"), limit_exceeded=False)


@router.post("/fit/cancel", response_model=CancelOut)
def cancel_evaluations(queue: FitQueue = Depends(get_queue)):
    return CancelOut(cancelled=queue.cancel_all())


@router.post("/fit/{posting_id}", response_model=EnqueueOut)
def evaluate_one(
    posting_id: int,
    lang: Literal["en", "de"] = "en",
    session: Session = Depends(get_session),
    queue: FitQueue = Depends(get_queue),
):
    config_id = ensure_ready(session)
    if session.get(Posting, posting_id) is None:
        raise NotFoundError("posting_not_found", "Posting not found", {"posting_id": posting_id})
    exceeded = usage.limit_exceeded(session, utcnow(), config_id)  # single evaluations only warn
    session.close()  # no session held while enqueueing (it writes in its own transaction)
    return EnqueueOut(queued=queue.enqueue([posting_id], lang=lang, kind="single"), limit_exceeded=exceeded)

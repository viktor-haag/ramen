from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy.orm import Session

from app.db import get_session
from app.schemas.feed import FeedFilter, FeedPage, PostingDetail
from app.services import feed as feed_service
from app.services import triage

router = APIRouter()


@router.get("/feed", response_model=FeedPage)
def get_feed(
    request: Request, f: Annotated[FeedFilter, Query()], session: Session = Depends(get_session)
) -> FeedPage:
    return feed_service.query_feed(session, f, request.app.state.geocoder)


@router.get("/postings/{posting_id}", response_model=PostingDetail)
def get_posting(posting_id: int, session: Session = Depends(get_session)) -> PostingDetail:
    return feed_service.get_posting(session, posting_id)


@router.post("/postings/{posting_id}/save")
def save(posting_id: int, session: Session = Depends(get_session)) -> dict:
    application = triage.save_posting(session, posting_id, datetime.now(UTC))
    session.commit()
    return {"application_id": application.id}


@router.post("/postings/{posting_id}/unsave", status_code=204)
def unsave(posting_id: int, session: Session = Depends(get_session)) -> Response:
    triage.unsave_posting(session, posting_id)
    session.commit()
    return Response(status_code=204)


@router.post("/postings/{posting_id}/dismiss", status_code=204)
def dismiss(posting_id: int, session: Session = Depends(get_session)) -> Response:
    triage.dismiss_posting(session, posting_id, datetime.now(UTC))
    session.commit()
    return Response(status_code=204)


@router.post("/postings/{posting_id}/undismiss", status_code=204)
def undismiss(posting_id: int, session: Session = Depends(get_session)) -> Response:
    triage.undismiss_posting(session, posting_id)
    session.commit()
    return Response(status_code=204)

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.db import get_session
from app.schemas.feed import FromUrlIn, ManualPostingIn, PostingOut
from app.services import postings

router = APIRouter()


@router.post("/postings")
def create_manual(data: ManualPostingIn, session: Session = Depends(get_session)) -> dict:
    application = postings.create_manual(session, data, datetime.now(UTC))
    session.commit()
    return {"application_id": application.id}


@router.post("/postings/from-url", response_model=PostingOut)
def from_url(body: FromUrlIn, request: Request, session: Session = Depends(get_session)) -> PostingOut:
    state = request.app.state
    result = postings.fetch_from_url(
        session, state.registry, state.runner_pool, body.url, datetime.now(UTC)
    )
    session.commit()
    return result

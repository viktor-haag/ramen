from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import AppStatus
from app.schemas.application import (
    ApplicationDetailOut,
    ApplicationOut,
    ApplicationPatch,
    StatusChangeIn,
)
from app.services import applications as svc

router = APIRouter()


@router.get("/applications", response_model=list[ApplicationOut])
def list_applications(
    status: Annotated[list[AppStatus] | None, Query()] = None,
    q: str | None = None,
    session: Session = Depends(get_session),
) -> list[ApplicationOut]:
    return svc.applications_out(session, svc.list_applications(session, status, q))


@router.get("/applications/{app_id}", response_model=ApplicationDetailOut)
def get_application(app_id: int, session: Session = Depends(get_session)) -> ApplicationDetailOut:
    return svc.application_detail(session, svc.get_application(session, app_id))


@router.patch("/applications/{app_id}", response_model=ApplicationDetailOut)
def patch_application(
    app_id: int, patch: ApplicationPatch, session: Session = Depends(get_session)
) -> ApplicationDetailOut:
    application = svc.update_application(session, app_id, patch, datetime.now(UTC))
    session.commit()
    return svc.application_detail(session, application)


@router.post("/applications/{app_id}/status", response_model=ApplicationDetailOut)
def change_status(
    app_id: int, body: StatusChangeIn, session: Session = Depends(get_session)
) -> ApplicationDetailOut:
    application = svc.change_status(session, app_id, body.to, body.comment, datetime.now(UTC))
    session.commit()
    return svc.application_detail(session, application)


@router.post("/applications/{app_id}/reopen", response_model=ApplicationDetailOut)
def reopen(
    app_id: int, body: StatusChangeIn, session: Session = Depends(get_session)
) -> ApplicationDetailOut:
    application = svc.reopen(session, app_id, body.to, body.comment, datetime.now(UTC))
    session.commit()
    return svc.application_detail(session, application)

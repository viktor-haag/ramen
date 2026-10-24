from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import RunStatus
from app.schemas.run import RunOut
from app.services import profiles

router = APIRouter()


@router.get("/runs", response_model=list[RunOut])
def list_runs(
    profile_id: int | None = None,
    status: RunStatus | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(get_session),
) -> list[RunOut]:
    return profiles.list_runs(session, profile_id=profile_id, status=status, limit=limit)


@router.get("/runs/active", response_model=list[RunOut])
def active_runs(session: Session = Depends(get_session)) -> list[RunOut]:
    return profiles.list_runs(session, status=RunStatus.running, limit=200)

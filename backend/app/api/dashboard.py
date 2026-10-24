from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_session
from app.schemas.dashboard import DashboardOut
from app.services import dashboard as svc

router = APIRouter()


@router.get("/dashboard", response_model=DashboardOut)
def get_dashboard(session: Session = Depends(get_session)) -> DashboardOut:
    return svc.dashboard(session, datetime.now(UTC))

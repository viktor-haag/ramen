from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_session
from app.schemas.settings import SettingsIn, SettingsOut
from app.services import settings as settings_service

router = APIRouter()


@router.get("/settings", response_model=SettingsOut)
def read(session: Session = Depends(get_session)) -> SettingsOut:
    return settings_service.get_settings(session)


@router.put("/settings", response_model=SettingsOut)
def update(data: SettingsIn, session: Session = Depends(get_session)) -> SettingsOut:
    out = settings_service.update_settings(session, data)
    session.commit()
    return out

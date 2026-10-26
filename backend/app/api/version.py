from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.db import get_session
from app.errors import ConflictError
from app.schemas.version import VersionOut
from app.services import settings as settings_service
from app.services.updates import UpdateStatus

router = APIRouter()


def _out(request: Request, session: Session, status: UpdateStatus) -> VersionOut:
    env_enabled = request.app.state.settings.update_check
    return VersionOut(
        current=status.current,
        latest=status.latest,
        update_available=status.update_available,
        release_url=status.release_url,
        published_at=status.published_at,
        checked_at=status.checked_at,
        error=status.error,
        enabled=env_enabled and settings_service.get_settings(session).update_check,
        disabled_by_env=not env_enabled,
        pdf_available=request.app.state.cover_letter_jobs.compiler.available(),
    )


@router.get("/version", response_model=VersionOut)
def read(request: Request, session: Session = Depends(get_session)) -> VersionOut:
    return _out(request, session, request.app.state.update_checker.status())


@router.post("/version/check", response_model=VersionOut)
def check_now(request: Request, session: Session = Depends(get_session)) -> VersionOut:
    """Check immediately; works with the app setting off, only the env flag blocks it."""
    if not request.app.state.settings.update_check:
        raise ConflictError("update_check_disabled", "Update checks are disabled by the server configuration")
    return _out(request, session, request.app.state.update_checker.check())

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import RunTrigger, SearchProfile
from app.schemas.profile import ProfileIn, ProfileOut
from app.schemas.run import RunStartOut
from app.services import profiles

router = APIRouter()


@router.get("/profiles", response_model=list[ProfileOut])
def list_all(session: Session = Depends(get_session)) -> list[ProfileOut]:
    return profiles.list_profiles(session)


@router.post("/profiles", response_model=ProfileOut)
def create(data: ProfileIn, request: Request, session: Session = Depends(get_session)) -> ProfileOut:
    profile = profiles.create_profile(session, request.app.state.registry, data)
    session.commit()
    request.app.state.scheduler.sync()
    return profiles.profile_out(session, profile)


@router.get("/profiles/{profile_id}", response_model=ProfileOut)
def read(profile_id: int, session: Session = Depends(get_session)) -> ProfileOut:
    return profiles.profile_out(session, profiles.get_profile(session, profile_id))


@router.put("/profiles/{profile_id}", response_model=ProfileOut)
def update(
    profile_id: int, data: ProfileIn, request: Request, session: Session = Depends(get_session)
) -> ProfileOut:
    profile = profiles.update_profile(session, request.app.state.registry, profile_id, data)
    session.commit()
    request.app.state.scheduler.sync()
    return profiles.profile_out(session, profile)


@router.delete("/profiles/{profile_id}", status_code=204)
def delete(profile_id: int, request: Request, session: Session = Depends(get_session)) -> Response:
    profiles.delete_profile(session, profile_id)
    session.commit()
    request.app.state.scheduler.sync()
    return Response(status_code=204)


@router.post("/profiles/{profile_id}/run", response_model=RunStartOut)
def run_profile(profile_id: int, request: Request, session: Session = Depends(get_session)) -> RunStartOut:
    profile = profiles.get_profile(session, profile_id)  # 404; RunService skips unknown ids silently
    service = request.app.state.run_service
    run_ids = service.start_runs([profile_id], RunTrigger.manual)
    already = not run_ids and profiles.skipped_running(session, service, [profile], run_ids)
    return RunStartOut(run_ids=run_ids, already_running=already)


@router.post("/runs", response_model=RunStartOut)
def run_all(request: Request, session: Session = Depends(get_session)) -> RunStartOut:
    service = request.app.state.run_service
    run_ids = service.start_runs(None, RunTrigger.manual)
    enabled = list(session.scalars(select(SearchProfile).where(SearchProfile.enabled.is_(True))))
    return RunStartOut(run_ids=run_ids, already_running=profiles.skipped_running(session, service, enabled, run_ids))

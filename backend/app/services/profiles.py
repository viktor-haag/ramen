from collections.abc import Collection
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.errors import NotFoundError, UnprocessableError
from app.models import RunStatus, SearchProfile, SearchRun
from app.plugins.base import Capability
from app.plugins.registry import PluginRegistry
from app.runner.service import RunService
from app.schemas.profile import ProfileIn, ProfileOut
from app.schemas.run import RunOut


def validate_plugins(registry: PluginRegistry, names: list[str]) -> None:
    """Every name must be a usable plugin with the SEARCH capability."""
    known = {i.name for i in registry.usable() if Capability.SEARCH in i.capabilities}
    unknown = [n for n in dict.fromkeys(names) if n not in known]
    if unknown:
        raise UnprocessableError("unknown_plugin", f"Unknown plugins: {', '.join(unknown)}", {"names": unknown})


def _last_run_at(session: Session, profile_ids: list[int]) -> dict:
    rows = session.execute(
        select(SearchRun.profile_id, func.max(SearchRun.started_at))
        .where(SearchRun.profile_id.in_(profile_ids))
        .group_by(SearchRun.profile_id)
    )
    return dict(rows.all())


def _out(profile: SearchProfile, last_run_at) -> ProfileOut:
    return ProfileOut(
        id=profile.id, name=profile.name, keywords=list(profile.keywords or []), location=profile.location,
        radius_km=profile.radius_km, employment_type=profile.employment_type, remote=profile.remote,
        enabled=profile.enabled, schedule_hours=profile.schedule_hours,
        plugins=list(profile.plugins or []), last_run_at=last_run_at,
    )


def get_profile(session: Session, profile_id: int) -> SearchProfile:
    profile = session.get(SearchProfile, profile_id)
    if profile is None:
        raise NotFoundError("profile_not_found", f"Profile {profile_id} not found", {"id": profile_id})
    return profile


def list_profiles(session: Session) -> list[ProfileOut]:
    profiles = session.scalars(select(SearchProfile).order_by(SearchProfile.id)).all()
    last = _last_run_at(session, [p.id for p in profiles])
    return [_out(p, last.get(p.id)) for p in profiles]


def profile_out(session: Session, profile: SearchProfile) -> ProfileOut:
    return _out(profile, _last_run_at(session, [profile.id]).get(profile.id))


def create_profile(session: Session, registry: PluginRegistry, data: ProfileIn) -> SearchProfile:
    validate_plugins(registry, data.plugins)
    profile = SearchProfile(**data.model_dump())
    session.add(profile)
    session.flush()
    return profile


def update_profile(session: Session, registry: PluginRegistry, profile_id: int, data: ProfileIn) -> SearchProfile:
    profile = get_profile(session, profile_id)
    validate_plugins(registry, data.plugins)
    for key, value in data.model_dump().items():
        setattr(profile, key, value)
    session.flush()
    return profile


def delete_profile(session: Session, profile_id: int) -> None:
    session.delete(get_profile(session, profile_id))
    session.flush()


def skipped_running(
    session: Session, run_service: RunService, profiles: list[SearchProfile], created_ids: list[int]
) -> bool:
    """True if some effective (profile, plugin) pair has a running run that this start did not create."""
    pairs = {(p.id, i.name) for p in profiles for i in run_service.effective_plugins(session, p)}
    if not pairs:
        return False
    running = session.execute(
        select(SearchRun.id, SearchRun.profile_id, SearchRun.plugin).where(
            SearchRun.status == RunStatus.running,
            SearchRun.profile_id.in_({pid for pid, _ in pairs}),
        )
    )
    created = set(created_ids)
    return any(rid not in created and (pid, plugin) in pairs for rid, pid, plugin in running)


def list_runs(
    session: Session,
    *,
    profile_id: int | None = None,
    status: RunStatus | None = None,
    statuses: Collection[RunStatus] | None = None,
    since: datetime | None = None,
    limit: int = 50,
) -> list[RunOut]:
    stmt = (
        select(SearchRun, SearchProfile.name)
        .join(SearchProfile, SearchProfile.id == SearchRun.profile_id, isouter=True)
        .order_by(SearchRun.started_at.desc(), SearchRun.id.desc())
        .limit(limit)
    )
    if profile_id is not None:
        stmt = stmt.where(SearchRun.profile_id == profile_id)
    if status is not None:
        stmt = stmt.where(SearchRun.status == status)
    if statuses is not None:
        stmt = stmt.where(SearchRun.status.in_(statuses))
    if since is not None:
        stmt = stmt.where(SearchRun.started_at >= since)
    return [
        RunOut(profile_name=name, **{f: getattr(run, f) for f in RunOut.model_fields if f != "profile_name"})
        for run, name in session.execute(stmt)
    ]

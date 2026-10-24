from datetime import datetime

from pydantic import BaseModel

from app.models import RunStatus, RunTrigger


class RunOut(BaseModel):
    id: int
    profile_id: int | None
    profile_name: str | None
    plugin: str
    trigger: RunTrigger
    started_at: datetime
    finished_at: datetime | None
    status: RunStatus
    new_count: int
    total_count: int
    invalid_count: int
    error: str | None


class RunStartOut(BaseModel):
    run_ids: list[int]
    already_running: bool

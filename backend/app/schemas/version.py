from datetime import datetime

from pydantic import BaseModel


class VersionOut(BaseModel):
    current: str
    latest: str | None
    update_available: bool
    release_url: str | None
    published_at: datetime | None
    checked_at: datetime | None
    error: str | None
    enabled: bool  # env flag on and app setting on
    disabled_by_env: bool

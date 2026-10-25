from sqlalchemy.orm import Session

from app.models import AppSetting
from app.schemas.settings import SettingsIn, SettingsOut

DEFAULTS: dict[str, object] = {
    "fit_auto": False,
    "fit_concurrency": 2,
    "daily_limit_kind": "none",
    "daily_limit_value": None,
    "fit_language": "en",
    "update_check": True,
}


def get_settings(session: Session) -> SettingsOut:
    stored = {row.key: row.value for row in session.query(AppSetting)}
    return SettingsOut.model_validate({**DEFAULTS, **{k: v for k, v in stored.items() if k in DEFAULTS}})


def update_settings(session: Session, data: SettingsIn) -> SettingsOut:
    for key, value in data.model_dump().items():
        row = session.get(AppSetting, key)
        if row is None:
            session.add(AppSetting(key=key, value=value))
        else:
            row.value = value
    session.flush()
    return get_settings(session)

from fastapi.encoders import jsonable_encoder
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.errors import ConflictError, UnprocessableError
from app.models import PluginSetting
from app.plugins.loader import PluginInfo
from app.plugins.registry import PluginRegistry
from app.runner.failures import split_timeout
from app.schemas.plugin import PluginOut


def _json_schema(info: PluginInfo) -> dict | None:
    if info.error is not None or info.settings_schema is None:
        return None
    schema = info.settings_schema.model_json_schema()
    schema.setdefault("properties", {})["timeout_seconds"] = {
        "type": "integer", "minimum": 1, "default": info.timeout_seconds, "title": "Timeout (seconds)",
    }
    return schema


def _current_settings(info: PluginInfo, stored: dict | None) -> dict:
    """Stored values filled up with the schema defaults, plus the effective timeout."""
    if info.error is not None or info.settings_schema is None:
        return {}
    timeout, rest = split_timeout(info, stored)
    try:
        values = info.settings_schema.model_validate(rest).model_dump(mode="json")
    except ValidationError:  # schema changed since saving: show what is stored
        values = rest
    return {**values, "timeout_seconds": timeout}


def _out(key: str, info: PluginInfo, row: PluginSetting | None) -> PluginOut:
    return PluginOut(
        name=key,
        display_name=info.display_name,
        capabilities=sorted(info.capabilities),
        url_patterns=info.url_patterns,
        enabled=row.enabled if row is not None else info.enabled_by_default,
        settings=_current_settings(info, row.settings if row is not None else None),
        settings_schema=_json_schema(info),
        error=info.error,
        notice=info.notice,
    )


def list_plugins(session: Session, registry: PluginRegistry) -> list[PluginOut]:
    rows = {r.plugin: r for r in session.query(PluginSetting)}
    return [_out(key, info, rows.get(key)) for key, info in registry.items()]


def _validation_error(errors: list[dict]) -> UnprocessableError:
    return UnprocessableError(
        "validation_error", "Validation error",
        {"errors": jsonable_encoder(errors, custom_encoder={Exception: str})},
    )


def update_plugin(
    session: Session, registry: PluginRegistry, name: str, enabled: bool, settings: dict
) -> PluginOut:
    info = registry.get(name)
    if info.error is not None:
        raise ConflictError("plugin_not_loadable", f"Plugin '{name}' could not be loaded", {"name": name})
    rest = dict(settings)
    timeout = rest.pop("timeout_seconds", None)
    errors: list[dict] = []
    values: dict = {}
    try:
        values = info.settings_schema.model_validate(rest).model_dump(mode="json")
    except ValidationError as exc:
        errors.extend({**e, "loc": ("body", "settings", *e["loc"])} for e in exc.errors())
    if "timeout_seconds" in settings and (
        isinstance(timeout, bool) or not isinstance(timeout, int) or timeout < 1
    ):
        errors.append({
            "type": "int_parsing" if not isinstance(timeout, int) or isinstance(timeout, bool) else "greater_than_equal",
            "loc": ("body", "settings", "timeout_seconds"),
            "msg": "Input should be an integer greater than or equal to 1",
            "input": timeout,
        })
    if errors:
        raise _validation_error(errors)
    if timeout is not None:
        values["timeout_seconds"] = timeout
    row = session.get(PluginSetting, name)
    if row is None:
        row = PluginSetting(plugin=name)
        session.add(row)
    row.enabled = enabled
    row.settings = values
    session.flush()
    return _out(name, info, row)

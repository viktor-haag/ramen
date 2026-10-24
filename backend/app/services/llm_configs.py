from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.errors import ConflictError, NotFoundError
from app.llm.factory import ConfigData
from app.models import LLMConfig, LLMProvider, LLMPurpose, LLMPurposeKind, LLMUsage
from app.schemas.llm import LLMConfigIn, LLMConfigOut, PurposesIn, PurposesOut


def mask_key(key: str | None) -> str | None:
    """'…' + last 4 characters; a key of 4 characters or fewer is shown as '…' alone."""
    if not key:
        return None
    return "…" + key[-4:] if len(key) > 4 else "…"


def to_out(cfg: LLMConfig) -> LLMConfigOut:
    return LLMConfigOut(
        id=cfg.id, name=cfg.name, provider=cfg.provider, base_url=cfg.base_url,
        api_key=mask_key(cfg.api_key), has_api_key=bool(cfg.api_key), model=cfg.model,
        thinking=cfg.thinking, supports_images=cfg.supports_images, extra_body=dict(cfg.extra_body or {}),
        extra_headers=dict(cfg.extra_headers or {}), price_in=cfg.price_in, price_out=cfg.price_out,
        is_default=cfg.is_default,
    )


def to_data(cfg: LLMConfig) -> ConfigData:
    return ConfigData(
        provider=cfg.provider.value, model=cfg.model, supports_images=cfg.supports_images, id=cfg.id,
        name=cfg.name, base_url=cfg.base_url, api_key=cfg.api_key, thinking=cfg.thinking.value,
        extra_body=dict(cfg.extra_body or {}), extra_headers=dict(cfg.extra_headers or {}),
        price_in=cfg.price_in, price_out=cfg.price_out,
    )


def default_supports_images(provider: LLMProvider) -> bool:
    return provider != LLMProvider.openai_compatible


def list_configs(session: Session) -> list[LLMConfig]:
    return list(session.scalars(select(LLMConfig).order_by(LLMConfig.id)))


def get_config(session: Session, config_id: int) -> LLMConfig:
    cfg = session.get(LLMConfig, config_id)
    if cfg is None:
        raise NotFoundError("llm_config_not_found", "LLM configuration not found")
    return cfg


def _name_taken() -> ConflictError:
    return ConflictError("llm_config_name_taken", "An LLM configuration with this name already exists")


def _check_name_free(session: Session, name: str, own_id: int | None = None) -> None:
    clash = session.scalar(select(LLMConfig.id).where(LLMConfig.name == name))
    if clash is not None and clash != own_id:
        raise _name_taken()


def create_config(session: Session, data: LLMConfigIn) -> LLMConfig:
    _check_name_free(session, data.name)
    first = session.scalar(select(LLMConfig.id).limit(1)) is None
    cfg = LLMConfig(
        name=data.name, provider=data.provider, base_url=data.base_url, api_key=data.api_key or None,
        model=data.model, thinking=data.thinking,
        supports_images=(
            data.supports_images if data.supports_images is not None else default_supports_images(data.provider)
        ),
        extra_body=data.extra_body, extra_headers=data.extra_headers, price_in=data.price_in,
        price_out=data.price_out, is_default=first,
    )
    session.add(cfg)
    try:
        session.flush()
    except IntegrityError:  # lost a race against the unique name index
        session.rollback()
        raise _name_taken() from None
    return cfg


def update_config(session: Session, config_id: int, data: LLMConfigIn) -> LLMConfig:
    cfg = get_config(session, config_id)
    _check_name_free(session, data.name, cfg.id)
    if data.api_key is not None:  # omitted keeps the key, "" clears it
        cfg.api_key = data.api_key or None
    if data.supports_images is not None:
        cfg.supports_images = data.supports_images
    elif data.provider != cfg.provider:
        cfg.supports_images = default_supports_images(data.provider)
    cfg.name, cfg.provider, cfg.base_url, cfg.model = data.name, data.provider, data.base_url, data.model
    cfg.thinking, cfg.extra_body, cfg.extra_headers = data.thinking, data.extra_body, data.extra_headers
    cfg.price_in, cfg.price_out = data.price_in, data.price_out
    try:
        session.flush()
    except IntegrityError:
        session.rollback()
        raise _name_taken() from None
    return cfg


def set_default(session: Session, config_id: int) -> LLMConfig:
    cfg = get_config(session, config_id)
    session.execute(update(LLMConfig).where(LLMConfig.id != cfg.id).values(is_default=False))
    cfg.is_default = True
    session.flush()
    return cfg


def delete_config(session: Session, config_id: int) -> None:
    cfg = get_config(session, config_id)
    others = session.scalar(select(LLMConfig.id).where(LLMConfig.id != cfg.id).limit(1)) is not None
    if others:
        assigned = session.scalar(select(LLMPurpose.purpose).where(LLMPurpose.config_id == cfg.id).limit(1))
        if cfg.is_default or assigned is not None:
            raise ConflictError(
                "llm_config_in_use",
                "The default configuration or one assigned to a purpose cannot be deleted",
                {"name": cfg.name},
            )
    # Explicit instead of relying on ON DELETE SET NULL alone.
    session.execute(update(LLMPurpose).where(LLMPurpose.config_id == cfg.id).values(config_id=None))
    session.execute(update(LLMUsage).where(LLMUsage.config_id == cfg.id).values(config_id=None))
    session.delete(cfg)
    session.flush()


def get_purposes(session: Session) -> PurposesOut:
    stored = {row.purpose.value: row.config_id for row in session.scalars(select(LLMPurpose))}
    return PurposesOut(**{p.value: stored.get(p.value) for p in LLMPurposeKind})


def set_purposes(session: Session, data: PurposesIn) -> PurposesOut:
    values = data.model_dump()
    for config_id in values.values():
        if config_id is not None:
            get_config(session, config_id)  # 404 before anything is written
    for purpose in LLMPurposeKind:
        row = session.get(LLMPurpose, purpose)
        if row is None:
            session.add(LLMPurpose(purpose=purpose, config_id=values[purpose.value]))
        else:
            row.config_id = values[purpose.value]
    session.flush()
    return get_purposes(session)


def resolve(session: Session, purpose: str | LLMPurposeKind) -> ConfigData:
    """The config for a purpose; an unassigned purpose uses the default config."""
    kind = LLMPurposeKind(purpose)
    row = session.get(LLMPurpose, kind)
    cfg = session.get(LLMConfig, row.config_id) if row is not None and row.config_id is not None else None
    if cfg is None:
        cfg = session.scalar(select(LLMConfig).where(LLMConfig.is_default.is_(True)))
    if cfg is None:
        raise ConflictError("llm_not_configured", "No LLM configuration exists")
    return to_data(cfg)

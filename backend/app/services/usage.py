"""LLM usage records and the daily limits (global and per config).

A day / month is a calendar day / month in Europe/Berlin.
"""
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.llm.base import LLMResult, estimate_tokens
from app.models import LLMConfig, LLMUsage
from app.schemas.llm import ConfigUsageOut, LimitOut, UsageOut, UsageTotals
from app.services import settings as settings_service

BERLIN = ZoneInfo("Europe/Berlin")
USAGE_PURPOSE_TEST = "test"  # connection tests of the settings page


def record(
    session: Session, *, config_id: int | None, purpose: str, result: LLMResult | None, ok: bool, chars_in: int = 0
) -> LLMUsage:
    """Add a usage row (flushed, not committed). Without a result the input is estimated from `chars_in`."""
    if result is not None:
        in_tok, out_tok, estimated = result.input_tokens, result.output_tokens, result.estimated
    else:
        in_tok, out_tok, estimated = estimate_tokens(chars_in), 0, chars_in > 0
    row = LLMUsage(
        config_id=config_id, purpose=purpose, input_tokens=in_tok, output_tokens=out_tok, estimated=estimated, ok=ok
    )
    session.add(row)
    session.flush()
    return row


def _berlin_midnight_utc(year: int, month: int, day: int) -> datetime:
    return datetime(year, month, day, tzinfo=BERLIN).astimezone(UTC)


def _boundaries(now: datetime) -> tuple[datetime, datetime]:
    local = now.astimezone(BERLIN)
    return _berlin_midnight_utc(local.year, local.month, local.day), _berlin_midnight_utc(local.year, local.month, 1)


_ALL = object()  # `_totals` filter: every usage row


@dataclass(frozen=True)
class LimitHit:
    """Which daily limit is reached: the global one or that of the config `config_name`."""

    scope: Literal["global", "config"]
    config_name: str | None


def _totals(session: Session, start: datetime, now: datetime, config_id: object = _ALL) -> UsageTotals:
    """Totals from `start` to `now`; `config_id` limits them to one config (None: rows of deleted configs)."""
    query = (
        select(LLMUsage.input_tokens, LLMUsage.output_tokens, LLMConfig.price_in, LLMConfig.price_out)
        .join(LLMConfig, LLMUsage.config_id == LLMConfig.id, isouter=True)
        .where(LLMUsage.at >= start, LLMUsage.at <= now)
    )
    if config_id is None:
        query = query.where(LLMUsage.config_id.is_(None))
    elif config_id is not _ALL:
        query = query.where(LLMUsage.config_id == config_id)
    rows = session.execute(query).all()
    tokens_in = sum(r.input_tokens for r in rows)
    tokens_out = sum(r.output_tokens for r in rows)
    priced = [r for r in rows if r.price_in is not None and r.price_out is not None]
    eur = sum((r.input_tokens * r.price_in + r.output_tokens * r.price_out) / 1_000_000 for r in priced)
    return UsageTotals(input_tokens=tokens_in, output_tokens=tokens_out, eur=eur if priced else None)


def _reached(kind: str, value: float | None, today: UsageTotals) -> bool:
    if value is None:
        return False
    if kind == "tokens":
        return today.input_tokens + today.output_tokens >= value
    if kind == "eur":
        return (today.eur or 0.0) >= value
    return False


def _global_limit(session: Session) -> LimitOut:
    cfg = settings_service.get_settings(session)
    return LimitOut(kind=cfg.daily_limit_kind, value=cfg.daily_limit_value)


def _config_limit(cfg: LLMConfig) -> LimitOut:
    kind = cfg.daily_limit_kind if cfg.daily_limit_kind in ("tokens", "eur") else "none"
    return LimitOut(kind=kind, value=cfg.daily_limit_value if kind != "none" else None)


def limit_status(session: Session, now: datetime, config_id: int | None = None) -> LimitHit | None:
    """The reached daily limit: the global one first, then that of config `config_id` (its own usage today)."""
    day_start, _ = _boundaries(now)
    limit = _global_limit(session)
    if limit.kind != "none" and _reached(limit.kind, limit.value, _totals(session, day_start, now)):
        return LimitHit("global", None)
    cfg = session.get(LLMConfig, config_id) if config_id is not None else None
    if cfg is not None:
        own = _config_limit(cfg)
        if own.kind != "none" and _reached(own.kind, own.value, _totals(session, day_start, now, cfg.id)):
            return LimitHit("config", cfg.name)
    return None


def limit_exceeded(session: Session, now: datetime, config_id: int | None = None) -> bool:
    return limit_status(session, now, config_id) is not None


def _per_config(session: Session, day_start: datetime, month_start: datetime, now: datetime) -> list[ConfigUsageOut]:
    rows = []
    configs = sorted(session.scalars(select(LLMConfig)), key=lambda c: (c.name.casefold(), c.id))
    for cfg in configs:
        today = _totals(session, day_start, now, cfg.id)
        limit = _config_limit(cfg)
        rows.append(ConfigUsageOut(
            config_id=cfg.id, name=cfg.name, deleted=False, today=today,
            month=_totals(session, month_start, now, cfg.id), limit=limit,
            limit_exceeded=_reached(limit.kind, limit.value, today),
        ))
    # one row for usage of deleted configs, shown only when there is some in the displayed month
    orphaned = session.scalar(
        select(LLMUsage.id)
        .where(LLMUsage.config_id.is_(None), LLMUsage.at >= month_start, LLMUsage.at <= now)
        .limit(1)
    )
    if orphaned is not None:
        rows.append(ConfigUsageOut(
            config_id=None, name=None, deleted=True, today=_totals(session, day_start, now, None),
            month=_totals(session, month_start, now, None), limit=LimitOut(kind="none", value=None),
            limit_exceeded=False,
        ))
    return rows


def summary(session: Session, now: datetime) -> UsageOut:
    day_start, month_start = _boundaries(now)
    today = _totals(session, day_start, now)
    limit = _global_limit(session)
    return UsageOut(
        today=today, month=_totals(session, month_start, now), limit=limit,
        limit_exceeded=_reached(limit.kind, limit.value, today),
        per_config=_per_config(session, day_start, month_start, now),
    )

"""LLM usage records and the daily limit. A day / month is a calendar day / month in Europe/Berlin."""
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.llm.base import LLMResult, estimate_tokens
from app.models import LLMConfig, LLMUsage
from app.schemas.llm import LimitOut, UsageOut, UsageTotals
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


def _totals(session: Session, start: datetime, now: datetime) -> UsageTotals:
    rows = session.execute(
        select(LLMUsage.input_tokens, LLMUsage.output_tokens, LLMConfig.price_in, LLMConfig.price_out)
        .join(LLMConfig, LLMUsage.config_id == LLMConfig.id, isouter=True)
        .where(LLMUsage.at >= start, LLMUsage.at <= now)
    ).all()
    tokens_in = sum(r.input_tokens for r in rows)
    tokens_out = sum(r.output_tokens for r in rows)
    priced = [r for r in rows if r.price_in is not None and r.price_out is not None]
    eur = sum((r.input_tokens * r.price_in + r.output_tokens * r.price_out) / 1_000_000 for r in priced)
    return UsageTotals(input_tokens=tokens_in, output_tokens=tokens_out, eur=eur if priced else None)


def summary(session: Session, now: datetime) -> UsageOut:
    day_start, month_start = _boundaries(now)
    today = _totals(session, day_start, now)
    cfg = settings_service.get_settings(session)
    kind, value = cfg.daily_limit_kind, cfg.daily_limit_value
    if kind == "tokens":
        exceeded = value is not None and today.input_tokens + today.output_tokens >= value
    elif kind == "eur":
        exceeded = value is not None and (today.eur or 0.0) >= value
    else:
        exceeded = False
    return UsageOut(
        today=today, month=_totals(session, month_start, now), limit=LimitOut(kind=kind, value=value),
        limit_exceeded=exceeded,
    )


def limit_exceeded(session: Session, now: datetime) -> bool:
    return summary(session, now).limit_exceeded

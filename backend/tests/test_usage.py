from datetime import UTC, datetime

import pytest

from app.errors import AppError, ConflictError
from app.llm.base import LLMResult, Message
from app.llm.errors import LLMError
from app.llm.factory import ConfigData
from app.llm.runner import llm_call
from app.models import LLMConfig, LLMProvider, LLMUsage
from app.schemas.settings import SettingsIn
from app.services import settings as settings_service
from app.services import usage

NOW = datetime(2026, 10, 24, 12, 0, tzinfo=UTC)


def add_config(session, name="c", price_in=None, price_out=None) -> LLMConfig:
    cfg = LLMConfig(name=name, provider=LLMProvider.anthropic, model="m", api_key="sk-test-1234",
                    price_in=price_in, price_out=price_out, is_default=True)
    session.add(cfg)
    session.commit()
    return cfg


def add_usage(session, at, cfg_id=None, i=100, o=50, ok=True):
    session.add(LLMUsage(at=at, config_id=cfg_id, purpose="fit", input_tokens=i, output_tokens=o, ok=ok))
    session.commit()


def test_record_with_result_and_failure(session):
    cfg = add_config(session)
    usage.record(session, config_id=cfg.id, purpose="fit", result=LLMResult("x", 10, 4, False), ok=True)
    usage.record(session, config_id=cfg.id, purpose="fit", result=LLMResult("x", 3, 1, True), ok=True)
    usage.record(session, config_id=cfg.id, purpose="fit", result=None, ok=False, chars_in=41)
    usage.record(session, config_id=cfg.id, purpose="fit", result=None, ok=False)
    rows = session.query(LLMUsage).order_by(LLMUsage.id).all()
    assert [(r.input_tokens, r.output_tokens, r.estimated, r.ok) for r in rows] == [
        (10, 4, False, True), (3, 1, True, True), (11, 0, True, False), (0, 0, False, False)]
    assert all(r.at.tzinfo is not None for r in rows)


def test_berlin_day_boundary(session):
    """22:30 UTC on Oct 23 is 00:30 on Oct 24 in Berlin (CEST); 21:30 UTC is 23:30 on Oct 23."""
    after = datetime(2026, 10, 23, 22, 30, tzinfo=UTC)
    before = datetime(2026, 10, 23, 21, 30, tzinfo=UTC)
    add_usage(session, after, i=100, o=10)
    add_usage(session, before, i=1000, o=100)
    now = datetime(2026, 10, 24, 6, 0, tzinfo=UTC)
    out = usage.summary(session, now)
    assert (out.today.input_tokens, out.today.output_tokens) == (100, 10)
    assert (out.month.input_tokens, out.month.output_tokens) == (1100, 110)
    # seen from the evening before, only the earlier record exists
    out = usage.summary(session, datetime(2026, 10, 23, 21, 45, tzinfo=UTC))
    assert (out.today.input_tokens, out.today.output_tokens) == (1000, 100)


def test_berlin_day_boundary_in_winter_time(session):
    # CET (UTC+1): 22:59 UTC on Jan 15 is still Jan 15, 23:00 UTC is already Jan 16
    add_usage(session, datetime(2026, 1, 15, 22, 59, tzinfo=UTC), i=1, o=0)
    add_usage(session, datetime(2026, 1, 15, 23, 0, tzinfo=UTC), i=10, o=0)
    out = usage.summary(session, datetime(2026, 1, 16, 8, 0, tzinfo=UTC))
    assert out.today.input_tokens == 10 and out.month.input_tokens == 11


def test_month_boundary_is_berlin_midnight(session):
    # 2026-09-30 22:30 UTC = Oct 1, 00:30 Berlin -> October; 21:30 UTC = Sep 30, 23:30 -> September
    add_usage(session, datetime(2026, 9, 30, 22, 30, tzinfo=UTC), i=5, o=0)
    add_usage(session, datetime(2026, 9, 30, 21, 30, tzinfo=UTC), i=7, o=0)
    out = usage.summary(session, datetime(2026, 10, 15, 12, 0, tzinfo=UTC))
    assert out.month.input_tokens == 5


def test_eur_only_for_configs_with_prices(session):
    priced = add_config(session, "p", price_in=3.0, price_out=15.0)
    free = LLMConfig(name="f", provider=LLMProvider.openai, model="m", api_key="k")
    half = LLMConfig(name="h", provider=LLMProvider.openai, model="m", api_key="k", price_in=1.0)
    session.add_all([free, half])
    session.commit()
    assert usage.summary(session, NOW).today.eur is None  # no usage at all
    add_usage(session, NOW, free.id, i=1_000_000, o=1_000_000)
    add_usage(session, NOW, half.id, i=1_000_000, o=0)
    add_usage(session, NOW, None, i=1_000_000, o=0)  # deleted config
    out = usage.summary(session, NOW)
    assert out.today.eur is None and out.today.input_tokens == 3_000_000
    add_usage(session, NOW, priced.id, i=2_000_000, o=1_000_000)
    out = usage.summary(session, NOW)
    assert out.today.eur == pytest.approx(2 * 3.0 + 15.0) and out.month.eur == pytest.approx(21.0)


def set_limit(session, kind, value):
    settings_service.update_settings(session, SettingsIn(
        fit_auto=False, fit_concurrency=2, daily_limit_kind=kind, daily_limit_value=value))
    session.commit()


def test_limit_exceeded_tokens(session):
    assert usage.limit_exceeded(session, NOW) is False  # kind none
    set_limit(session, "tokens", 1000)
    add_usage(session, NOW, i=600, o=300)
    assert usage.limit_exceeded(session, NOW) is False
    add_usage(session, NOW, i=100, o=0)
    assert usage.limit_exceeded(session, NOW) is True
    out = usage.summary(session, NOW)
    assert out.limit_exceeded is True and out.limit.kind == "tokens" and out.limit.value == 1000
    # yesterday's usage (Berlin) does not count today
    assert usage.limit_exceeded(session, datetime(2026, 10, 25, 12, 0, tzinfo=UTC)) is False


def test_limit_exceeded_eur_ignores_unpriced(session):
    priced = add_config(session, "p", price_in=10.0, price_out=10.0)
    free = LLMConfig(name="f", provider=LLMProvider.openai, model="m", api_key="k")
    session.add(free)
    session.commit()
    set_limit(session, "eur", 5.0)
    add_usage(session, NOW, free.id, i=50_000_000, o=0)
    assert usage.limit_exceeded(session, NOW) is False
    add_usage(session, NOW, priced.id, i=600_000, o=0)  # 6 EUR
    assert usage.limit_exceeded(session, NOW) is True


# --- llm_call --------------------------------------------------------------------------------

class FakeClient:
    def __init__(self, cfg, result=None, error=None):
        self.result, self.error = result, error

    def complete(self, system, messages, *, json_schema=None, max_tokens=4096):
        if self.error:
            raise self.error
        return self.result


@pytest.fixture
def fake(monkeypatch):
    class State:
        result = LLMResult("done", 12, 3, False)
        error = None
        made: list[ConfigData] = []
        seen: list = []

    def make(cfg, **_):
        State.made.append(cfg)
        return FakeClient(cfg, State.result, State.error)

    monkeypatch.setattr("app.llm.runner.make_client", make)
    return State


def build(cfg):
    return "sys", [Message("user", ["hello world"])]


def test_llm_call_success_records_usage(client, app, fake):
    with app.state.session_factory() as s:
        cfg = add_config(s)
    result, exceeded = llm_call(app.state.session_factory, "fit", build)
    assert result.text == "done" and exceeded is False
    assert fake.made[-1].id == cfg.id and fake.made[-1].api_key == "sk-test-1234"
    with app.state.session_factory() as s:
        row = s.query(LLMUsage).one()
        assert (row.config_id, row.purpose, row.input_tokens, row.output_tokens, row.ok) == (cfg.id, "fit", 12, 3, True)


def test_llm_call_failure_records_and_maps(client, app, fake):
    with app.state.session_factory() as s:
        add_config(s)
    fake.error = LLMError("llm_unavailable", "down")
    with pytest.raises(AppError) as exc:
        llm_call(app.state.session_factory, "extraction", build)
    assert exc.value.code == "llm_unavailable" and exc.value.status_code == 502
    assert exc.value.params == {"reason": "down"}
    with app.state.session_factory() as s:
        row = s.query(LLMUsage).one()
        assert (row.purpose, row.ok, row.estimated, row.input_tokens, row.output_tokens) == ("extraction", False, True, 4, 0)


@pytest.mark.parametrize("code,status", [
    ("llm_auth_failed", 502), ("llm_bad_request", 502), ("llm_rate_limited", 429), ("llm_timeout", 502)])
def test_llm_call_status_mapping(client, app, fake, code, status):
    with app.state.session_factory() as s:
        add_config(s)
    fake.error = LLMError(code, "r")
    with pytest.raises(AppError) as exc:
        llm_call(app.state.session_factory, "fit", build)
    assert (exc.value.code, exc.value.status_code) == (code, status)


def test_llm_call_not_configured_records_nothing(client, app, fake):
    with pytest.raises(ConflictError) as exc:
        llm_call(app.state.session_factory, "fit", build)
    assert exc.value.code == "llm_not_configured"
    with app.state.session_factory() as s:
        assert s.query(LLMUsage).count() == 0


def test_llm_call_make_client_error_mapped(client, app, monkeypatch):
    def boom(cfg, **_):
        raise LLMError("llm_auth_failed", "API key is missing")

    monkeypatch.setattr("app.llm.runner.make_client", boom)
    with app.state.session_factory() as s:
        add_config(s)
    with pytest.raises(AppError) as exc:
        llm_call(app.state.session_factory, "fit", build)
    assert exc.value.code == "llm_auth_failed"


def test_llm_call_build_error_propagates_without_request(client, app, fake):
    with app.state.session_factory() as s:
        add_config(s)

    def bad(cfg):
        raise AppError("llm_no_image_support", "no images")

    with pytest.raises(AppError):
        llm_call(app.state.session_factory, "fit", bad)
    assert fake.made == []


def test_llm_call_flags_limit_exceeded(client, app, fake):
    with app.state.session_factory() as s:
        add_config(s)
        set_limit(s, "tokens", 10)
    result, exceeded = llm_call(app.state.session_factory, "profile", build)
    assert result.text == "done" and exceeded is True  # 15 tokens recorded > 10, but the call still ran


def test_usage_endpoint(client, app):
    with app.state.session_factory() as s:
        add_usage(s, datetime.now(UTC), i=7, o=3)
    out = client.get("/api/llm/usage").json()
    assert out["today"] == {"input_tokens": 7, "output_tokens": 3, "eur": None}
    assert out["month"]["input_tokens"] == 7
    assert out["limit"] == {"kind": "none", "value": None} and out["limit_exceeded"] is False

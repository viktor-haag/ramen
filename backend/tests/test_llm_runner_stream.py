import pytest

from app.errors import AppError
from app.llm.base import LLMResult, Message
from app.llm.errors import LLMError
from app.llm.runner import llm_call
from app.models import LLMConfig, LLMProvider, LLMUsage


class StreamClient:
    calls: list = []
    error: Exception | None = None

    def __init__(self, cfg):
        pass

    def complete(self, system, messages, *, json_schema=None, max_tokens=4096):
        type(self).calls.append(("complete", max_tokens))
        return LLMResult("full", 5, 2, False)

    def stream(self, system, messages, *, max_tokens=4096, on_text):
        type(self).calls.append(("stream", max_tokens))
        on_text("par")
        on_text("tial")
        if type(self).error:
            raise type(self).error
        return LLMResult("partial", 12, 3, False)


@pytest.fixture
def fake(monkeypatch):
    StreamClient.calls, StreamClient.error = [], None
    monkeypatch.setattr("app.llm.runner.make_client", lambda cfg, **_: StreamClient(cfg))
    return StreamClient


@pytest.fixture
def cfg(client, app):
    with app.state.session_factory() as s:
        s.add(LLMConfig(name="c", provider=LLMProvider.anthropic, model="m", api_key="sk-test-1234", is_default=True))
        s.commit()


def build(cfg):
    return "sys", [Message("user", ["hello"])]


def rows(app):
    with app.state.session_factory() as s:
        return s.query(LLMUsage).all()


def test_on_text_streams_and_records_usage(app, fake, cfg):
    chunks = []
    result, _ = llm_call(app.state.session_factory, "cover_letter", build, max_tokens=999, on_text=chunks.append)
    assert result.text == "partial" and chunks == ["par", "tial"]
    assert fake.calls == [("stream", 999)]
    (row,) = rows(app)
    assert (row.purpose, row.input_tokens, row.output_tokens, row.ok) == ("cover_letter", 12, 3, True)


def test_without_on_text_uses_complete(app, fake, cfg):
    result, _ = llm_call(app.state.session_factory, "fit", build)
    assert result.text == "full" and fake.calls == [("complete", 4096)]


def test_stream_llm_error_maps_and_records_failure(app, fake, cfg):
    fake.error = LLMError("llm_rate_limited", "slow down")
    with pytest.raises(AppError) as exc:
        llm_call(app.state.session_factory, "fit", build, on_text=lambda t: None)
    assert exc.value.code == "llm_rate_limited" and exc.value.status_code == 429
    (row,) = rows(app)
    assert row.ok is False


def test_on_text_and_json_schema_is_a_programming_error(app, fake, cfg):
    with pytest.raises(ValueError):
        llm_call(app.state.session_factory, "fit", build, json_schema={"type": "object"}, on_text=lambda t: None)
    assert fake.calls == [] and rows(app) == []


def test_on_text_exception_is_unexpected_error(app, fake, cfg):
    def boom(_):
        raise RuntimeError("callback bug")

    with pytest.raises(AppError) as exc:
        llm_call(app.state.session_factory, "fit", build, on_text=boom)
    assert exc.value.code == "llm_unavailable"
    (row,) = rows(app)
    assert row.ok is False

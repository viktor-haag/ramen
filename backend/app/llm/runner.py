"""Run one LLM request for a purpose: resolve the config, call, record usage, map errors to AppError.

Thread-safe: every step uses its own short session from the factory, none is held during the request.
Errors: clients raise LLMError. Anything else is a bug in the client layer: it is logged with the API key
redacted (message only, no traceback that could echo it), recorded as a failed call and reported as
`llm_unavailable`.
"""
import logging
from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy.orm import Session, sessionmaker

from app.errors import AppError, TooManyRequestsError, UpstreamError
from app.llm.base import LLMClient, LLMResult, Message, input_chars
from app.llm.errors import REDACTED, LLMError
from app.llm.factory import ConfigData, make_client
from app.services import llm_configs, usage

log = logging.getLogger(__name__)

BuildMessages = Callable[[ConfigData], tuple[str, list[Message]]]

NO_REASON = "no details provided"


def _scrub(text: str, api_key: str | None) -> str:
    return text.replace(api_key, REDACTED) if api_key else text


def to_app_error(err: LLMError, api_key: str | None) -> AppError:
    reason = _scrub(err.reason, api_key).strip()
    cls = TooManyRequestsError if err.code == "llm_rate_limited" else UpstreamError
    # params.reason stays empty when there is none: the frontend supplies the localized fallback
    return cls(err.code, f"The LLM provider request failed: {reason or NO_REASON}", {"reason": reason})


def _unexpected(exc: Exception, cfg: ConfigData) -> LLMError:
    message = _scrub(str(exc), cfg.api_key)
    log.error("unexpected %s in LLM call (config %s): %s", type(exc).__name__, cfg.id, message)
    return LLMError("llm_unavailable", f"unexpected {type(exc).__name__}")


def _client(cfg: ConfigData) -> LLMClient:
    try:
        return make_client(cfg)
    except LLMError as exc:
        err = exc
    raise to_app_error(err, cfg.api_key) from None


def list_models_for(cfg: ConfigData) -> list[str]:
    client = _client(cfg)
    try:
        return client.list_models()
    except LLMError as exc:
        err = exc
    except Exception as exc:  # noqa: BLE001
        err = _unexpected(exc, cfg)
    raise to_app_error(err, cfg.api_key) from None


def run_call(
    session_factory: sessionmaker[Session],
    cfg: ConfigData,
    purpose: str,
    build_messages: BuildMessages,
    *,
    json_schema: dict | None = None,
    max_tokens: int = 4096,
    on_text: Callable[[str], None] | None = None,
) -> tuple[LLMResult, bool]:
    """Call with an already resolved config. Returns (result, limit_exceeded after recording this call).

    With `on_text` the call is streamed (no json_schema: ValueError). An exception raised by `on_text` is a bug
    in the caller: it aborts the call and is handled like any unexpected error (failed usage, `llm_unavailable`).
    """
    if on_text is not None and json_schema is not None:
        raise ValueError("on_text (streaming) cannot be combined with json_schema")
    system, messages = build_messages(cfg)  # may raise AppError (e.g. no image support): nothing is sent
    client = _client(cfg)
    result, err = None, None
    try:
        if on_text is not None:
            result = client.stream(system, messages, max_tokens=max_tokens, on_text=on_text)
        else:
            result = client.complete(system, messages, json_schema=json_schema, max_tokens=max_tokens)
    except LLMError as exc:
        err = exc
    except Exception as exc:  # noqa: BLE001
        err = _unexpected(exc, cfg)
    with session_factory() as session:
        usage.record(
            session, config_id=cfg.id, purpose=purpose, result=result, ok=err is None,
            chars_in=input_chars(system, messages),
        )
        session.commit()
        exceeded = usage.limit_exceeded(session, datetime.now(UTC), cfg.id)  # global or this config
    if err is not None:
        raise to_app_error(err, cfg.api_key) from None
    return result, exceeded


def llm_call(
    session_factory: sessionmaker[Session],
    purpose: str,
    build_messages: BuildMessages,
    *,
    json_schema: dict | None = None,
    max_tokens: int = 4096,
    on_text: Callable[[str], None] | None = None,
) -> tuple[LLMResult, bool]:
    """Resolve the config of `purpose` (ConflictError llm_not_configured), call, record, map errors."""
    with session_factory() as session:
        cfg = llm_configs.resolve(session, purpose)
    return run_call(
        session_factory, cfg, purpose, build_messages, json_schema=json_schema, max_tokens=max_tokens, on_text=on_text,
    )

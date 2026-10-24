import time
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from app.db import get_session
from app.llm.base import Message
from app.llm.factory import ConfigData
from app.llm.runner import list_models_for, run_call
from app.schemas.llm import (
    ConnectionTestOut,
    LLMConfigCreate,
    LLMConfigIn,
    LLMConfigOut,
    ModelsIn,
    PurposesIn,
    PurposesOut,
    UsageOut,
)
from app.services import llm_configs, usage
from app.services.usage import USAGE_PURPOSE_TEST

router = APIRouter()


@router.get("/llm/configs", response_model=list[LLMConfigOut])
def list_all(session: Session = Depends(get_session)) -> list[LLMConfigOut]:
    return [llm_configs.to_out(c) for c in llm_configs.list_configs(session)]


@router.post("/llm/configs", response_model=LLMConfigOut)
def create(data: LLMConfigCreate, session: Session = Depends(get_session)) -> LLMConfigOut:
    cfg = llm_configs.create_config(session, data)
    session.commit()
    return llm_configs.to_out(cfg)


@router.get("/llm/configs/{config_id}", response_model=LLMConfigOut)
def read(config_id: int, session: Session = Depends(get_session)) -> LLMConfigOut:
    return llm_configs.to_out(llm_configs.get_config(session, config_id))


@router.put("/llm/configs/{config_id}", response_model=LLMConfigOut)
def update(config_id: int, data: LLMConfigIn, session: Session = Depends(get_session)) -> LLMConfigOut:
    cfg = llm_configs.update_config(session, config_id, data)
    session.commit()
    return llm_configs.to_out(cfg)


@router.delete("/llm/configs/{config_id}", status_code=204)
def delete(config_id: int, session: Session = Depends(get_session)) -> Response:
    llm_configs.delete_config(session, config_id)
    session.commit()
    return Response(status_code=204)


@router.post("/llm/configs/{config_id}/default", response_model=LLMConfigOut)
def make_default(config_id: int, session: Session = Depends(get_session)) -> LLMConfigOut:
    cfg = llm_configs.set_default(session, config_id)
    session.commit()
    return llm_configs.to_out(cfg)


@router.post("/llm/configs/{config_id}/test", response_model=ConnectionTestOut)
def test_connection(
    config_id: int, request: Request, session: Session = Depends(get_session)
) -> ConnectionTestOut:
    cfg = llm_configs.to_data(llm_configs.get_config(session, config_id))
    session.close()  # do not hold a connection during the network call
    started = time.monotonic()
    run_call(
        request.app.state.session_factory, cfg, USAGE_PURPOSE_TEST,
        lambda _cfg: ("", [Message("user", ["Reply with the single word OK."])]), max_tokens=16,
    )
    return ConnectionTestOut(ok=True, model=cfg.model, latency_ms=round((time.monotonic() - started) * 1000))


@router.post("/llm/models", response_model=list[str])
def models(data: ModelsIn, session: Session = Depends(get_session)) -> list[str]:
    if data.config_id is not None:
        stored = llm_configs.get_config(session, data.config_id)
        cfg = llm_configs.to_data(stored)
        provider = data.provider.value if data.provider is not None else cfg.provider
        base_url = data.base_url if data.base_url is not None else cfg.base_url
        if provider != cfg.provider or base_url != cfg.base_url:
            # a different endpoint must not receive the stored credentials
            cfg.api_key, cfg.extra_headers, cfg.extra_body = None, {}, {}
        cfg.provider, cfg.base_url = provider, base_url
    else:
        cfg = ConfigData(provider=data.provider.value, model="", supports_images=False)
    session.close()  # do not hold a connection during the network call
    for field in ("base_url", "api_key", "model", "extra_body", "extra_headers"):
        value = getattr(data, field)
        if value is not None:
            setattr(cfg, field, value)
    if cfg.provider != "openai_compatible":
        cfg.base_url = None  # only generic endpoints have a custom URL; never send a key to a leftover one
    return list_models_for(cfg)


@router.get("/llm/purposes", response_model=PurposesOut)
def read_purposes(session: Session = Depends(get_session)) -> PurposesOut:
    return llm_configs.get_purposes(session)


@router.put("/llm/purposes", response_model=PurposesOut)
def update_purposes(data: PurposesIn, session: Session = Depends(get_session)) -> PurposesOut:
    out = llm_configs.set_purposes(session, data)
    session.commit()
    return out


@router.get("/llm/usage", response_model=UsageOut)
def read_usage(session: Session = Depends(get_session)) -> UsageOut:
    return usage.summary(session, datetime.now(UTC))

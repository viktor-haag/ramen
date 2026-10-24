from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationInfo, field_validator

from app.models import LLMProvider, ThinkingLevel


class LLMConfigIn(BaseModel):
    name: str = Field(min_length=1)
    provider: LLMProvider
    base_url: str | None = Field(default=None, validate_default=True)
    api_key: str | None = None  # PUT: omitted keeps the stored key, "" clears it
    model: str = Field(min_length=1)
    thinking: ThinkingLevel = ThinkingLevel.off
    supports_images: bool | None = None  # None = provider default (create) / keep (update)
    extra_body: dict[str, Any] = Field(default_factory=dict)
    extra_headers: dict[str, str] = Field(default_factory=dict)
    price_in: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    price_out: float | None = Field(default=None, ge=0, allow_inf_nan=False)

    @field_validator("name", "model")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value

    # Cross-field rules are field validators (not model validators) so the 422 names the failing field.
    @field_validator("base_url", mode="after")
    @classmethod
    def _check_base_url(cls, value: str | None, info: ValidationInfo) -> str | None:
        value = (value or "").strip() or None
        provider = info.data.get("provider")
        if provider == LLMProvider.openai_compatible and value is None:
            raise ValueError("base_url is required for openai_compatible")
        if provider is not None and provider != LLMProvider.openai_compatible and value is not None:
            raise ValueError("base_url is only allowed for openai_compatible")
        return value

    @field_validator("thinking", mode="after")
    @classmethod
    def _check_thinking(cls, value: ThinkingLevel, info: ValidationInfo) -> ThinkingLevel:
        if info.data.get("provider") == LLMProvider.openai_compatible and value != ThinkingLevel.off:
            raise ValueError("thinking is only available for anthropic and openai")
        return value


class LLMConfigCreate(LLMConfigIn):
    api_key: str | None = Field(default=None, validate_default=True)

    @field_validator("api_key", mode="after")
    @classmethod
    def _key_required(cls, value: str | None, info: ValidationInfo) -> str | None:
        provider = info.data.get("provider")
        if provider is not None and provider != LLMProvider.openai_compatible and not (value or "").strip():
            raise ValueError("api_key is required")
        return value


class LLMConfigOut(BaseModel):
    id: int
    name: str
    provider: LLMProvider
    base_url: str | None
    api_key: str | None  # masked, never the clear text
    has_api_key: bool
    model: str
    thinking: ThinkingLevel
    supports_images: bool
    extra_body: dict[str, Any]
    extra_headers: dict[str, str]
    price_in: float | None
    price_out: float | None
    is_default: bool


class PurposesIn(BaseModel):
    profile: int | None
    fit: int | None
    extraction: int | None


class PurposesOut(PurposesIn):
    pass


class ModelsIn(BaseModel):
    """Either a stored config (`config_id`) or the config fields typed into the form; fields override."""

    config_id: int | None = None
    provider: LLMProvider | None = Field(default=None, validate_default=True)
    base_url: str | None = None
    api_key: str | None = None
    model: str | None = None
    extra_body: dict[str, Any] | None = None
    extra_headers: dict[str, str] | None = None

    @field_validator("provider", mode="after")
    @classmethod
    def _need_source(cls, value: LLMProvider | None, info: ValidationInfo) -> LLMProvider | None:
        if value is None and info.data.get("config_id") is None:
            raise ValueError("config_id or provider is required")
        return value


class ConnectionTestOut(BaseModel):
    ok: bool
    model: str
    latency_ms: int


class UsageTotals(BaseModel):
    input_tokens: int
    output_tokens: int
    eur: float | None  # only usage of configs with prices; None when there is none


class LimitOut(BaseModel):
    kind: Literal["none", "tokens", "eur"]
    value: float | None


class UsageOut(BaseModel):
    today: UsageTotals
    month: UsageTotals
    limit: LimitOut
    limit_exceeded: bool

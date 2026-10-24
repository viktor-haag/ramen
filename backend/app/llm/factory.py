"""Client factory.

make_client() can raise LLMError (missing API key, missing base URL), so callers must wrap it as well
as complete(). The SDKs still merge ANTHROPIC_CUSTOM_HEADERS / OPENAI_CUSTOM_HEADERS from the
environment (operator-controlled, accepted).
"""
from dataclasses import dataclass, field

import httpx2  # the SDKs reject legacy httpx clients; they depend on httpx2

from app.llm.anthropic_client import AnthropicClient
from app.llm.base import LLMClient
from app.llm.openai_client import OpenAIClient


@dataclass
class ConfigData:
    """Plain mirror of the LLMConfig row (incl. the clear-text api_key) for the client layer."""

    provider: str
    model: str
    supports_images: bool  # no default: the right value depends on the provider, the caller decides
    id: int | None = None
    name: str = ""
    base_url: str | None = None
    api_key: str | None = field(default=None, repr=False)
    thinking: str = "off"
    extra_body: dict = field(default_factory=dict, repr=False)
    extra_headers: dict = field(default_factory=dict, repr=False)  # may carry credentials
    price_in: float | None = None
    price_out: float | None = None


def make_client(cfg: ConfigData, *, http_client: httpx2.Client | None = None) -> LLMClient:
    provider = getattr(cfg.provider, "value", cfg.provider)
    if provider == "anthropic":
        return AnthropicClient(cfg, http_client=http_client)
    if provider in ("openai", "openai_compatible"):
        return OpenAIClient(cfg, http_client=http_client)
    raise ValueError(f"Unknown LLM provider: {provider}")

import base64
import json

import anthropic
import httpx2  # the SDKs reject legacy httpx clients; they depend on httpx2

from app.llm.base import (
    SCHEMA_INSTRUCTION,
    THINKING_MIN_MAX_TOKENS,
    ImagePart,
    LLMResult,
    Message,
    resolve_usage,
)
from app.llm.errors import LLMError, map_sdk_error

DEFAULT_BASE_URL = "https://api.anthropic.com"  # explicit, so ANTHROPIC_BASE_URL is never picked up


def _part(p: str | ImagePart) -> dict:
    if isinstance(p, str):
        return {"type": "text", "text": p}
    return {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": p.mime,
            "data": base64.b64encode(p.data).decode("ascii"),
        },
    }


def _extract_text(resp) -> str | None:
    """Concatenated text blocks, or None for any unexpected response shape."""
    try:
        blocks = resp.content
        if not isinstance(blocks, list):
            return None
        texts = []
        for b in blocks:
            if getattr(b, "type", None) == "text":
                if not isinstance(b.text, str):
                    return None
                texts.append(b.text)
        return "".join(texts).strip() or None
    except (AttributeError, TypeError):
        return None


class AnthropicClient:
    def __init__(self, cfg, *, http_client: httpx2.Client | None = None):
        if not (cfg.api_key or "").strip():
            raise LLMError("llm_auth_failed", "No API key configured.")
        self._cfg = cfg
        self._client = anthropic.Anthropic(
            api_key=cfg.api_key,
            base_url=cfg.base_url or DEFAULT_BASE_URL,
            timeout=120.0,
            max_retries=2,
            http_client=http_client,
        )

    def complete(self, system, messages: list[Message], *, json_schema=None, max_tokens=4096) -> LLMResult:
        """json_schema is only a prompt instruction here; callers validate the output locally."""
        cfg = self._cfg
        if json_schema is not None:
            system = f"{system}\n\n{SCHEMA_INSTRUCTION}{json.dumps(json_schema)}".strip()
        kwargs: dict = {}
        thinking = getattr(cfg.thinking, "value", cfg.thinking)
        if thinking and thinking != "off":
            kwargs["thinking"] = {"type": "adaptive"}
            kwargs["output_config"] = {"effort": thinking}
            max_tokens = max(max_tokens, THINKING_MIN_MAX_TOKENS)
        if system:
            kwargs["system"] = system
        err: LLMError | None = None
        try:
            resp = self._client.messages.create(
                model=cfg.model,
                max_tokens=max_tokens,
                messages=[{"role": m.role, "content": [_part(p) for p in m.parts]} for m in messages],
                extra_headers=cfg.extra_headers or None,
                extra_body=cfg.extra_body or None,
                **kwargs,
            )
        except (anthropic.AnthropicError, ValueError) as exc:  # anything else is a bug and propagates
            err = map_sdk_error(exc, cfg.api_key)
        if err is not None:
            raise err
        text = _extract_text(resp)
        if text is None:
            raise LLMError("llm_invalid_output", "The model returned no usable text content.")
        usage = getattr(resp, "usage", None)
        return resolve_usage(
            getattr(usage, "input_tokens", None), getattr(usage, "output_tokens", None), system, messages, text
        )

    def list_models(self) -> list[str]:
        err: LLMError | None = None
        try:
            return [m.id for m in self._client.models.list()]
        except (anthropic.AnthropicError, ValueError) as exc:
            err = map_sdk_error(exc, self._cfg.api_key)
        raise err

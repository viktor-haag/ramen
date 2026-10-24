import base64
import json

import httpx2  # the SDKs reject legacy httpx clients; they depend on httpx2
import openai

from app.llm.base import (
    SCHEMA_INSTRUCTION,
    THINKING_MIN_MAX_TOKENS,
    ImagePart,
    LLMResult,
    Message,
    resolve_usage,
)
from app.llm.errors import LLMError, map_sdk_error

DEFAULT_BASE_URL = "https://api.openai.com/v1"  # explicit, so OPENAI_BASE_URL is never picked up


def _content(parts: list[str | ImagePart]):
    if all(isinstance(p, str) for p in parts):
        return "\n\n".join(parts)  # plain string: widest compatibility with OpenAI-like servers
    out: list[dict] = []
    for p in parts:
        if isinstance(p, str):
            out.append({"type": "text", "text": p})
        else:
            b64 = base64.b64encode(p.data).decode("ascii")
            out.append({"type": "image_url", "image_url": {"url": f"data:{p.mime};base64,{b64}"}})
    return out


def _extract_text(resp) -> str | None:
    """Message text (string or list of text parts), or None for any unexpected response shape."""
    try:
        content = resp.choices[0].message.content
        if isinstance(content, list):  # some compatible servers return content parts
            texts = []
            for part in content:
                kind = part.get("type") if isinstance(part, dict) else getattr(part, "type", None)
                text = part.get("text") if isinstance(part, dict) else getattr(part, "text", None)
                if kind == "text" and isinstance(text, str):
                    texts.append(text)
            content = "".join(texts)
        return content.strip() or None if isinstance(content, str) else None
    except (AttributeError, TypeError, IndexError, KeyError):
        return None


class OpenAIClient:
    def __init__(self, cfg, *, http_client: httpx2.Client | None = None):
        provider = getattr(cfg.provider, "value", cfg.provider)
        self._official = provider == "openai"
        if self._official and not (cfg.api_key or "").strip():
            raise LLMError("llm_auth_failed", "No API key configured.")
        if not self._official and not (cfg.base_url or "").strip():
            raise LLMError("llm_bad_request", "A base URL is required for OpenAI-compatible endpoints.")
        self._cfg = cfg
        # Local OpenAI-compatible servers often need no key; the SDK insists on a non-empty one.
        # Everything is passed explicitly so the SDK never falls back to OPENAI_* environment variables.
        self._client = openai.OpenAI(
            api_key=cfg.api_key or "not-needed",
            base_url=cfg.base_url.strip() if cfg.base_url else DEFAULT_BASE_URL,
            timeout=120.0,
            max_retries=2,
            http_client=http_client,
        )
        # The constructor falls back to OPENAI_ORG_ID / OPENAI_PROJECT_ID; drop whatever it picked up.
        self._client.organization = None
        self._client.project = None

    def complete(self, system, messages: list[Message], *, json_schema=None, max_tokens=4096) -> LLMResult:
        """For provider `openai` json_schema is sent with strict=True: callers must pass a
        strict-compatible schema (additionalProperties false, all properties required)."""
        cfg = self._cfg
        kwargs: dict = {}
        if json_schema is not None:
            if self._official:
                kwargs["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {"name": "result", "schema": json_schema, "strict": True},
                }
            else:
                system = f"{system}\n\n{SCHEMA_INSTRUCTION}{json.dumps(json_schema)}".strip()
        thinking = getattr(cfg.thinking, "value", cfg.thinking)
        if self._official:
            if thinking and thinking != "off":
                kwargs["reasoning_effort"] = thinking
                max_tokens = max(max_tokens, THINKING_MIN_MAX_TOKENS)
            kwargs["max_completion_tokens"] = max_tokens
        else:
            kwargs["max_tokens"] = max_tokens
        msgs: list[dict] = []
        if system:
            msgs.append({"role": "system", "content": system})
        msgs += [{"role": m.role, "content": _content(m.parts)} for m in messages]
        err: LLMError | None = None
        try:
            resp = self._client.chat.completions.create(
                model=cfg.model,
                messages=msgs,
                extra_headers=cfg.extra_headers or None,
                extra_body=cfg.extra_body or None,
                **kwargs,
            )
        except (openai.OpenAIError, ValueError) as exc:  # anything else is a bug and propagates
            err = map_sdk_error(exc, cfg.api_key)
        if err is not None:
            raise err
        text = _extract_text(resp)
        if text is None:
            raise LLMError("llm_invalid_output", "The model returned no usable text content.")
        usage = getattr(resp, "usage", None)
        return resolve_usage(
            getattr(usage, "prompt_tokens", None), getattr(usage, "completion_tokens", None), system, messages, text
        )

    def list_models(self) -> list[str]:
        err: LLMError | None = None
        try:
            return [m.id for m in self._client.models.list()]
        except (openai.OpenAIError, ValueError) as exc:
            err = map_sdk_error(exc, self._cfg.api_key)
        raise err

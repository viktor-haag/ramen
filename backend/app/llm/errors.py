import anthropic
import httpx2
import openai

REDACTED = "***"

# Error events inside an already started (HTTP 200) stream carry the error type in the body only.
_STREAM_ERROR_TYPES = {
    "authentication_error": "llm_auth_failed",
    "permission_error": "llm_auth_failed",
    "rate_limit_error": "llm_rate_limited",
    "invalid_request_error": "llm_bad_request",
    "not_found_error": "llm_bad_request",
    "request_too_large": "llm_bad_request",
}


class LLMError(Exception):
    def __init__(self, code: str, reason: str = ""):
        super().__init__(f"{code}: {reason}" if reason else code)
        self.code = code
        self.reason = reason


def _scrub(text: str, api_key: str | None) -> str:
    if api_key:
        text = text.replace(api_key, REDACTED)
    return text


def map_sdk_error(exc: Exception, api_key: str | None = None) -> LLMError:
    """Translate an anthropic/openai SDK exception into an LLMError (spec 2.4).

    Callers must raise the result outside their `except` block so that no chained SDK exception
    (which may echo the API key) stays reachable through __cause__/__context__.
    """
    if isinstance(exc, LLMError):
        return exc
    message = _scrub(str(getattr(exc, "message", None) or exc), api_key)
    if isinstance(exc, (anthropic.APITimeoutError, openai.APITimeoutError, httpx2.TimeoutException)):
        return LLMError("llm_timeout", message)
    # Raw transport errors surface from the Anthropic SDK when a stream body breaks off midway.
    if isinstance(exc, (anthropic.APIConnectionError, openai.APIConnectionError, httpx2.TransportError)):
        return LLMError("llm_unavailable", message)
    if isinstance(exc, (anthropic.APIResponseValidationError, openai.APIResponseValidationError)):
        return LLMError("llm_invalid_output", message)  # carries status 200; not a request problem
    if isinstance(exc, ValueError):  # e.g. json.JSONDecodeError from a malformed 200 body
        return LLMError("llm_invalid_output", message)
    status = getattr(exc, "status_code", None)
    if isinstance(status, int):
        if status < 400:  # error event mid-stream, e.g. Anthropic `overloaded_error`
            code = _STREAM_ERROR_TYPES.get(_error_type(getattr(exc, "body", None)), "llm_unavailable")
            return LLMError(code, message)
        if status in (401, 403):
            return LLMError("llm_auth_failed", message)
        if status == 429:
            return LLMError("llm_rate_limited", message)
        if status >= 500:
            return LLMError("llm_unavailable", message)
        return LLMError("llm_bad_request", message)  # 400/404/422 and other 4xx
    return LLMError("llm_unavailable", message)


def _error_type(body: object) -> object:
    if isinstance(body, dict):
        inner = body.get("error")
        return inner.get("type") if isinstance(inner, dict) else body.get("type")
    return None

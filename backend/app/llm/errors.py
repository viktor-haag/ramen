import anthropic
import openai

REDACTED = "***"


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
    if isinstance(exc, (anthropic.APITimeoutError, openai.APITimeoutError)):
        return LLMError("llm_timeout", message)
    if isinstance(exc, (anthropic.APIConnectionError, openai.APIConnectionError)):
        return LLMError("llm_unavailable", message)
    if isinstance(exc, (anthropic.APIResponseValidationError, openai.APIResponseValidationError)):
        return LLMError("llm_invalid_output", message)  # carries status 200; not a request problem
    if isinstance(exc, ValueError):  # e.g. json.JSONDecodeError from a malformed 200 body
        return LLMError("llm_invalid_output", message)
    status = getattr(exc, "status_code", None)
    if isinstance(status, int):
        if status in (401, 403):
            return LLMError("llm_auth_failed", message)
        if status == 429:
            return LLMError("llm_rate_limited", message)
        if status >= 500:
            return LLMError("llm_unavailable", message)
        return LLMError("llm_bad_request", message)  # 400/404/422 and other 4xx
    return LLMError("llm_unavailable", message)

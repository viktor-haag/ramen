import traceback
from concurrent.futures import CancelledError, TimeoutError

import httpx
from pebble import ProcessExpired

from app.plugins.loader import PluginInfo


def describe(exc: BaseException) -> str:
    text = str(exc)
    return f"{type(exc).__name__}: {text}" if text else type(exc).__name__


class PluginFailure(Exception):
    """Picklable stand-in for any exception raised by a plugin inside a pool worker.

    Plugin exceptions can be unpicklable (httpx.HTTPStatusError needs keyword-only arguments),
    which pebble reports only as "Unpicklable object from worker" and loses the real reason.
    """

    def __init__(self, summary: str, traceback_text: str = ""):
        super().__init__(summary, traceback_text)
        self.summary = summary
        self.traceback_text = traceback_text

    def __str__(self) -> str:
        return self.summary


def _host(exc: httpx.RequestError) -> str | None:
    try:
        return exc.request.url.host or None
    except RuntimeError:  # no request attached
        return None


def summarize(exc: BaseException) -> str:
    """Short English reason: HTTP status and host for HTTP errors, else type and message."""
    if isinstance(exc, httpx.HTTPStatusError):
        response = exc.response
        status = f"HTTP {response.status_code} {response.reason_phrase}".rstrip()
        return f"{status} ({exc.request.url.host})"
    text = describe(exc)
    if isinstance(exc, httpx.RequestError) and (host := _host(exc)):
        return f"{text} ({host})"
    return text


def to_failure(exc: BaseException) -> PluginFailure:
    return PluginFailure(summarize(exc), "".join(traceback.format_exception(exc)))


def failure_text(exc: BaseException, timeout: int) -> str:
    """English, user-facing reason why a pool job failed (shared by search runs and URL fetches)."""
    if isinstance(exc, PluginFailure):
        return exc.summary
    if isinstance(exc, TimeoutError):
        return f"Timed out after {timeout} s"
    if isinstance(exc, ProcessExpired):
        return f"Plugin process crashed (exit code {exc.exitcode})"
    if isinstance(exc, CancelledError):
        return "Run cancelled"
    return describe(exc)


def split_timeout(info: PluginInfo, settings: dict | None) -> tuple[int, dict]:
    """Effective timeout (setting `timeout_seconds`, else the plugin default) and the settings
    without that key, ready to hand to the plugin. Missing, invalid or < 1 values fall back."""
    rest = dict(settings or {})
    raw = rest.pop("timeout_seconds", None)
    try:
        timeout = int(raw)
    except (TypeError, ValueError):
        timeout = 0
    return (timeout if timeout >= 1 else info.timeout_seconds), rest

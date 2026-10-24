from concurrent.futures import CancelledError, TimeoutError

from pebble import ProcessExpired

from app.plugins.loader import PluginInfo


def describe(exc: BaseException) -> str:
    text = str(exc)
    return f"{type(exc).__name__}: {text}" if text else type(exc).__name__


def failure_text(exc: BaseException, timeout: int) -> str:
    """English, user-facing reason why a pool job failed (shared by search runs and URL fetches)."""
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

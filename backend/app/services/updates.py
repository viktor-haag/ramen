"""Check GitHub for a newer RAMEN release (in-memory state, never raises)."""

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime

import httpx
from packaging.version import InvalidVersion, Version

from app.models.posting import utcnow
from app.plugins.http import make_client

logger = logging.getLogger(__name__)

GITHUB_API = "https://api.github.com"
TIMEOUT_SECONDS = 10.0


@dataclass(frozen=True)
class UpdateStatus:
    current: str
    latest: str | None = None
    release_url: str | None = None
    published_at: datetime | None = None
    checked_at: datetime | None = None
    error: str | None = None

    @property
    def update_available(self) -> bool:
        if self.latest is None:
            return False
        try:
            return Version(self.latest) > Version(self.current)
        except InvalidVersion:
            return False


def parse_version(tag: str) -> Version | None:
    """Parse a release tag like ``v1.2.3``; None for invalid tags and pre-releases."""
    text = tag.strip()
    if text[:1] in ("v", "V"):
        text = text[1:]
    try:
        version = Version(text)
    except InvalidVersion:
        return None
    if version.is_prerelease:
        return None
    return version


def _parse_published_at(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


class _CheckError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class UpdateChecker:
    def __init__(
        self,
        repo: str,
        current: str,
        *,
        client_factory: Callable[[], httpx.Client] | None = None,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._repo = repo
        self._current = current
        self._headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": f"RAMEN/{current}",
        }
        self._client_factory = client_factory or self._default_client
        self._clock = clock
        self._state = UpdateStatus(current=current)
        self._state_lock = threading.Lock()  # guards _state; never held during I/O
        self._check_lock = threading.Lock()  # serializes concurrent checks

    def _default_client(self) -> httpx.Client:
        return make_client(retries=0, timeout=TIMEOUT_SECONDS, headers=self._headers)

    def status(self) -> UpdateStatus:
        with self._state_lock:
            return self._state

    def check(self) -> UpdateStatus:
        """Query GitHub once and store the outcome. Errors never raise and keep the last good result."""
        with self._check_lock:
            try:
                latest, url, published = self._fetch()
                error = None
            except _CheckError as exc:
                latest = url = published = None
                error = exc.code
            except httpx.HTTPError as exc:
                logger.info("update check failed: %s", exc)
                latest = url = published = None
                error = "network"
            except Exception:
                logger.exception("update check failed unexpectedly")
                latest = url = published = None
                error = "network"
            checked_at = self._clock()
            with self._state_lock:
                if error is None:
                    self._state = UpdateStatus(
                        current=self._current,
                        latest=latest,
                        release_url=url,
                        published_at=published,
                        checked_at=checked_at,
                    )
                else:
                    self._state = replace(self._state, checked_at=checked_at, error=error)
                return self._state

    def _fetch(self) -> tuple[str, str | None, datetime | None]:
        url = f"{GITHUB_API}/repos/{self._repo}/releases/latest"
        client = self._client_factory()
        try:
            response = client.get(url, headers=self._headers)
        finally:
            client.close()
        code = response.status_code
        if code == 429 or (code == 403 and response.headers.get("x-ratelimit-remaining") == "0"):
            raise _CheckError("rate_limited")
        if code != 200:
            raise _CheckError(f"http_{code}")
        try:
            body = response.json()
        except ValueError:
            raise _CheckError("invalid_response") from None
        tag = body.get("tag_name") if isinstance(body, dict) else None
        version = parse_version(tag) if isinstance(tag, str) else None
        if version is None:
            raise _CheckError("invalid_response")
        html_url = body.get("html_url")
        return (
            str(version),
            html_url if isinstance(html_url, str) else None,
            _parse_published_at(body.get("published_at")),
        )

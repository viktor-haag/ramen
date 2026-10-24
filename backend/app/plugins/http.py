"""HTTP helper for extractor plugins: httpx client with retries, backoff and rate limit."""

import math
import time
import urllib.request

import httpx

DEFAULT_USER_AGENT = "jobtracker/0.1 (+personal use)"
MAX_RETRY_AFTER = 60.0
RETRY_STATUS_CODES = frozenset({429, 500, 502, 503, 504})


def _sleep(seconds: float) -> None:
    """Module-wide sleep so tests can patch it."""
    time.sleep(seconds)


def _retry_after_seconds(response: httpx.Response) -> float | None:
    value = response.headers.get("Retry-After")
    if value is None:
        return None
    try:
        seconds = float(value.strip())
    except ValueError:
        return None
    if not math.isfinite(seconds) or seconds < 0:
        return None
    return min(seconds, MAX_RETRY_AFTER)


class RetryTransport(httpx.BaseTransport):
    def __init__(
        self,
        wrapped: httpx.BaseTransport,
        retries: int = 3,
        backoff: float = 0.5,
        min_interval: float = 0.0,
    ) -> None:
        self._wrapped = wrapped
        self._retries = retries
        self._backoff = backoff
        self._min_interval = min_interval
        self._last_request: float | None = None

    def _respect_min_interval(self) -> None:
        if self._min_interval > 0 and self._last_request is not None:
            wait = self._last_request + self._min_interval - time.monotonic()
            if wait > 0:
                _sleep(wait)
        self._last_request = time.monotonic()

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        attempt = 0
        while True:
            self._respect_min_interval()
            try:
                response = self._wrapped.handle_request(request)
            except httpx.TransportError:
                if attempt >= self._retries:
                    raise
                wait = self._backoff * 2**attempt
            else:
                if response.status_code not in RETRY_STATUS_CODES or attempt >= self._retries:
                    return response
                retry_after = _retry_after_seconds(response)
                wait = retry_after if retry_after is not None else self._backoff * 2**attempt
                response.close()
            _sleep(wait)
            attempt += 1

    def close(self) -> None:
        self._wrapped.close()


class EnvProxyTransport(httpx.BaseTransport):
    """Routes each request to a direct or proxied transport per the standard proxy env vars.

    Honours HTTP(S)_PROXY / ALL_PROXY / NO_PROXY (via urllib) like httpx's own default
    transport does when no custom transport is given. It sits *inside* one RetryTransport,
    so retry and rate-limit state is shared by the direct and the proxied path.
    """

    def __init__(self) -> None:
        self._proxies = {k: v for k, v in urllib.request.getproxies().items() if k != "no"}
        self._no_proxy = {"no": urllib.request.getproxies().get("no", "")}
        self._direct = httpx.HTTPTransport()
        self._proxied = {
            scheme: httpx.HTTPTransport(proxy=url)
            for scheme, url in self._proxies.items()
            if scheme in ("http", "https", "all")
        }

    def select(self, url: httpx.URL) -> httpx.BaseTransport:
        proxy_transport = self._proxied.get(url.scheme) or self._proxied.get("all")
        if proxy_transport is None:
            return self._direct
        if urllib.request.proxy_bypass_environment(url.host, {**self._no_proxy, **self._proxies}):
            return self._direct
        return proxy_transport

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        return self.select(request.url).handle_request(request)

    def close(self) -> None:
        self._direct.close()
        for transport in self._proxied.values():
            transport.close()


def make_client(
    *,
    retries: int = 3,
    backoff: float = 0.5,
    min_interval: float = 0.0,
    timeout: float = 30.0,
    headers: dict | None = None,
    transport: httpx.BaseTransport | None = None,
) -> httpx.Client:
    wrapped = transport if transport is not None else EnvProxyTransport()
    merged = httpx.Headers({"User-Agent": DEFAULT_USER_AGENT})
    merged.update(headers or {})
    return httpx.Client(
        transport=RetryTransport(wrapped, retries, backoff, min_interval),
        timeout=timeout,
        headers=merged,
    )

import httpx
import pytest

from app.plugins import http as plugin_http


@pytest.fixture
def sleeps(monkeypatch):
    recorded: list[float] = []
    monkeypatch.setattr(plugin_http, "_sleep", recorded.append)
    return recorded


def _client(handler, **kwargs):
    return plugin_http.make_client(transport=httpx.MockTransport(handler), **kwargs)


def test_retries_on_503_then_succeeds(sleeps):
    statuses = iter([503, 503, 200])
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(next(statuses))

    with _client(handler) as client:
        response = client.get("https://example.test/")

    assert response.status_code == 200
    assert len(calls) == 3
    assert sleeps == [0.5, 1.0]


def test_gives_up_after_retries(sleeps):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(500)

    with _client(handler) as client:
        response = client.get("https://example.test/")

    assert response.status_code == 500
    assert len(calls) == 4
    assert sleeps == [0.5, 1.0, 2.0]


def test_retry_after_header(sleeps):
    statuses = iter([429, 200])

    def handler(request):
        status = next(statuses)
        headers = {"Retry-After": "3"} if status == 429 else {}
        return httpx.Response(status, headers=headers)

    with _client(handler) as client:
        response = client.get("https://example.test/")

    assert response.status_code == 200
    assert sleeps == [3]


def test_invalid_retry_after_falls_back_to_backoff(sleeps):
    statuses = iter([429, 200])

    def handler(request):
        status = next(statuses)
        headers = {"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"} if status == 429 else {}
        return httpx.Response(status, headers=headers)

    with _client(handler) as client:
        client.get("https://example.test/")

    assert sleeps == [0.5]


def test_no_retry_on_404(sleeps):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(404)

    with _client(handler) as client:
        response = client.get("https://example.test/")

    assert response.status_code == 404
    assert len(calls) == 1
    assert sleeps == []


def test_retries_on_transport_error_then_succeeds(sleeps):
    calls = []

    def handler(request):
        calls.append(request)
        if len(calls) < 3:
            raise httpx.ConnectError("boom")
        return httpx.Response(200)

    with _client(handler) as client:
        response = client.get("https://example.test/")

    assert response.status_code == 200
    assert sleeps == [0.5, 1.0]


def test_transport_error_reraised_after_retries(sleeps):
    calls = []

    def handler(request):
        calls.append(request)
        raise httpx.ConnectError("boom")

    with _client(handler, retries=2) as client:
        with pytest.raises(httpx.ConnectError):
            client.get("https://example.test/")

    assert len(calls) == 3
    assert sleeps == [0.5, 1.0]


def test_user_agent_set(sleeps):
    seen = []

    def handler(request):
        seen.append(request.headers["user-agent"])
        return httpx.Response(200)

    with _client(handler) as client:
        client.get("https://example.test/")

    assert seen == ["jobtracker/0.1 (+personal use)"]


def test_custom_headers_override_user_agent(sleeps):
    seen = []

    def handler(request):
        seen.append((request.headers["user-agent"], request.headers["x-api-key"]))
        return httpx.Response(200)

    with _client(handler, headers={"User-Agent": "custom", "X-Api-Key": "k"}) as client:
        client.get("https://example.test/")

    assert seen == [("custom", "k")]


def test_min_interval_between_requests(sleeps, monkeypatch):
    now = [100.0]
    monkeypatch.setattr(plugin_http.time, "monotonic", lambda: now[0])

    def handler(request):
        return httpx.Response(200)

    with _client(handler, min_interval=2.0) as client:
        client.get("https://example.test/")
        assert sleeps == []  # first request is not delayed
        now[0] = 100.5
        client.get("https://example.test/")
        assert sleeps == [pytest.approx(1.5)]
        now[0] = 110.0
        client.get("https://example.test/")
        assert sleeps == [pytest.approx(1.5)]  # interval already elapsed


def test_lowercase_user_agent_override_sends_single_value(sleeps):
    seen = []

    def handler(request):
        seen.append(request.headers.get_list("user-agent"))
        return httpx.Response(200)

    with _client(handler, headers={"user-agent": "custom"}) as client:
        client.get("https://example.test/")

    assert seen == [["custom"]]


class _FakeHTTPTransport(httpx.BaseTransport):
    instances: list = []

    def __init__(self, proxy=None, **kwargs):
        self.proxy = proxy
        type(self).instances.append(self)

    def handle_request(self, request):
        return httpx.Response(200, headers={"x-via": str(self.proxy)})


@pytest.fixture
def fake_transport(monkeypatch):
    for var in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY"):
        monkeypatch.delenv(var, raising=False)
        monkeypatch.delenv(var.lower(), raising=False)
    _FakeHTTPTransport.instances = []
    monkeypatch.setattr(plugin_http.httpx, "HTTPTransport", _FakeHTTPTransport)


def test_env_proxy_used_for_https(fake_transport, monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.test:3128")
    with plugin_http.make_client() as client:
        assert client.get("https://example.test/").headers["x-via"] == "http://proxy.test:3128"
        # no http proxy configured -> direct
        assert client.get("http://example.test/").headers["x-via"] == "None"


def test_no_proxy_host_goes_direct(fake_transport, monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.test:3128")
    monkeypatch.setenv("NO_PROXY", "internal.test,.corp.test")
    with plugin_http.make_client() as client:
        assert client.get("https://internal.test/").headers["x-via"] == "None"
        assert client.get("https://api.corp.test/").headers["x-via"] == "None"
        assert client.get("https://example.test/").headers["x-via"] == "http://proxy.test:3128"


def test_no_proxy_env_means_direct(fake_transport):
    with plugin_http.make_client() as client:
        assert client.get("https://example.test/").headers["x-via"] == "None"


def test_proxy_path_shares_retry_and_rate_limit(fake_transport, monkeypatch, sleeps):
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.test:3128")
    monkeypatch.setenv("NO_PROXY", "internal.test")
    clock = iter([0.0, 0.0, 0.0, 0.0])
    monkeypatch.setattr(plugin_http.time, "monotonic", lambda: next(clock, 0.0))
    with plugin_http.make_client(min_interval=1.0) as client:
        client.get("https://example.test/")  # via proxy
        client.get("https://internal.test/")  # direct, same limiter
    assert sleeps == [1.0]


@pytest.mark.parametrize("value", ["inf", "-inf", "nan", "-5"])
def test_non_finite_retry_after_falls_back_to_backoff(sleeps, value):
    statuses = iter([429, 200])

    def handler(request):
        status = next(statuses)
        return httpx.Response(status, headers={"Retry-After": value} if status == 429 else {})

    with _client(handler) as client:
        client.get("https://example.test/")

    assert sleeps == [0.5]


def test_huge_retry_after_is_capped(sleeps):
    statuses = iter([429, 200])

    def handler(request):
        status = next(statuses)
        return httpx.Response(status, headers={"Retry-After": "86400"} if status == 429 else {})

    with _client(handler) as client:
        client.get("https://example.test/")

    assert sleeps == [60]

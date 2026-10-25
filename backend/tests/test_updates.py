"""UpdateChecker: GitHub release lookup with injected transport (never the real API)."""

from datetime import UTC, datetime, timedelta

import httpx
import pytest
from packaging.version import Version

from app.services.updates import UpdateChecker, UpdateStatus, parse_version

REPO = "viktor-haag/ramen"
URL = "https://api.github.com/repos/viktor-haag/ramen/releases/latest"
T0 = datetime(2026, 10, 25, 12, 0, tzinfo=UTC)


class Clock:
    def __init__(self, now: datetime = T0) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


def make_checker(handler, current="0.1.0", clock=None):
    clock = clock or Clock()
    checker = UpdateChecker(
        REPO,
        current,
        client_factory=lambda: httpx.Client(transport=httpx.MockTransport(handler)),
        clock=clock,
    )
    return checker, clock


def release(tag="v0.2.0", **extra):
    body = {
        "tag_name": tag,
        "html_url": f"https://github.com/{REPO}/releases/tag/{tag}",
        "published_at": "2026-10-24T08:30:00Z",
        **extra,
    }
    return httpx.Response(200, json=body)


def test_newer_release_is_offered():
    seen: list[httpx.Request] = []

    def handler(request):
        seen.append(request)
        return release()

    checker, clock = make_checker(handler)
    status = checker.check()

    assert status.latest == "0.2.0"
    assert status.update_available is True
    assert status.release_url == f"https://github.com/{REPO}/releases/tag/v0.2.0"
    assert status.published_at == datetime(2026, 10, 24, 8, 30, tzinfo=UTC)
    assert status.checked_at == clock()
    assert status.error is None
    assert checker.status() == status
    assert len(seen) == 1
    assert str(seen[0].url) == URL
    assert seen[0].headers["accept"] == "application/vnd.github+json"
    assert seen[0].headers["user-agent"] == "RAMEN/0.1.0"


@pytest.mark.parametrize(
    ("current", "tag", "latest"),
    [
        ("0.1.0", "v0.1.0", "0.1.0"),
        ("0.1.0", "0.0.9", "0.0.9"),
        ("0.3.0", "v0.2.0", "0.2.0"),  # dev build newer than latest release
    ],
)
def test_same_or_older_is_not_offered(current, tag, latest):
    checker, _ = make_checker(lambda r: release(tag), current=current)
    status = checker.check()
    assert status.latest == latest
    assert status.update_available is False
    assert status.error is None


def test_update_available_without_latest_is_false():
    assert UpdateStatus(current="0.1.0").update_available is False
    assert UpdateStatus(current="not-a-version", latest="0.2.0").update_available is False


@pytest.mark.parametrize(
    "response",
    [
        release("v0.2.0-beta"),
        release("latest"),
        release("release-2"),
        httpx.Response(200, json={"html_url": "https://example.test"}),
        httpx.Response(200, json=["not", "an", "object"]),
        httpx.Response(200, json={"tag_name": 2}),
        httpx.Response(200, content=b"<html>not json</html>"),
    ],
)
def test_prerelease_or_garbage_tag_is_invalid(response):
    checker, clock = make_checker(lambda r: response)
    status = checker.check()
    assert status.error == "invalid_response"
    assert status.latest is None
    assert status.update_available is False
    assert status.checked_at == clock()


@pytest.mark.parametrize("exc", [httpx.ConnectError("boom"), httpx.ReadTimeout("slow")])
def test_network_error(exc):
    def handler(request):
        raise exc

    checker, clock = make_checker(handler)
    status = checker.check()  # must not raise
    assert status.error == "network"
    assert status.latest is None
    assert status.update_available is False
    assert status.checked_at == clock()


def test_client_factory_failure_is_reported_not_raised():
    def broken():
        raise RuntimeError("no client")

    checker = UpdateChecker(REPO, "0.1.0", client_factory=broken, clock=Clock())
    assert checker.check().error == "network"


@pytest.mark.parametrize(
    ("response", "code"),
    [
        (httpx.Response(403, headers={"x-ratelimit-remaining": "0"}), "rate_limited"),
        (httpx.Response(429), "rate_limited"),
        (httpx.Response(403), "http_403"),
        (httpx.Response(404), "http_404"),
        (httpx.Response(500), "http_500"),
    ],
)
def test_http_errors(response, code):
    checker, _ = make_checker(lambda r: response)
    status = checker.check()
    assert status.error == code
    assert status.update_available is False


def test_error_keeps_last_good_result():
    clock = Clock()
    state = {"fail": False}

    def handler(request):
        if state["fail"]:
            raise httpx.ConnectError("down")
        return release()

    checker, _ = make_checker(handler, clock=clock)
    checker.check()

    state["fail"] = True
    clock.now = T0 + timedelta(hours=12)
    status = checker.check()

    assert status.latest == "0.2.0"
    assert status.update_available is True
    assert status.release_url is not None
    assert status.error == "network"
    assert status.checked_at == T0 + timedelta(hours=12)


def test_success_after_error_clears_error():
    state = {"fail": True}

    def handler(request):
        if state["fail"]:
            return httpx.Response(500)
        return release()

    checker, _ = make_checker(handler)
    assert checker.check().error == "http_500"
    state["fail"] = False
    status = checker.check()
    assert status.error is None
    assert status.latest == "0.2.0"


def test_status_before_first_check():
    checker, _ = make_checker(lambda r: release())
    status = checker.status()
    assert status.current == "0.1.0"
    assert status.latest is None
    assert status.checked_at is None
    assert status.error is None
    assert status.update_available is False


def test_parse_version():
    assert parse_version("v1.2.3") == Version("1.2.3")
    assert parse_version("V1.2.3") == Version("1.2.3")
    assert parse_version("1.2") == Version("1.2")
    assert parse_version("v1.0.0rc1") is None
    assert parse_version("v1.0.0-beta") is None
    assert parse_version("x") is None
    assert parse_version("") is None

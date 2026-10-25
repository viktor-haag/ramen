import pickle

import httpx

from app.runner.failures import PluginFailure, failure_text, to_failure


def _status_error(code: int) -> httpx.HTTPStatusError:
    request = httpx.Request("GET", "https://rest.example.test/jobs?q=x")
    return httpx.HTTPStatusError("boom", request=request, response=httpx.Response(code, request=request))


def _raised(exc: BaseException) -> BaseException:
    try:
        raise exc
    except BaseException as caught:
        return caught


def test_http_status_error_becomes_readable_and_picklable():
    failure = to_failure(_raised(_status_error(429)))
    restored = pickle.loads(pickle.dumps(failure))
    assert isinstance(restored, PluginFailure)
    assert restored.summary == "HTTP 429 Too Many Requests (rest.example.test)"
    assert "HTTPStatusError" in restored.traceback_text and "Traceback" in restored.traceback_text
    assert failure_text(restored, 60) == "HTTP 429 Too Many Requests (rest.example.test)"


def test_request_error_names_host():
    request = httpx.Request("GET", "https://slow.example.test/")
    failure = to_failure(_raised(httpx.ConnectTimeout("timed out", request=request)))
    assert failure.summary == "ConnectTimeout: timed out (slow.example.test)"


def test_request_error_without_request_still_works():
    assert to_failure(_raised(httpx.ConnectError("dns"))).summary == "ConnectError: dns"


def test_other_exception_uses_type_and_message():
    failure = pickle.loads(pickle.dumps(to_failure(_raised(ValueError("bad page")))))
    assert failure.summary == "ValueError: bad page"
    assert str(failure) == "ValueError: bad page"


class Unpicklable(Exception):
    def __init__(self, *, thing):
        super().__init__("needs a thing")
        self.thing = thing


def test_custom_unpicklable_exception_is_wrapped():
    failure = pickle.loads(pickle.dumps(to_failure(_raised(Unpicklable(thing=object())))))
    assert failure.summary == "Unpicklable: needs a thing"

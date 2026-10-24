from types import SimpleNamespace

import pytest

from app.runner.failures import split_timeout

INFO = SimpleNamespace(timeout_seconds=120)


def test_missing_uses_plugin_default():
    assert split_timeout(INFO, None) == (120, {})
    assert split_timeout(INFO, {"a": 1}) == (120, {"a": 1})


def test_string_value_is_coerced():
    assert split_timeout(INFO, {"timeout_seconds": "30"}) == (30, {})


@pytest.mark.parametrize("bad", ["abc", None, 0, -5, "0", [1]])
def test_invalid_falls_back(bad):
    assert split_timeout(INFO, {"timeout_seconds": bad})[0] == 120


def test_key_removed_and_input_untouched():
    settings = {"timeout_seconds": 9, "max_results": 5}
    assert split_timeout(INFO, settings) == (9, {"max_results": 5})
    assert settings == {"timeout_seconds": 9, "max_results": 5}

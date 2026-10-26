import json
import traceback

import httpx2
import pytest

from app.llm.base import ImagePart, Message
from app.llm.errors import LLMError
from app.llm.factory import ConfigData, make_client

KEY = "sk-test-1234"
SCHEMA = {"type": "object", "properties": {"a": {"type": "integer"}}}


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda *_: None)  # SDK retry backoff


class Recorder:
    """MockTransport handler: replays queued responses, records outgoing requests."""

    def __init__(self, *responses):
        self.queue = list(responses)
        self.requests: list[httpx2.Request] = []

    def __call__(self, request):
        self.requests.append(request)
        r = self.queue.pop(0) if len(self.queue) > 1 else self.queue[0]
        return r

    @property
    def body(self):
        return json.loads(self.requests[-1].content)

    def client(self):
        return httpx2.Client(transport=httpx2.MockTransport(self))


def anthropic_ok(content=None, usage=True):
    data = {
        "id": "msg_1", "type": "message", "role": "assistant", "model": "claude-x",
        "content": content or [{"type": "text", "text": "hello"}],
        "stop_reason": "end_turn", "stop_sequence": None,
    }
    if usage:
        data["usage"] = {"input_tokens": 11, "output_tokens": 7}
    return httpx2.Response(200, json=data)


def openai_ok(content="hello", usage=True):
    data = {
        "id": "c1", "object": "chat.completion", "created": 1, "model": "gpt-x",
        "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": content}}],
    }
    if usage:
        data["usage"] = {"prompt_tokens": 13, "completion_tokens": 5, "total_tokens": 18}
    return httpx2.Response(200, json=data)


def cfg(provider, **kw):
    kw.setdefault("supports_images", provider != "openai_compatible")
    if provider == "openai_compatible":
        kw.setdefault("base_url", "http://localhost:1234/v1")
    return ConfigData(provider=provider, model="m-1", api_key=KEY, **kw)


def user(*parts):
    return [Message("user", list(parts))]


def run(config, rec, *parts, system="sys", **kw):
    return make_client(config, http_client=rec.client()).complete(system, user(*(parts or ("hi",))), **kw)


# ---------------- Anthropic ----------------

def test_anthropic_basic_body_and_result():
    rec = Recorder(anthropic_ok())
    res = run(cfg("anthropic"), rec)
    assert (res.text, res.input_tokens, res.output_tokens, res.estimated) == ("hello", 11, 7, False)
    assert str(rec.requests[0].url) == "https://api.anthropic.com/v1/messages"
    auth = rec.requests[0].headers
    assert KEY in (auth.get("x-api-key") or auth.get("authorization") or "")
    assert rec.body == {
        "model": "m-1", "max_tokens": 4096, "system": "sys",
        "messages": [{"role": "user", "content": [{"type": "text", "text": "hi"}]}],
    }


def test_anthropic_thinking_off_has_no_thinking_params():
    rec = Recorder(anthropic_ok())
    run(cfg("anthropic", thinking="off"), rec)
    assert "thinking" not in rec.body and "output_config" not in rec.body


def test_anthropic_thinking_high_adaptive_with_effort_and_large_max_tokens():
    rec = Recorder(anthropic_ok())
    run(cfg("anthropic", thinking="high"), rec)
    assert rec.body["thinking"] == {"type": "adaptive"}
    assert rec.body["output_config"] == {"effort": "high"}
    assert rec.body["max_tokens"] == 16000
    run(cfg("anthropic", thinking="high"), rec, max_tokens=30000)
    assert rec.body["max_tokens"] == 30000


def test_anthropic_extra_body_overrides_and_headers_sent():
    rec = Recorder(anthropic_ok())
    run(cfg("anthropic", extra_body={"max_tokens": 10, "custom": 1}, extra_headers={"X-Org": "acme"}), rec)
    assert rec.body["max_tokens"] == 10 and rec.body["custom"] == 1
    assert rec.requests[0].headers["x-org"] == "acme"


def test_anthropic_image_part_shape():
    rec = Recorder(anthropic_ok())
    run(cfg("anthropic"), rec, "look", ImagePart(b"\x89PNG", "image/png"))
    assert rec.body["messages"][0]["content"] == [
        {"type": "text", "text": "look"},
        {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "iVBORw=="}},
    ]


def test_anthropic_json_schema_appended_to_system():
    rec = Recorder(anthropic_ok())
    run(cfg("anthropic"), rec, json_schema=SCHEMA)
    assert rec.body["system"].startswith("sys\n\nRespond only with JSON matching this schema: ")
    assert json.dumps(SCHEMA) in rec.body["system"]
    assert "response_format" not in rec.body


def test_anthropic_ignores_thinking_blocks_in_text():
    rec = Recorder(anthropic_ok([
        {"type": "thinking", "thinking": "hmm", "signature": "s"},
        {"type": "text", "text": "a"}, {"type": "text", "text": "b"},
    ]))
    assert run(cfg("anthropic"), rec).text == "ab"


def test_anthropic_thinking_only_response_is_invalid_output():
    rec = Recorder(anthropic_ok([{"type": "thinking", "thinking": "hmm", "signature": "s"}]))
    with pytest.raises(LLMError) as e:
        run(cfg("anthropic"), rec)
    assert e.value.code == "llm_invalid_output"


def test_anthropic_missing_usage_is_estimated():
    rec = Recorder(anthropic_ok([{"type": "text", "text": "abcdefgh"}], usage=False))
    res = run(cfg("anthropic"), rec, "x" * 40, system="y" * 8)
    assert (res.input_tokens, res.output_tokens, res.estimated) == (12, 2, True)


def test_anthropic_base_url_and_list_models():
    rec = Recorder(httpx2.Response(200, json={
        "data": [
            {"type": "model", "id": "claude-a", "display_name": "A", "created_at": "2025-01-01T00:00:00Z"},
            {"type": "model", "id": "claude-b", "display_name": "B", "created_at": "2025-01-01T00:00:00Z"},
        ],
        "has_more": False, "first_id": "claude-a", "last_id": "claude-b",
    }))
    client = make_client(cfg("anthropic", base_url="https://proxy.example/anthropic"), http_client=rec.client())
    assert client.list_models() == ["claude-a", "claude-b"]
    assert str(rec.requests[0].url).startswith("https://proxy.example/anthropic/v1/models")


# ---------------- OpenAI ----------------

def test_openai_basic_body_and_result():
    rec = Recorder(openai_ok())
    res = run(cfg("openai"), rec)
    assert (res.text, res.input_tokens, res.output_tokens, res.estimated) == ("hello", 13, 5, False)
    assert str(rec.requests[0].url) == "https://api.openai.com/v1/chat/completions"
    assert rec.requests[0].headers["authorization"] == f"Bearer {KEY}"
    assert rec.body == {
        "model": "m-1", "max_completion_tokens": 4096,
        "messages": [{"role": "system", "content": "sys"}, {"role": "user", "content": "hi"}],
    }


def test_openai_reasoning_effort_off_vs_high():
    rec = Recorder(openai_ok())
    run(cfg("openai", thinking="off"), rec)
    assert "reasoning_effort" not in rec.body
    run(cfg("openai", thinking="high"), rec)
    assert rec.body["reasoning_effort"] == "high"
    assert rec.body["max_completion_tokens"] == 16000


def test_openai_extra_body_overrides_and_headers_sent():
    rec = Recorder(openai_ok())
    run(cfg("openai", extra_body={"max_completion_tokens": 10, "seed": 3}, extra_headers={"X-Org": "acme"}), rec)
    assert rec.body["max_completion_tokens"] == 10 and rec.body["seed"] == 3
    assert rec.requests[0].headers["x-org"] == "acme"


def test_openai_image_part_shape():
    rec = Recorder(openai_ok())
    run(cfg("openai"), rec, "look", ImagePart(b"\x89PNG", "image/png"))
    assert rec.body["messages"][1]["content"] == [
        {"type": "text", "text": "look"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,iVBORw=="}},
    ]


def test_openai_json_schema_uses_response_format():
    rec = Recorder(openai_ok())
    run(cfg("openai"), rec, json_schema=SCHEMA)
    assert rec.body["response_format"] == {
        "type": "json_schema", "json_schema": {"name": "result", "schema": SCHEMA, "strict": True},
    }
    assert rec.body["messages"][0]["content"] == "sys"


def test_compatible_uses_base_url_prompt_schema_and_no_reasoning():
    rec = Recorder(openai_ok())
    config = cfg("openai_compatible", base_url="http://localhost:1234/v1", thinking="high")
    run(config, rec, json_schema=SCHEMA)
    assert str(rec.requests[0].url) == "http://localhost:1234/v1/chat/completions"
    assert "response_format" not in rec.body and "reasoning_effort" not in rec.body
    assert rec.body["max_tokens"] == 4096 and "max_completion_tokens" not in rec.body
    assert "Respond only with JSON matching this schema" in rec.body["messages"][0]["content"]


def test_compatible_without_api_key_still_constructs():
    rec = Recorder(openai_ok())
    config = ConfigData(provider="openai_compatible", model="m", supports_images=False, base_url="http://localhost:1234/v1")
    assert run(config, rec).text == "hello"


def test_openai_null_content_is_invalid_output():
    rec = Recorder(openai_ok(content=None))
    with pytest.raises(LLMError) as e:
        run(cfg("openai"), rec)
    assert e.value.code == "llm_invalid_output"


def test_openai_missing_usage_is_estimated():
    rec = Recorder(openai_ok("abcdefgh", usage=False))
    res = run(cfg("openai"), rec, "x" * 40, system="y" * 8)
    assert (res.input_tokens, res.output_tokens, res.estimated) == (12, 2, True)


def test_openai_list_models():
    rec = Recorder(httpx2.Response(200, json={"object": "list", "data": [
        {"id": "gpt-a", "object": "model", "created": 1, "owned_by": "o"},
        {"id": "gpt-b", "object": "model", "created": 2, "owned_by": "o"},
    ]}))
    client = make_client(cfg("openai"), http_client=rec.client())
    assert client.list_models() == ["gpt-a", "gpt-b"]
    assert str(rec.requests[0].url) == "https://api.openai.com/v1/models"


# ---------------- Errors (both SDKs) ----------------

PROVIDERS = [("anthropic", anthropic_ok), ("openai", openai_ok)]


@pytest.mark.parametrize("provider", ["anthropic", "openai"])
@pytest.mark.parametrize("status,code", [(401, "llm_auth_failed"), (403, "llm_auth_failed"),
                                         (400, "llm_bad_request"), (404, "llm_bad_request"),
                                         (422, "llm_bad_request")])
def test_status_mapping(provider, status, code):
    rec = Recorder(httpx2.Response(status, json={"error": {"message": "nope", "type": "x"}}))
    with pytest.raises(LLMError) as e:
        run(cfg(provider), rec)
    assert e.value.code == code
    assert len(rec.requests) == 1  # not retried


@pytest.mark.parametrize("provider,ok", PROVIDERS)
def test_rate_limit_then_success_is_retried(provider, ok):
    rec = Recorder(httpx2.Response(429, json={"error": {"message": "slow down"}}), ok())
    assert run(cfg(provider), rec).text == "hello"
    assert len(rec.requests) == 2


@pytest.mark.parametrize("provider", ["anthropic", "openai"])
def test_persistent_429_maps_to_rate_limited(provider):
    rec = Recorder(httpx2.Response(429, json={"error": {"message": "slow down"}}))
    with pytest.raises(LLMError) as e:
        run(cfg(provider), rec)
    assert e.value.code == "llm_rate_limited"


@pytest.mark.parametrize("provider", ["anthropic", "openai"])
def test_server_error_three_times_is_unavailable(provider):
    rec = Recorder(httpx2.Response(500, json={"error": {"message": "boom"}}))
    with pytest.raises(LLMError) as e:
        run(cfg(provider), rec)
    assert e.value.code == "llm_unavailable"
    assert len(rec.requests) == 3  # 1 try + 2 retries


@pytest.mark.parametrize("provider", ["anthropic", "openai"])
def test_connection_error_is_unavailable(provider):
    def boom(request):
        raise httpx2.ConnectError("refused", request=request)

    client = make_client(cfg(provider), http_client=httpx2.Client(transport=httpx2.MockTransport(boom)))
    with pytest.raises(LLMError) as e:
        client.complete("s", user("hi"))
    assert e.value.code == "llm_unavailable"


@pytest.mark.parametrize("provider", ["anthropic", "openai"])
def test_timeout_is_llm_timeout(provider):
    def slow(request):
        raise httpx2.ReadTimeout("slow", request=request)

    client = make_client(cfg(provider), http_client=httpx2.Client(transport=httpx2.MockTransport(slow)))
    with pytest.raises(LLMError) as e:
        client.complete("s", user("hi"))
    assert e.value.code == "llm_timeout"


@pytest.mark.parametrize("provider", ["anthropic", "openai"])
def test_bad_request_reason_never_contains_api_key(provider):
    rec = Recorder(httpx2.Response(400, json={"error": {"message": f"Invalid key {KEY} for model", "type": "x"}}))
    with pytest.raises(LLMError) as e:
        run(cfg(provider), rec)
    assert e.value.code == "llm_bad_request"
    assert KEY not in e.value.reason and "Invalid key" in e.value.reason


@pytest.mark.parametrize("provider", ["anthropic", "openai"])
def test_list_models_errors_are_translated(provider):
    rec = Recorder(httpx2.Response(401, json={"error": {"message": "bad key"}}))
    client = make_client(cfg(provider), http_client=rec.client())
    with pytest.raises(LLMError) as e:
        client.list_models()
    assert e.value.code == "llm_auth_failed"


# ---------------- Fix round 1 ----------------

@pytest.mark.parametrize("provider", ["anthropic", "openai"])
def test_error_chain_does_not_leak_api_key(provider):
    rec = Recorder(httpx2.Response(400, json={"error": {"message": f"bad key {KEY}", "type": "x"}}))
    with pytest.raises(LLMError) as e:
        run(cfg(provider), rec)
    assert e.value.__cause__ is None and e.value.__context__ is None
    assert KEY not in "".join(traceback.format_exception(e.value))


@pytest.mark.parametrize("provider", ["anthropic", "openai"])
def test_invalid_output_error_has_no_chain_either(provider):
    rec = Recorder(anthropic_ok([{"type": "thinking", "thinking": "h", "signature": "s"}]) if provider == "anthropic"
                   else openai_ok(None))
    with pytest.raises(LLMError) as e:
        run(cfg(provider), rec)
    assert e.value.__cause__ is None


def test_config_data_repr_hides_secrets():
    c = cfg("openai", extra_headers={"Authorization": "Bearer sk-secret-9999"})
    assert KEY not in repr(c) and "sk-secret-9999" not in repr(c)


def test_anthropic_null_content_is_invalid_output():
    data = {"id": "m", "type": "message", "role": "assistant", "model": "x", "content": None,
            "stop_reason": "end_turn", "usage": {"input_tokens": 1, "output_tokens": 1}}
    with pytest.raises(LLMError) as e:
        run(cfg("anthropic"), Recorder(httpx2.Response(200, json=data)))
    assert e.value.code == "llm_invalid_output"


def test_anthropic_null_text_block_is_invalid_output():
    with pytest.raises(LLMError) as e:
        run(cfg("anthropic"), Recorder(anthropic_ok([{"type": "text", "text": None}])))
    assert e.value.code == "llm_invalid_output"


@pytest.mark.parametrize("provider", ["anthropic", "openai"])
def test_html_200_body_is_invalid_output(provider):
    rec = Recorder(httpx2.Response(200, text="<html>Gateway</html>", headers={"content-type": "text/html"}))
    with pytest.raises(LLMError) as e:
        run(cfg(provider), rec)
    assert e.value.code == "llm_invalid_output"


@pytest.mark.parametrize("provider", ["openai", "openai_compatible"])
@pytest.mark.parametrize("choices", [
    [{"index": 0, "finish_reason": "stop", "message": None}],
    [],
    None,
])
def test_openai_odd_choices_are_invalid_output(provider, choices):
    data = {"id": "c", "object": "chat.completion", "created": 1, "model": "m", "choices": choices,
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}
    with pytest.raises(LLMError) as e:
        run(cfg(provider), Recorder(httpx2.Response(200, json=data)))
    assert e.value.code == "llm_invalid_output"


@pytest.mark.parametrize("provider", ["anthropic", "openai", "openai_compatible"])
def test_missing_key_fails_up_front_even_with_env_key(provider, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-env-1")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-env-2")
    rec = Recorder(anthropic_ok() if provider == "anthropic" else openai_ok())
    config = ConfigData(provider=provider, model="m", supports_images=True, base_url="http://x.test/v1")
    if provider == "openai_compatible":
        assert run(config, rec).text == "hello"  # keyless local servers are allowed
        assert "sk-env-2" not in rec.requests[0].headers.get("authorization", "")
        return
    with pytest.raises(LLMError) as e:
        run(config, rec)
    assert e.value.code == "llm_auth_failed"
    assert rec.requests == []


@pytest.mark.parametrize("provider", ["anthropic", "openai"])
def test_non_sdk_exceptions_propagate_as_bugs(provider, monkeypatch):
    client = make_client(cfg(provider), http_client=Recorder(anthropic_ok()).client())
    target = client._client.messages if provider == "anthropic" else client._client.chat.completions

    def broken(*a, **kw):
        raise RuntimeError("bug")

    monkeypatch.setattr(target, "create", broken)
    with pytest.raises(RuntimeError):
        client.complete("s", user("hi"))


@pytest.mark.parametrize("provider", ["anthropic", "openai"])
def test_response_validation_error_is_invalid_output(provider):
    import anthropic
    import openai

    from app.llm.errors import map_sdk_error

    resp = httpx2.Response(200, request=httpx2.Request("POST", "https://x.test"))
    exc = (anthropic if provider == "anthropic" else openai).APIResponseValidationError(resp, None)
    assert map_sdk_error(exc, KEY).code == "llm_invalid_output"


def test_3xx_status_error_is_bad_request():
    import anthropic

    from app.llm.errors import map_sdk_error

    resp = httpx2.Response(302, request=httpx2.Request("POST", "https://x.test"))
    assert map_sdk_error(anthropic.APIStatusError("moved", response=resp, body=None), KEY).code == "llm_bad_request"


@pytest.mark.parametrize("provider,ok", PROVIDERS)
def test_env_does_not_override_config(provider, ok, monkeypatch):
    for k in ("ANTHROPIC_BASE_URL", "OPENAI_BASE_URL"):
        monkeypatch.setenv(k, "https://evil.test")
    monkeypatch.setenv("OPENAI_ORG_ID", "org-env")
    monkeypatch.setenv("OPENAI_PROJECT_ID", "proj-env")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "tok-env")
    rec = Recorder(ok())
    run(cfg(provider), rec)
    req = rec.requests[0]
    assert req.url.host in ("api.anthropic.com", "api.openai.com")
    assert "openai-organization" not in req.headers and "openai-project" not in req.headers
    assert "tok-env" not in req.headers.get("authorization", "")


def test_compatible_without_base_url_fails_fast_even_with_env_base_url(monkeypatch):
    monkeypatch.setenv("OPENAI_BASE_URL", "https://evil.test")
    config = ConfigData(provider="openai_compatible", model="m", supports_images=False, api_key=KEY)
    with pytest.raises(LLMError) as e:
        make_client(config)
    assert e.value.code == "llm_bad_request"


def test_anthropic_partial_usage_estimates_only_missing_count():
    data = {"id": "m", "type": "message", "role": "assistant", "model": "x",
            "content": [{"type": "text", "text": "abcdefgh"}], "stop_reason": "end_turn",
            "usage": {"input_tokens": 11}}
    res = run(cfg("anthropic"), Recorder(httpx2.Response(200, json=data)))
    assert (res.input_tokens, res.output_tokens, res.estimated) == (11, 2, True)


def test_openai_partial_usage_estimates_only_missing_count():
    data = {"id": "c", "object": "chat.completion", "created": 1, "model": "m",
            "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": "abcdefgh"}}],
            "usage": {"completion_tokens": 9}}
    res = run(cfg("openai"), Recorder(httpx2.Response(200, json=data)), "x" * 40, system="y" * 8)
    assert (res.input_tokens, res.output_tokens, res.estimated) == (12, 9, True)


def test_openai_compatible_list_content_parts_are_joined():
    content = [{"type": "text", "text": "foo"}, {"type": "text", "text": "bar"}]
    assert run(cfg("openai_compatible"), Recorder(openai_ok(content))).text == "foobar"


def test_supports_images_has_no_default():
    with pytest.raises(TypeError):
        ConfigData(provider="openai", model="m")


def test_sdk_built_client_honours_proxy_env(monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.test:3128")
    client = make_client(cfg("anthropic"))
    assert client._client._client._mounts  # per-scheme proxy transports were built from the env


# ---------------- Fix round 2 ----------------

BROKEN_JSON = httpx2.Response(200, content=b'{"broken', headers={"content-type": "application/json"})


@pytest.mark.parametrize("provider", ["anthropic", "openai"])
def test_malformed_json_body_is_invalid_output(provider):
    with pytest.raises(LLMError) as e:
        run(cfg(provider), Recorder(BROKEN_JSON))
    assert e.value.code == "llm_invalid_output"
    assert e.value.__cause__ is None and e.value.__context__ is None


@pytest.mark.parametrize("provider", ["anthropic", "openai"])
def test_malformed_json_body_in_list_models_is_invalid_output(provider):
    client = make_client(cfg(provider), http_client=Recorder(BROKEN_JSON).client())
    with pytest.raises(LLMError) as e:
        client.list_models()
    assert e.value.code == "llm_invalid_output"


@pytest.mark.parametrize("provider", ["anthropic", "openai"])
@pytest.mark.parametrize("key", ["", "   ", "\t\n"])
def test_blank_api_key_counts_as_missing(provider, key):
    config = ConfigData(provider=provider, model="m", supports_images=True, api_key=key)
    with pytest.raises(LLMError) as e:
        make_client(config)
    assert e.value.code == "llm_auth_failed"

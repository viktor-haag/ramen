import json

import httpx2
import pytest

from app.llm.base import Message
from app.llm.errors import LLMError
from app.llm.factory import ConfigData, make_client

KEY = "sk-test-1234"
SSE = {"content-type": "text/event-stream"}


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda *_: None)  # SDK retry backoff


class Recorder:
    """MockTransport handler: replays queued responses (factories), records outgoing requests."""

    def __init__(self, *responses):
        self.queue = list(responses)
        self.requests: list[httpx2.Request] = []

    def __call__(self, request):
        self.requests.append(request)
        make = self.queue.pop(0) if len(self.queue) > 1 else self.queue[0]
        return make()

    @property
    def body(self):
        return json.loads(self.requests[-1].content)

    def client(self):
        return httpx2.Client(transport=httpx2.MockTransport(self))


def cfg(provider, **kw):
    kw.setdefault("supports_images", provider != "openai_compatible")
    if provider == "openai_compatible":
        kw.setdefault("base_url", "http://localhost:1234/v1")
    return ConfigData(provider=provider, model="m-1", api_key=KEY, **kw)


def user(*parts):
    return [Message("user", list(parts))]


def stream(config, rec, *parts, system="sys", chunks: list[str] | None = None, **kw):
    """Run `stream`; pass your own `chunks` list to inspect the on_text calls after an error."""
    chunks = [] if chunks is None else chunks
    client = make_client(config, http_client=rec.client())
    res = client.stream(system, user(*(parts or ("hi",))), on_text=chunks.append, **kw)
    return res, chunks


def sse_response(frames: list[bytes], *, fail: Exception | None = None):
    """A streamed 200 body; with `fail`, the body breaks after the frames were delivered."""

    def body():
        yield from frames
        if fail is not None:
            raise fail

    return lambda: httpx2.Response(200, headers=SSE, content=body())


# ---------------- Anthropic wire format ----------------

def a_event(name: str, data: dict) -> bytes:
    return f"event: {name}\ndata: {json.dumps(data)}\n\n".encode()


def a_start(input_tokens=11):
    return a_event("message_start", {"type": "message_start", "message": {
        "id": "msg_1", "type": "message", "role": "assistant", "model": "claude-x", "content": [],
        "stop_reason": None, "stop_sequence": None,
        "usage": {"input_tokens": input_tokens, "output_tokens": 1},
    }})


def a_text_block(index: int, pieces: list[str]) -> list[bytes]:
    out = [a_event("content_block_start", {"type": "content_block_start", "index": index,
                                           "content_block": {"type": "text", "text": ""}})]
    out += [a_event("content_block_delta", {"type": "content_block_delta", "index": index,
                                            "delta": {"type": "text_delta", "text": p}}) for p in pieces]
    out.append(a_event("content_block_stop", {"type": "content_block_stop", "index": index}))
    return out


def a_thinking_block(index: int, thought: str) -> list[bytes]:
    return [
        a_event("content_block_start", {"type": "content_block_start", "index": index,
                                        "content_block": {"type": "thinking", "thinking": "", "signature": ""}}),
        a_event("content_block_delta", {"type": "content_block_delta", "index": index,
                                        "delta": {"type": "thinking_delta", "thinking": thought}}),
        a_event("content_block_delta", {"type": "content_block_delta", "index": index,
                                        "delta": {"type": "signature_delta", "signature": "sig"}}),
        a_event("content_block_stop", {"type": "content_block_stop", "index": index}),
    ]


def a_end(output_tokens=7):
    return [
        a_event("message_delta", {"type": "message_delta",
                                  "delta": {"stop_reason": "end_turn", "stop_sequence": None},
                                  "usage": {"output_tokens": output_tokens}}),
        a_event("message_stop", {"type": "message_stop"}),
    ]


def anthropic_stream(pieces=("Hal", "lo")):
    return sse_response([a_start(), *a_text_block(0, list(pieces)), *a_end()])


# ---------------- OpenAI wire format ----------------

def o_chunk(delta: dict | None = None, *, usage: dict | None = None, finish=None) -> bytes:
    data = {"id": "c1", "object": "chat.completion.chunk", "created": 1, "model": "gpt-x",
            "choices": [] if delta is None else [{"index": 0, "delta": delta, "finish_reason": finish}]}
    if usage is not None:
        data["usage"] = usage
    return f"data: {json.dumps(data)}\n\n".encode()


DONE = b"data: [DONE]\n\n"


def openai_stream(pieces=("Hal", "lo"), usage=True):
    frames = [o_chunk({"role": "assistant", "content": ""})]
    frames += [o_chunk({"content": p}) for p in pieces]
    frames.append(o_chunk({}, finish="stop"))
    if usage:
        frames.append(o_chunk(usage={"prompt_tokens": 13, "completion_tokens": 5, "total_tokens": 18}))
    frames.append(DONE)
    return sse_response(frames)


# ---------------- Anthropic ----------------

def test_anthropic_stream_text_and_usage():
    rec = Recorder(anthropic_stream())
    res, chunks = stream(cfg("anthropic"), rec)
    assert chunks == ["Hal", "lo"]
    assert (res.text, res.input_tokens, res.output_tokens, res.estimated) == ("Hallo", 11, 7, False)
    assert str(rec.requests[0].url) == "https://api.anthropic.com/v1/messages"
    assert rec.body == {
        "model": "m-1", "max_tokens": 4096, "system": "sys", "stream": True,
        "messages": [{"role": "user", "content": [{"type": "text", "text": "hi"}]}],
    }


def test_anthropic_stream_ignores_thinking():
    rec = Recorder(sse_response([a_start(), *a_thinking_block(0, "secret plan"), *a_text_block(1, ["ok"]),
                                 *a_end()]))
    res, chunks = stream(cfg("anthropic"), rec)
    assert chunks == ["ok"]
    assert res.text == "ok"


def test_anthropic_stream_sends_same_params_as_complete():
    rec = Recorder(anthropic_stream())
    config = cfg("anthropic", thinking="high", extra_body={"custom": 1}, extra_headers={"X-Org": "acme"})
    stream(config, rec)
    assert rec.body["thinking"] == {"type": "adaptive"}
    assert rec.body["output_config"] == {"effort": "high"}
    assert rec.body["max_tokens"] == 16000
    assert rec.body["custom"] == 1
    assert rec.requests[0].headers["x-org"] == "acme"


@pytest.mark.parametrize("kind,code", [("overloaded_error", "llm_unavailable"), ("api_error", "llm_unavailable"),
                                       ("rate_limit_error", "llm_rate_limited")])
def test_anthropic_stream_error_event_midway(kind, code):
    err = a_event("error", {"type": "error", "error": {"type": kind, "message": "Overloaded"}})
    rec = Recorder(sse_response([a_start(), *a_text_block(0, ["Hal"])[:2], err]))
    chunks: list[str] = []
    with pytest.raises(LLMError) as e:
        stream(cfg("anthropic"), rec, chunks=chunks)
    assert e.value.code == code
    assert chunks == ["Hal"]
    assert e.value.__cause__ is None and e.value.__context__ is None


# ---------------- OpenAI ----------------

@pytest.mark.parametrize("provider", ["openai", "openai_compatible"])
def test_openai_stream_text_and_usage(provider):
    rec = Recorder(openai_stream())
    res, chunks = stream(cfg(provider), rec)
    assert chunks == ["Hal", "lo"]
    assert (res.text, res.input_tokens, res.output_tokens, res.estimated) == ("Hallo", 13, 5, False)
    assert rec.body["stream"] is True
    assert rec.body["stream_options"] == {"include_usage": True}
    assert rec.body["messages"] == [{"role": "system", "content": "sys"}, {"role": "user", "content": "hi"}]
    limit = "max_completion_tokens" if provider == "openai" else "max_tokens"
    assert rec.body[limit] == 4096


def test_openai_stream_sends_same_params_as_complete():
    rec = Recorder(openai_stream())
    stream(cfg("openai", thinking="high", extra_body={"seed": 3}, extra_headers={"X-Org": "acme"}), rec)
    assert rec.body["reasoning_effort"] == "high"
    assert rec.body["max_completion_tokens"] == 16000
    assert rec.body["seed"] == 3
    assert rec.requests[0].headers["x-org"] == "acme"
    assert "response_format" not in rec.body


def test_openai_compatible_stream_without_usage_estimates():
    rec = Recorder(openai_stream(("abcd", "efgh"), usage=False))
    res, _ = stream(cfg("openai_compatible"), rec, "x" * 40, system="y" * 8)
    assert res.text == "abcdefgh"
    assert (res.input_tokens, res.output_tokens, res.estimated) == (12, 2, True)


def test_openai_stream_error_chunk_midway_is_unavailable():
    err = b'data: {"error": {"message": "server overloaded", "type": "server_error"}}\n\n'
    rec = Recorder(sse_response([o_chunk({"role": "assistant", "content": "Hal"}), err]))
    chunks: list[str] = []
    with pytest.raises(LLMError) as e:
        stream(cfg("openai"), rec, chunks=chunks)
    assert e.value.code == "llm_unavailable"
    assert chunks == ["Hal"]


# ---------------- Both ----------------

def first_piece(provider) -> list[bytes]:
    if provider == "anthropic":
        return [a_start(), *a_text_block(0, ["Hal"])[:2]]
    return [o_chunk({"role": "assistant", "content": "Hal"})]


@pytest.mark.parametrize("provider", ["anthropic", "openai", "openai_compatible"])
@pytest.mark.parametrize("fail,code", [
    (httpx2.ReadError("connection reset"), "llm_unavailable"),
    (httpx2.ReadTimeout("slow"), "llm_timeout"),
])
def test_stream_error_midway(provider, fail, code):
    rec = Recorder(sse_response(first_piece(provider), fail=fail))
    chunks: list[str] = []
    with pytest.raises(LLMError) as e:
        stream(cfg(provider), rec, chunks=chunks)
    assert e.value.code == code
    assert chunks == ["Hal"]  # the piece before the break, nothing after
    assert e.value.__cause__ is None and e.value.__context__ is None


@pytest.mark.parametrize("provider", ["anthropic", "openai"])
@pytest.mark.parametrize("status", [500, 529])
def test_stream_server_error_on_setup_is_unavailable(provider, status):
    rec = Recorder(lambda: httpx2.Response(status, json={"error": {"message": "boom"}}))
    chunks: list[str] = []
    with pytest.raises(LLMError) as e:
        stream(cfg(provider), rec, chunks=chunks)
    assert e.value.code == "llm_unavailable"
    assert chunks == []
    assert len(rec.requests) == 3  # 1 try + 2 retries, like complete


@pytest.mark.parametrize("provider", ["anthropic", "openai"])
def test_stream_auth_error_on_setup(provider):
    rec = Recorder(lambda: httpx2.Response(401, json={"error": {"message": f"bad key {KEY}", "type": "x"}}))
    chunks: list[str] = []
    with pytest.raises(LLMError) as e:
        stream(cfg(provider), rec, chunks=chunks)
    assert e.value.code == "llm_auth_failed"
    assert KEY not in e.value.reason
    assert e.value.__cause__ is None and e.value.__context__ is None


@pytest.mark.parametrize("provider", ["anthropic", "openai", "openai_compatible"])
@pytest.mark.parametrize("pieces", [(), ("  ", "\n")])
def test_stream_empty_text(provider, pieces):
    make = anthropic_stream(pieces) if provider == "anthropic" else openai_stream(pieces)
    with pytest.raises(LLMError) as e:
        stream(cfg(provider), Recorder(make))
    assert e.value.code == "llm_invalid_output"


@pytest.mark.parametrize("provider", ["anthropic", "openai"])
def test_stream_on_text_exception_propagates_unmapped(provider):
    class Boom(ValueError):
        pass

    def on_text(_):
        raise Boom("callback bug")

    make = anthropic_stream() if provider == "anthropic" else openai_stream()
    client = make_client(cfg(provider), http_client=Recorder(make).client())
    with pytest.raises(Boom):
        client.stream("sys", user("hi"), on_text=on_text)


@pytest.mark.parametrize("provider", ["anthropic", "openai"])
def test_stream_rejects_json_schema(provider):
    client = make_client(cfg(provider), http_client=Recorder(anthropic_stream()).client())
    with pytest.raises(TypeError):
        client.stream("sys", user("hi"), on_text=lambda _: None, json_schema={"type": "object"})

import pytest

from app.llm.base import LLMResult
from app.llm.errors import LLMError

KEY = "sk-test-1234"
LEAK = "sk-leak-9876"


def body(**kw) -> dict:
    return {"name": "A", "provider": "anthropic", "model": "claude-x", "api_key": KEY, **kw}


def create(client, **kw) -> dict:
    res = client.post("/api/llm/configs", json=body(**kw))
    assert res.status_code == 200, res.text
    return res.json()


class FakeClient:
    def __init__(self, cfg, result=None, error=None):
        self.cfg, self.result, self.error = cfg, result, error

    def complete(self, system, messages, *, json_schema=None, max_tokens=4096):
        if self.error:
            raise self.error
        return self.result or LLMResult("OK", 5, 2, False)

    def list_models(self):
        if self.error:
            raise self.error
        return ["m1", "m2"]


@pytest.fixture
def fake(monkeypatch):
    """Patch the factory used by the runner; `state.error` / `state.result` steer the fake."""

    class State:
        error = None
        result = None
        made = []

    def make(cfg, **_):
        State.made.append(cfg)
        return FakeClient(cfg, State.result, State.error)

    monkeypatch.setattr("app.llm.runner.make_client", make)
    return State


# --- CRUD, masking ---------------------------------------------------------------------------

def test_create_masks_key_and_first_becomes_default(client):
    first = create(client)
    assert first["api_key"] == "…1234" and first["has_api_key"] is True and first["is_default"] is True
    assert first["supports_images"] is True and first["thinking"] == "off"
    second = create(client, name="B")
    assert second["is_default"] is False
    assert KEY not in client.get("/api/llm/configs").text
    assert KEY not in client.get(f"/api/llm/configs/{first['id']}").text


def test_mask_key_follows_spec(client):
    assert create(client, api_key="abcd")["api_key"] == "…"  # nothing beyond the tail to hide
    assert create(client, name="B", api_key="abcde")["api_key"] == "…bcde"


def test_put_keeps_clears_and_replaces_key(client):
    cfg = create(client)
    url = f"/api/llm/configs/{cfg['id']}"
    keep = client.put(url, json={k: v for k, v in body(model="m2").items() if k != "api_key"})
    assert keep.status_code == 200 and keep.json()["api_key"] == "…1234" and keep.json()["model"] == "m2"
    assert KEY not in keep.text
    replaced = client.put(url, json=body(api_key="sk-new-5678"))
    assert replaced.json()["api_key"] == "…5678"
    cleared = client.put(url, json=body(api_key=""))
    assert cleared.json()["api_key"] is None and cleared.json()["has_api_key"] is False


def test_supports_images_defaults_per_provider_and_can_be_set(client):
    compat = create(client, name="L", provider="openai_compatible", base_url="http://x/v1", api_key=None)
    assert compat["supports_images"] is False
    assert create(client, name="O", provider="openai")["supports_images"] is True
    assert create(client, name="X", supports_images=False)["supports_images"] is False
    # PUT without the field keeps the stored value
    res = client.put(f"/api/llm/configs/{compat['id']}", json={
        "name": "L", "provider": "openai_compatible", "model": "m", "base_url": "http://x/v1", "supports_images": True})
    assert res.json()["supports_images"] is True
    res = client.put(f"/api/llm/configs/{compat['id']}", json={
        "name": "L", "provider": "openai_compatible", "model": "m", "base_url": "http://x/v1"})
    assert res.json()["supports_images"] is True


def test_duplicate_name_409(client):
    create(client)
    res = client.post("/api/llm/configs", json=body())
    assert res.status_code == 409 and res.json()["code"] == "llm_config_name_taken"


def test_unknown_config_404(client):
    for res in (client.get("/api/llm/configs/99"), client.put("/api/llm/configs/99", json=body()),
                client.delete("/api/llm/configs/99"), client.post("/api/llm/configs/99/default"),
                client.post("/api/llm/configs/99/test")):
        assert res.status_code == 404 and res.json()["code"] == "llm_config_not_found"


@pytest.mark.parametrize("override", [
    {"provider": "openai_compatible", "api_key": None},  # base_url missing
    {"provider": "openai_compatible", "base_url": "  ", "api_key": None},
    {"base_url": "http://x/v1"},  # base_url only for openai_compatible
    {"api_key": None},  # key required on create
    {"api_key": "  "},
    {"provider": "openai_compatible", "base_url": "http://x/v1", "thinking": "high"},
    {"thinking": "extreme"},
    {"provider": "gemini"},
    {"name": ""},
    {"model": ""},
    {"extra_body": [1]},
    {"extra_body": "x"},
    {"extra_headers": {"X": 1}},
    {"extra_headers": ["a"]},
    {"price_in": -1},
    {"price_out": -0.5},
])
def test_create_validation_422(client, override):
    res = client.post("/api/llm/configs", json=body(**override))
    assert res.status_code == 422, res.text
    assert res.json()["code"] == "validation_error"


def test_compatible_without_key_ok_and_thinking_for_others(client):
    cfg = create(client, provider="openai_compatible", base_url="http://x/v1", api_key=None,
                 extra_body={"a": {"b": 1}}, extra_headers={"X-A": "1"}, price_in=0, price_out=1.5)
    assert cfg["api_key"] is None and cfg["extra_body"] == {"a": {"b": 1}} and cfg["price_in"] == 0
    assert create(client, name="T", thinking="max")["thinking"] == "max"


# --- default and delete rules ----------------------------------------------------------------

def test_set_default_switches(client):
    a, b = create(client), create(client, name="B")
    res = client.post(f"/api/llm/configs/{b['id']}/default")
    assert res.status_code == 200 and res.json()["is_default"] is True
    flags = {c["id"]: c["is_default"] for c in client.get("/api/llm/configs").json()}
    assert flags == {a["id"]: False, b["id"]: True}


def test_delete_rules(client):
    a, b, c = create(client), create(client, name="B"), create(client, name="C")
    # the default cannot go while others exist
    res = client.delete(f"/api/llm/configs/{a['id']}")
    assert res.status_code == 409 and res.json()["code"] == "llm_config_in_use"
    # a config assigned to a purpose cannot go
    assert client.put("/api/llm/purposes", json={"profile": None, "fit": b["id"], "extraction": None}).status_code == 200
    res = client.delete(f"/api/llm/configs/{b['id']}")
    assert res.status_code == 409 and res.json()["code"] == "llm_config_in_use"
    # an unassigned non-default one can
    assert client.delete(f"/api/llm/configs/{c['id']}").status_code == 204
    assert {x["id"] for x in client.get("/api/llm/configs").json()} == {a["id"], b["id"]}


def test_delete_only_config_resets_purposes(client):
    a = create(client)
    client.put("/api/llm/purposes", json={"profile": a["id"], "fit": a["id"], "extraction": None})
    assert client.delete(f"/api/llm/configs/{a['id']}").status_code == 204
    assert client.get("/api/llm/purposes").json() == {"profile": None, "fit": None, "extraction": None}
    assert client.get("/api/llm/configs").json() == []
    # the next config becomes default again
    assert create(client, name="N")["is_default"] is True


# --- purposes and resolve --------------------------------------------------------------------

def test_purposes_get_put_and_unknown_config(client):
    assert client.get("/api/llm/purposes").json() == {"profile": None, "fit": None, "extraction": None}
    a = create(client)
    res = client.put("/api/llm/purposes", json={"profile": a["id"], "fit": None, "extraction": a["id"]})
    assert res.status_code == 200 and res.json() == {"profile": a["id"], "fit": None, "extraction": a["id"]}
    assert client.get("/api/llm/purposes").json() == res.json()
    bad = client.put("/api/llm/purposes", json={"profile": 99, "fit": None, "extraction": None})
    assert bad.status_code == 404 and bad.json()["code"] == "llm_config_not_found"
    assert client.get("/api/llm/purposes").json() == res.json()  # unchanged
    assert client.put("/api/llm/purposes", json={"profile": None}).status_code == 422


def test_resolve_purpose_then_default_then_not_configured(app, client):
    from app.errors import ConflictError
    from app.services import llm_configs

    with app.state.session_factory() as s:
        with pytest.raises(ConflictError) as exc:
            llm_configs.resolve(s, "fit")
        assert exc.value.code == "llm_not_configured"
    a, b = create(client), create(client, name="B", model="m-b", api_key="sk-b-0000")
    with app.state.session_factory() as s:
        assert llm_configs.resolve(s, "fit").id == a["id"]  # NULL purpose = default
    client.put("/api/llm/purposes", json={"profile": None, "fit": b["id"], "extraction": None})
    with app.state.session_factory() as s:
        cfg = llm_configs.resolve(s, "fit")
        assert (cfg.id, cfg.model, cfg.api_key, cfg.provider) == (b["id"], "m-b", "sk-b-0000", "anthropic")
        assert llm_configs.resolve(s, "profile").id == a["id"]
        assert "sk-b-0000" not in repr(cfg)


# --- test / models endpoints -----------------------------------------------------------------

def test_test_endpoint_ok(client, fake):
    cfg = create(client)
    res = client.post(f"/api/llm/configs/{cfg['id']}/test")
    assert res.status_code == 200
    out = res.json()
    assert out["ok"] is True and out["model"] == "claude-x" and out["latency_ms"] >= 0
    assert fake.made[-1].api_key == KEY


@pytest.mark.parametrize("code,status", [
    ("llm_auth_failed", 502), ("llm_bad_request", 502), ("llm_unavailable", 502), ("llm_timeout", 502),
    ("llm_invalid_output", 502), ("llm_rate_limited", 429),
])
def test_test_endpoint_maps_errors_without_leaking_key(client, fake, code, status):
    cfg = create(client, api_key=LEAK)
    fake.error = LLMError(code, f"rejected key {LEAK}")
    res = client.post(f"/api/llm/configs/{cfg['id']}/test")
    assert res.status_code == status and res.json()["code"] == code
    assert LEAK not in res.text
    assert "rejected key" in res.json()["params"]["reason"]


def test_test_endpoint_client_creation_error_is_mapped(client, monkeypatch):
    def boom(cfg, **_):
        raise LLMError("llm_auth_failed", "API key is missing")

    monkeypatch.setattr("app.llm.runner.make_client", boom)
    cfg = create(client, provider="openai_compatible", base_url="http://x/v1", api_key=None)
    res = client.post(f"/api/llm/configs/{cfg['id']}/test")
    assert res.status_code == 502 and res.json()["code"] == "llm_auth_failed"


def test_models_by_config_id_and_by_body(client, fake):
    cfg = create(client)
    res = client.post("/api/llm/models", json={"config_id": cfg["id"]})
    assert res.status_code == 200 and res.json() == ["m1", "m2"]
    assert fake.made[-1].api_key == KEY
    res = client.post("/api/llm/models", json={"provider": "openai", "api_key": "sk-body-1111"})
    assert res.json() == ["m1", "m2"]
    assert (fake.made[-1].provider, fake.made[-1].api_key) == ("openai", "sk-body-1111")
    # body fields override the stored config (unsaved edits in the form)
    client.post("/api/llm/models", json={"config_id": cfg["id"], "api_key": "sk-over-2222"})
    assert fake.made[-1].api_key == "sk-over-2222"
    assert client.post("/api/llm/models", json={}).status_code == 422
    assert client.post("/api/llm/models", json={"config_id": 99}).status_code == 404


def test_models_error_mapped(client, fake):
    cfg = create(client, api_key=LEAK)
    fake.error = LLMError("llm_rate_limited", f"slow down {LEAK}")
    res = client.post("/api/llm/models", json={"config_id": cfg["id"]})
    assert res.status_code == 429 and res.json()["code"] == "llm_rate_limited" and LEAK not in res.text


# --- settings --------------------------------------------------------------------------------

def test_settings_defaults_update_and_bounds(client):
    assert client.get("/api/settings").json() == {
        "fit_auto": False, "fit_concurrency": 2, "daily_limit_kind": "none", "daily_limit_value": None,
        "fit_language": "en",
        "update_check": True}
    new = {"fit_auto": True, "fit_concurrency": 8, "daily_limit_kind": "tokens", "daily_limit_value": 50000,
           "fit_language": "en", "update_check": True}
    res = client.put("/api/settings", json=new)
    assert res.status_code == 200 and res.json() == new
    assert client.get("/api/settings").json() == new
    # kind none drops the value
    res = client.put("/api/settings", json={**new, "daily_limit_kind": "none"})
    assert res.json()["daily_limit_value"] is None
    for bad in ({"fit_concurrency": 0}, {"fit_concurrency": 9}, {"daily_limit_kind": "weekly"},
                {"daily_limit_value": -1}, {"daily_limit_kind": "eur", "daily_limit_value": None},
                {"daily_limit_kind": "eur", "daily_limit_value": 0}):
        assert client.put("/api/settings", json={**new, **bad}).status_code == 422, bad
    assert client.get("/api/settings").json()["daily_limit_kind"] == "none"  # nothing half-saved


def test_settings_fit_language_default_and_update(client):
    assert client.get("/api/settings").json()["fit_language"] == "en"
    base = {"fit_auto": False, "fit_concurrency": 2, "daily_limit_kind": "none"}
    res = client.put("/api/settings", json={**base, "fit_language": "de"})  # explicit
    assert res.status_code == 200 and res.json()["fit_language"] == "de"
    assert client.get("/api/settings").json()["fit_language"] == "de"
    res = client.put("/api/settings", json=base)  # older payload without the field: default
    assert res.status_code == 200 and res.json()["fit_language"] == "en"
    res = client.put("/api/settings", json={**base, "fit_language": "fr"})
    assert res.status_code == 422
    assert any("fit_language" in e["loc"] for e in res.json()["params"]["errors"])


# --- 422 bodies never echo the request (fix round 1) -----------------------------------------

def _loc_fields(res):
    return [e["loc"][-1] for e in res.json()["params"]["errors"]]


@pytest.mark.parametrize("override,field", [
    ({"provider": "openai_compatible"}, "base_url"),
    ({"provider": "openai_compatible", "base_url": "http://x/v1", "thinking": "high"}, "thinking"),
    ({"base_url": "http://x/v1"}, "base_url"),
    ({"api_key": None}, "api_key"),
])
def test_422_names_field_and_does_not_leak_key(client, override, field):
    payload = body(api_key=LEAK, **override) if override.get("api_key", 1) is not None else body(**override)
    res = client.post("/api/llm/configs", json=payload)
    assert res.status_code == 422 and field in _loc_fields(res)
    assert LEAK not in res.text and '"input"' not in res.text
    cfg = create(client, name="Z")
    if field != "api_key":  # key is optional on PUT
        res = client.put(f"/api/llm/configs/{cfg['id']}", json=payload)
        assert res.status_code == 422 and field in _loc_fields(res)
        assert LEAK not in res.text and '"input"' not in res.text


def test_models_missing_source_422_names_field_without_leak(client):
    res = client.post("/api/llm/models", json={"api_key": LEAK})
    assert res.status_code == 422 and "provider" in _loc_fields(res)
    assert LEAK not in res.text and '"input"' not in res.text


def test_models_reuses_stored_key_only_for_unchanged_endpoint(client, fake):
    cfg = create(client, provider="openai_compatible", base_url="http://a/v1", api_key=KEY,
                 extra_headers={"Authorization": "Bearer secret"})
    client.post("/api/llm/models", json={"config_id": cfg["id"]})
    assert fake.made[-1].api_key == KEY and fake.made[-1].extra_headers == {"Authorization": "Bearer secret"}
    client.post("/api/llm/models", json={"config_id": cfg["id"], "base_url": "http://a/v1"})
    assert fake.made[-1].api_key == KEY  # same endpoint
    client.post("/api/llm/models", json={"config_id": cfg["id"], "base_url": "http://evil/v1"})
    assert fake.made[-1].api_key is None and fake.made[-1].extra_headers == {}
    assert fake.made[-1].base_url == "http://evil/v1"
    client.post("/api/llm/models", json={"config_id": cfg["id"], "base_url": "http://evil/v1", "api_key": "sk-new-0001"})
    assert fake.made[-1].api_key == "sk-new-0001"
    client.post("/api/llm/models", json={"config_id": cfg["id"], "provider": "openai"})
    assert fake.made[-1].api_key is None and fake.made[-1].provider == "openai"


def test_models_never_sends_a_compat_base_url_to_a_hosted_provider(client, fake):
    cfg = create(client, provider="openai_compatible", base_url="http://a/v1", api_key=KEY)
    client.post("/api/llm/models", json={"config_id": cfg["id"], "provider": "anthropic", "api_key": "sk-typed-0002"})
    assert fake.made[-1].provider == "anthropic" and fake.made[-1].api_key == "sk-typed-0002"
    assert fake.made[-1].base_url is None
    client.post("/api/llm/models", json={"provider": "openai", "base_url": "http://evil/v1", "api_key": "sk-typed-0003"})
    assert fake.made[-1].base_url is None


def test_test_and_models_release_the_request_session_before_the_call(client, app, monkeypatch):
    cfg = create(client)
    seen = []

    class Probe:
        def __init__(self, c):
            pass

        def complete(self, *a, **k):
            seen.append(app.state.engine.pool.checkedout())
            return LLMResult("OK", 1, 1, False)

        def list_models(self):
            seen.append(app.state.engine.pool.checkedout())
            return []

    monkeypatch.setattr("app.llm.runner.make_client", lambda c, **_: Probe(c))
    client.post(f"/api/llm/configs/{cfg['id']}/test")
    client.post("/api/llm/models", json={"config_id": cfg["id"]})
    assert seen == [0, 0]


def test_unexpected_client_error_is_logged_redacted_and_recorded(client, app, fake, caplog):
    cfg = create(client, api_key=LEAK)
    fake.error = RuntimeError(f"boom with {LEAK}")
    res = client.post(f"/api/llm/configs/{cfg['id']}/test")
    assert res.status_code == 502 and res.json()["code"] == "llm_unavailable" and LEAK not in res.text
    assert LEAK not in caplog.text and "RuntimeError" in caplog.text
    from app.models import LLMUsage
    with app.state.session_factory() as s:
        row = s.query(LLMUsage).one()
        assert row.ok is False and row.purpose == "test"


def test_empty_reason_stays_empty_param_and_detail_is_not_dangling(client, fake):
    cfg = create(client)
    fake.error = LLMError("llm_unavailable", "")
    res = client.post(f"/api/llm/configs/{cfg['id']}/test")
    assert res.json()["params"] == {"reason": ""}  # the frontend supplies the localized fallback
    assert res.json()["detail"].strip() and not res.json()["detail"].endswith(":")


@pytest.mark.parametrize("field", ["price_in", "price_out"])
@pytest.mark.parametrize("literal", ["Infinity", "NaN"])
def test_config_prices_reject_inf_and_nan(client, field, literal):
    raw = ('{"name": "c", "provider": "anthropic", "model": "m", "api_key": "sk-test-1234", "%s": %s}' % (field, literal))
    res = client.post("/api/llm/configs", content=raw, headers={"Content-Type": "application/json"})
    assert res.status_code == 422
    assert [err["loc"][-1] for err in res.json()["params"]["errors"]] == [field]


@pytest.mark.parametrize("literal", ["Infinity", "NaN"])
def test_daily_limit_value_rejects_inf_and_nan(client, literal):
    raw = '{"fit_auto": false, "fit_concurrency": 2, "daily_limit_kind": "tokens", "daily_limit_value": %s}' % literal
    res = client.put("/api/settings", content=raw, headers={"Content-Type": "application/json"})
    assert res.status_code == 422
    assert [err["loc"][-1] for err in res.json()["params"]["errors"]] == ["daily_limit_value"]


def test_tokens_limit_is_an_integer(client):
    base = {"fit_auto": False, "fit_concurrency": 2, "daily_limit_kind": "tokens"}
    out = client.put("/api/settings", json={**base, "daily_limit_value": 50000.0})
    assert out.status_code == 200 and out.text.count("50000.0") == 0 and out.json()["daily_limit_value"] == 50000
    assert client.put("/api/settings", json={**base, "daily_limit_value": 10.5}).status_code == 422
    out = client.put("/api/settings", json={**base, "daily_limit_kind": "eur", "daily_limit_value": 2.5})
    assert out.json()["daily_limit_value"] == 2.5
    res = client.put("/api/settings", json={**base, "daily_limit_value": None})
    assert res.status_code == 422 and "daily_limit_value" in _loc_fields(res)

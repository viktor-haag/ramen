def by_name(client) -> dict:
    res = client.get("/api/plugins")
    assert res.status_code == 200
    return {p["name"]: p for p in res.json()}


def test_list_plugins_includes_broken_with_error(client):
    plugins = by_name(client)
    good = plugins["good"]
    assert good["display_name"] == "Good" and good["error"] is None and good["enabled"] is True
    assert good["capabilities"] == ["fetch", "search"]
    assert good["settings"] == {"max": 3, "timeout_seconds": 120}
    assert good["settings_schema"]["properties"]["max"]["type"] == "integer"
    broken = plugins["broken"]
    assert "kaputt" in broken["error"]
    assert broken["settings_schema"] is None and broken["settings"] == {} and broken["enabled"] is True


def test_update_settings_validated(client):
    bad = client.put("/api/plugins/good", json={"enabled": True, "settings": {"max": "x"}})
    assert bad.status_code == 422
    body = bad.json()
    assert body["code"] == "validation_error"
    assert body["params"]["errors"][0]["loc"] == ["body", "settings", "max"]
    assert by_name(client)["good"]["settings"]["max"] == 3  # nothing stored

    for timeout in (0, "5", True):
        res = client.put("/api/plugins/good", json={"enabled": True, "settings": {"timeout_seconds": timeout}})
        assert res.status_code == 422 and res.json()["code"] == "validation_error"

    ok = client.put("/api/plugins/good", json={"enabled": True, "settings": {"max": 5, "timeout_seconds": 30}})
    assert ok.status_code == 200
    assert ok.json()["settings"] == {"max": 5, "timeout_seconds": 30}
    assert by_name(client)["good"]["settings"] == {"max": 5, "timeout_seconds": 30}


def test_disable_plugin(client):
    res = client.put("/api/plugins/good", json={"enabled": False, "settings": {}})
    assert res.status_code == 200 and res.json()["enabled"] is False
    assert by_name(client)["good"]["enabled"] is False
    assert by_name(client)["good"]["settings"] == {"max": 3, "timeout_seconds": 120}


def test_update_unknown_and_broken(client):
    res = client.put("/api/plugins/nope", json={"enabled": True, "settings": {}})
    assert res.status_code == 404 and res.json()["code"] == "plugin_not_found"
    res = client.put("/api/plugins/broken", json={"enabled": False, "settings": {}})
    assert res.status_code == 409 and res.json()["code"] == "plugin_not_loadable"


def test_timeout_override_in_schema(client):
    prop = by_name(client)["good"]["settings_schema"]["properties"]["timeout_seconds"]
    assert prop["type"] == "integer" and prop["minimum"] == 1 and prop["default"] == 120


def test_settings_reach_runner(client, app):
    client.put("/api/plugins/good", json={"enabled": True, "settings": {"max": 2}})
    pid = client.post("/api/profiles", json={"name": "P", "keywords": ["py"], "plugins": ["good"]}).json()["id"]
    client.post(f"/api/profiles/{pid}/run")
    assert app.state.run_service.wait_idle(30)
    assert client.get("/api/runs").json()[0]["total_count"] == 3  # max=2 + shared-1


def test_default_off_plugin_listed_disabled_with_notice(client):
    plugins = by_name(client)
    assert plugins["optin"]["enabled"] is False
    assert plugins["optin"]["notice"] == {"de": "Achtung", "en": "Careful"}
    assert plugins["good"]["enabled"] is True and plugins["good"]["notice"] is None
    assert plugins["broken"]["enabled"] is True and plugins["broken"]["notice"] is None


def test_enable_default_off_plugin(client):
    res = client.put("/api/plugins/optin", json={"enabled": True, "settings": {}})
    assert res.status_code == 200 and res.json()["enabled"] is True
    assert by_name(client)["optin"]["enabled"] is True
    res = client.put("/api/plugins/optin", json={"enabled": False, "settings": {}})
    assert by_name(client)["optin"]["enabled"] is False

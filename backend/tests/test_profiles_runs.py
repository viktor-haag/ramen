from app.models import PluginSetting, RunStatus, RunTrigger, SearchRun


def make_profile(client, **kw) -> dict:
    body = {"name": "P", "keywords": ["py"], "plugins": ["good"], **kw}
    res = client.post("/api/profiles", json=body)
    assert res.status_code == 200, res.text
    return res.json()


def test_profile_crud(client):
    created = make_profile(client, location="Berlin", radius_km=30, schedule_hours=6)
    assert created["id"] and created["enabled"] is True and created["last_run_at"] is None
    pid = created["id"]

    assert client.get(f"/api/profiles/{pid}").json() == created
    assert [p["id"] for p in client.get("/api/profiles").json()] == [pid]

    updated = client.put(f"/api/profiles/{pid}", json={"name": "Q", "keywords": ["go"], "enabled": False, "plugins": []})
    assert updated.status_code == 200
    assert updated.json()["name"] == "Q" and updated.json()["enabled"] is False
    assert updated.json()["schedule_hours"] is None and updated.json()["keywords"] == ["go"]

    assert client.delete(f"/api/profiles/{pid}").status_code == 204
    for res in (client.get(f"/api/profiles/{pid}"), client.put(f"/api/profiles/{pid}", json={"name": "x", "keywords": ["k"]}),
                client.delete(f"/api/profiles/{pid}")):
        assert res.status_code == 404 and res.json()["code"] == "profile_not_found"
    assert client.get("/api/profiles").json() == []


def test_profile_validation(client):
    assert client.post("/api/profiles", json={"name": "x", "keywords": ["k"], "schedule_hours": 0}).status_code == 422
    assert client.post("/api/profiles", json={"name": "", "keywords": ["k"]}).status_code == 422


def test_profile_unknown_plugin_422(client):
    res = client.post("/api/profiles", json={"name": "x", "keywords": ["k"], "plugins": ["good", "nope", "broken"]})
    assert res.status_code == 422
    body = res.json()
    assert body["code"] == "unknown_plugin"
    assert set(body["params"]["names"]) == {"nope", "broken"}  # broken exists but is unusable
    pid = make_profile(client)["id"]
    res = client.put(f"/api/profiles/{pid}", json={"name": "x", "keywords": ["k"], "plugins": ["nope"]})
    assert res.status_code == 422 and res.json()["params"] == {"names": ["nope"]}


def test_run_profile_creates_runs(client, app):
    profile = make_profile(client, name="Berlin")
    res = client.post(f"/api/profiles/{profile['id']}/run")
    assert res.status_code == 200
    assert len(res.json()["run_ids"]) == 1 and res.json()["already_running"] is False
    assert app.state.run_service.wait_idle(30)

    runs = client.get("/api/runs").json()
    assert [r["id"] for r in runs] == res.json()["run_ids"]
    run = runs[0]
    assert run["status"] == "ok" and run["plugin"] == "good" and run["trigger"] == "manual"
    assert run["profile_id"] == profile["id"] and run["profile_name"] == "Berlin"
    assert run["total_count"] == 4 and run["finished_at"] is not None
    assert client.get(f"/api/runs?profile_id={profile['id']}&status=ok").json() == runs
    assert client.get("/api/runs?status=error").json() == []
    assert client.get("/api/runs/active").json() == []
    assert client.get(f"/api/profiles/{profile['id']}").json()["last_run_at"] == run["started_at"]
    assert client.get("/api/profiles").json()[0]["last_run_at"] == run["started_at"]

    client.delete(f"/api/profiles/{profile['id']}")
    assert client.get("/api/runs").json()[0]["profile_name"] is None


def test_run_unknown_profile_404(client):
    res = client.post("/api/profiles/999/run")
    assert res.status_code == 404 and res.json()["code"] == "profile_not_found"


def test_run_disabled_profile_manually(client, app):
    profile = make_profile(client, enabled=False)
    res = client.post(f"/api/profiles/{profile['id']}/run")
    assert len(res.json()["run_ids"]) == 1
    assert app.state.run_service.wait_idle(30)


def test_run_all_skips_disabled_profiles(client, app):
    on = make_profile(client, name="on")
    off = make_profile(client, name="off", enabled=False)
    res = client.post("/api/runs")
    assert res.status_code == 200 and len(res.json()["run_ids"]) == 1
    assert app.state.run_service.wait_idle(30)
    runs = client.get("/api/runs").json()
    assert [r["profile_id"] for r in runs] == [on["id"]]
    assert client.get(f"/api/runs?profile_id={off['id']}").json() == []


def test_already_running_flag(client, app):
    profile = make_profile(client)
    with app.state.session_factory() as s:
        s.add(SearchRun(profile_id=profile["id"], plugin="good", trigger=RunTrigger.manual))
        s.commit()
    expected = {"run_ids": [], "already_running": True}
    assert client.post(f"/api/profiles/{profile['id']}/run").json() == expected
    assert client.post("/api/runs").json() == expected
    assert [r["status"] for r in client.get("/api/runs/active").json()] == ["running"]


def test_profile_without_effective_plugins_not_already_running(client, app):
    profile = make_profile(client, enabled=True)
    with app.state.session_factory() as s:
        s.add(PluginSetting(plugin="good", enabled=False))
        s.add(SearchRun(profile_id=profile["id"], plugin="good", trigger=RunTrigger.manual))
        s.commit()
    assert client.post(f"/api/profiles/{profile['id']}/run").json() == {"run_ids": [], "already_running": False}


def test_runs_limit_and_order(client, app):
    profile = make_profile(client)
    with app.state.session_factory() as s:
        for _ in range(3):
            s.add(SearchRun(profile_id=profile["id"], plugin="good", trigger=RunTrigger.manual,
                            status=RunStatus.ok))
        s.commit()
    ids = [r["id"] for r in client.get("/api/runs").json()]
    assert ids == sorted(ids, reverse=True)
    assert len(client.get("/api/runs?limit=2").json()) == 2
    assert client.get("/api/runs?limit=0").status_code == 422


def test_profile_changes_sync_scheduler(client, app):
    pid = make_profile(client, schedule_hours=4)["id"]
    assert app.state.scheduler.jobs() == {f"profile-{pid}": 4}
    client.put(f"/api/profiles/{pid}", json={"name": "P", "keywords": ["py"], "schedule_hours": 2})
    assert app.state.scheduler.jobs() == {f"profile-{pid}": 2}
    client.delete(f"/api/profiles/{pid}")
    assert app.state.scheduler.jobs() == {}

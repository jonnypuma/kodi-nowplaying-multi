def test_auto_switch_preference_roundtrip(app_module):
    sanitized, error = app_module.validate_preferences_update({
        "autoSwitchPlayingPreference": "enabled",
    })
    assert error is None
    assert sanitized["autoSwitchPlayingPreference"] == "enabled"


def test_add_and_delete_custom_server(client, app_module):
    created = client.post("/api/servers", json={
        "host": "http://10.0.0.50:8080",
        "label": "Shed",
        "username": "kodi",
        "password": "secret",
    })
    assert created.status_code == 200
    body = created.get_json()
    assert body["success"] is True
    server_id = body["server"]["id"]
    assert server_id >= 100
    assert body["server"]["editable"] is True
    assert "password" not in body["server"]

    listed = client.get("/api/servers").get_json()["servers"]
    assert any(row["id"] == server_id for row in listed)

    deleted = client.delete(f"/api/servers/{server_id}")
    assert deleted.status_code == 200
    remaining = client.get("/api/servers").get_json()["servers"]
    assert all(row["id"] != server_id for row in remaining)


def test_cannot_delete_env_server(client, app_module):
    env_id = sorted(app_module.KODI_SERVERS)[0]
    response = client.delete(f"/api/servers/{env_id}")
    assert response.status_code == 400


def test_events_route_registered(app_module):
    rules = {rule.rule for rule in app_module.app.url_map.iter_rules()}
    assert "/api/events" in rules

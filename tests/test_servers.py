import os


def test_parse_numbered_servers(app_module, monkeypatch):
    monkeypatch.setenv("KODI_HOST_1", "http://10.0.0.1:8080")
    monkeypatch.setenv("KODI_HOST_LABEL_1", "Living Room")
    monkeypatch.setenv("KODI_USERNAME_1", "u1")
    monkeypatch.setenv("KODI_PASSWORD_1", "p1")
    monkeypatch.setenv("KODI_HOST_2", "http://10.0.0.2:8080")
    monkeypatch.delenv("KODI_HOST_LABEL_2", raising=False)
    monkeypatch.delenv("KODI_HOST_3", raising=False)
    monkeypatch.delenv("KODI_HOST", raising=False)

    servers = app_module.parse_kodi_servers()
    assert set(servers.keys()) == {1, 2}
    assert servers[1]["host"] == "http://10.0.0.1:8080"
    assert servers[1]["auth"] == ("u1", "p1")
    assert servers[1]["label"] == "Living Room"
    assert servers[2]["ip"] == "10.0.0.2"
    assert servers[2]["label"] == ""
    assert app_module.server_display_name(servers[1]) == "Living Room (10.0.0.1)"
    assert app_module.server_display_name(servers[2]) == "10.0.0.2"


def test_parse_legacy_single_server(app_module, monkeypatch):
    for key in list(os.environ):
        if key.startswith("KODI_HOST") or key.startswith("KODI_USERNAME_") or key.startswith("KODI_PASSWORD_"):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("KODI_HOST", "http://10.0.0.9:6666")
    monkeypatch.setenv("KODI_HOST_LABEL", "Office")
    monkeypatch.setenv("KODI_USER", "legacy")
    monkeypatch.setenv("KODI_PASS", "pw")

    servers = app_module.parse_kodi_servers()
    assert list(servers.keys()) == [1]
    assert servers[1]["host"] == "http://10.0.0.9:6666"
    assert servers[1]["auth"] == ("legacy", "pw")
    assert servers[1]["label"] == "Office"


def test_api_servers_lists_configured(client, app_module):
    app_module.KODI_SERVERS = {
        1: {"id": 1, "host": "http://10.0.0.1:8080", "ip": "10.0.0.1", "label": "Living Room", "auth": None, "username": "", "password": ""},
        2: {"id": 2, "host": "http://10.0.0.2:8080", "ip": "10.0.0.2", "label": "", "auth": None, "username": "", "password": ""},
    }
    response = client.get("/api/servers")
    assert response.status_code == 200
    data = response.get_json()
    assert len(data["servers"]) == 2
    assert data["servers"][0]["ip"] == "10.0.0.1"
    assert data["servers"][0]["label"] == "Living Room"
    assert data["servers"][0]["name"] == "Living Room (10.0.0.1)"
    assert data["servers"][1]["name"] == "10.0.0.2"

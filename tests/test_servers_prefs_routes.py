"""Server CRUD and preference mutation routes (3.1.9)."""
import pytest


@pytest.fixture
def prefs_on_disk(app_module, tmp_path):
    from kodi_np import preferences as prefs_mod

    app_module.PREFERENCES_DIR = tmp_path
    app_module.PREFERENCES_FILE = tmp_path / "preferences.json"
    prefs_mod.invalidate_preferences_cache()
    return tmp_path


@pytest.fixture
def one_env_server(app_module):
    app_module.KODI_SERVERS = {
        1: {
            "id": 1, "host": "http://10.0.0.1:8080", "ip": "10.0.0.1",
            "label": "Living Room", "auth": None, "username": "", "password": "",
            "source": "env",
        },
    }
    return app_module.KODI_SERVERS


def test_list_servers_sorted_by_ip(client, app_module):
    app_module.KODI_SERVERS = {
        1: {"id": 1, "host": "http://10.0.0.20:8080", "ip": "10.0.0.20", "label": "b",
            "auth": None, "username": "", "password": "", "source": "env"},
        2: {"id": 2, "host": "http://10.0.0.3:8080", "ip": "10.0.0.3", "label": "a",
            "auth": None, "username": "", "password": "", "source": "env"},
    }
    servers = client.get("/api/servers").get_json()["servers"]
    assert [s["ip"] for s in servers] == ["10.0.0.3", "10.0.0.20"]


def test_create_server_rejects_bad_host(client, prefs_on_disk):
    response = client.post("/api/servers", json={"host": "ftp://nope"})
    assert response.status_code == 400
    assert response.get_json()["success"] is False


def test_create_edit_and_delete_custom_server(client, prefs_on_disk, one_env_server):
    created = client.post("/api/servers", json={
        "host": "http://10.0.0.55:8080/",
        "username": "kodi",
        "password": "hunter2",
        "label": "Attic",
    })
    assert created.status_code == 200
    server = created.get_json()["server"]
    server_id = server["id"]
    assert server["host"] == "http://10.0.0.55:8080"
    assert server["label"] == "Attic"

    edited = client.put(f"/api/servers/{server_id}", json={"label": "Loft"})
    assert edited.status_code == 200
    assert edited.get_json()["server"]["label"] == "Loft"

    removed = client.delete(f"/api/servers/{server_id}")
    assert removed.status_code == 200
    assert removed.get_json()["success"] is True

    remaining = client.get("/api/servers").get_json()["servers"]
    assert server_id not in [s["id"] for s in remaining]


def test_public_server_payload_hides_password(client, prefs_on_disk):
    created = client.post("/api/servers", json={
        "host": "http://10.0.0.56:8080", "username": "kodi", "password": "hunter2",
    })
    body = created.get_data(as_text=True)
    assert "hunter2" not in body

    listed = client.get("/api/servers").get_data(as_text=True)
    assert "hunter2" not in listed


def test_cannot_delete_an_env_server(client, prefs_on_disk, one_env_server):
    response = client.delete("/api/servers/1")
    assert response.status_code == 400
    assert response.get_json()["success"] is False


def test_edit_unknown_server_is_rejected(client, prefs_on_disk):
    response = client.patch("/api/servers/9999", json={"label": "ghost"})
    assert response.status_code == 400


def test_switch_server_persists_and_reports(client, prefs_on_disk, one_env_server):
    assert client.post("/api/switch-server/999").status_code == 404

    response = client.post("/api/switch-server/1")
    assert response.status_code == 200
    assert response.get_json()["server_id"] == 1
    assert client.get("/api/current-server").get_json()["server_id"] == 1


def test_preferences_round_trip(client, prefs_on_disk):
    assert client.get("/api/preferences").get_json() == {}

    saved = client.post("/api/preferences", json={"fanartMinSizeKB": 300})
    assert saved.status_code == 200
    assert saved.get_json()["success"] is True
    assert client.get("/api/preferences").get_json()["fanartMinSizeKB"] == "300"


def test_preferences_rejects_unknown_key(client, prefs_on_disk):
    response = client.post("/api/preferences", json={"totallyMadeUp": "1"})
    assert response.status_code == 400
    assert "Unsupported preference key" in response.get_json()["error"]


def test_preferences_rejects_out_of_range_value(client, prefs_on_disk, app_module):
    key, (minimum, maximum) = next(iter(app_module.PREFERENCE_RANGES.items()))
    response = client.post("/api/preferences", json={key: maximum + 1})
    assert response.status_code == 400
    assert key in response.get_json()["error"]


def test_preferences_rejects_empty_body(client, prefs_on_disk):
    response = client.post("/api/preferences", json={})
    assert response.status_code == 400


def test_preferences_directory_writability_probe(client, prefs_on_disk):
    payload = client.get("/api/preferences/test").get_json()
    assert payload["success"] is True
    assert payload["writable"] is True


def test_test_connection_unknown_server(client, app_module):
    app_module.KODI_SERVERS = {}
    response = client.get("/api/test-connection/42")
    assert response.status_code == 404
    assert response.get_json()["connected"] is False


def test_test_connection_reports_connection_failure(client, one_env_server, monkeypatch):
    import requests

    from kodi_np.routes import servers_prefs as module

    def refuse(*args, **kwargs):
        raise requests.exceptions.ConnectionError("no route")

    monkeypatch.setattr(module.requests, "post", refuse)
    payload = client.get("/api/test-connection/1").get_json()
    assert payload["connected"] is False
    assert payload["error"] == "Connection failed"

from pathlib import Path


def test_health_endpoint(client, app_module):
    app_module.KODI_SERVERS = {
        1: {"id": 1, "host": "http://10.0.0.1:8080", "ip": "10.0.0.1", "auth": None, "username": "", "password": ""},
    }
    response = client.get("/health")
    assert response.status_code == 200
    data = response.get_json()
    assert data["status"] == "ok"
    assert data["servers_configured"] == 1


def test_resolve_safe_child_rejects_traversal(app_module, tmp_path):
    base = tmp_path
    (base / "ok.jpg").write_text("x", encoding="utf-8")
    assert app_module.resolve_safe_child(base, "ok.jpg") == (base / "ok.jpg").resolve()
    assert app_module.resolve_safe_child(base, "../secret.txt") is None
    assert app_module.resolve_safe_child(base, "sub/ok.jpg") is None
    assert app_module.resolve_safe_child(base, "") is None


def test_media_route_rejects_bad_filename(client):
    response = client.get("/media/../../../etc/passwd")
    assert response.status_code in (400, 404)

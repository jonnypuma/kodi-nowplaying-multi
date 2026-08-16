"""SSRF, redirect, and host-allowlist hardening (3.1.4).

Anything that reads live config must go through ``app_module``: the session
fixture reloads ``kodi_np.*``, so a module-level import here would bind a stale
config object.
"""
import pytest

from kodi_np.auth import safe_next_url

KODI = {"host": "http://10.0.0.1:8080"}


def test_same_host_vfs_url_is_allowed(app_module):
    assert app_module.is_kodi_host_url("http://10.0.0.1:8080/vfs/token/art.jpg", KODI) is True


@pytest.mark.parametrize("url", [
    "http://169.254.169.254/latest/meta-data/",
    "http://evil.example/x.jpg",
    "https://10.0.0.1:8080/vfs/x.jpg",
    "http://10.0.0.2:8080/vfs/x.jpg",
    "http://10.0.0.1:9999/vfs/x.jpg",
    "file:///etc/passwd",
    "",
])
def test_foreign_hosts_are_rejected(app_module, url):
    assert app_module.is_kodi_host_url(url, KODI) is False


def test_missing_server_rejects(app_module):
    assert app_module.is_kodi_host_url("http://10.0.0.1:8080/x.jpg", {}) is False
    assert app_module.is_kodi_host_url("http://10.0.0.1:8080/x.jpg", None) is False


def test_deferred_fanart_refuses_foreign_url(app_module, tmp_path):
    """POST /api/fanart must not fetch an arbitrary URL."""
    app_module.ART_TMP_DIR = str(tmp_path)
    app_module.ART_TMP_PATH = tmp_path
    app_module.KODI_SERVERS = {
        1: {"id": 1, "host": "http://10.0.0.1:8080", "ip": "10.0.0.1", "label": "", "auth": None},
    }
    result = app_module.download_fanart_variant(
        "http://169.254.169.254/latest/meta-data/",
        "fanart2",
        "a" * 32,
        server_id=1,
    )
    assert result is None


def test_api_fanart_route_rejects_foreign_url(client, app_module, tmp_path):
    app_module.ART_TMP_DIR = str(tmp_path)
    app_module.ART_TMP_PATH = tmp_path
    app_module.KODI_SERVERS = {
        1: {"id": 1, "host": "http://10.0.0.1:8080", "ip": "10.0.0.1", "label": "", "auth": None},
    }
    with client.session_transaction() as sess:
        sess["active_server_id"] = 1
    response = client.post(
        "/api/fanart",
        json={
            "path": "http://169.254.169.254/latest/meta-data/",
            "key": "fanart2",
            "session_id": "a" * 32,
        },
    )
    assert response.status_code == 404
    assert response.get_json()["success"] is False


@pytest.mark.parametrize("hostile", [
    "//evil.example",
    "//evil.example/path",
    "/\\evil.example",
    "https://evil.example",
    "http://evil.example",
    "javascript:alert(1)",
    "",
])
def test_safe_next_url_blocks_offsite(hostile):
    assert safe_next_url(hostile) == "/"


@pytest.mark.parametrize("benign", ["/", "/overview", "/nowplaying?json=1"])
def test_safe_next_url_keeps_relative_paths(benign):
    assert safe_next_url(benign) == benign


def test_host_allowlist_blocks_unlisted_host(app_module):
    app_module.KODI_HOST_ALLOWLIST = ("10.0.0.1", "kodi.lan")
    try:
        host, error = app_module.validate_server_host("http://10.0.0.99:8080")
        assert host is None
        assert "KODI_HOST_ALLOWLIST" in error

        host, error = app_module.validate_server_host("http://kodi.lan:8080")
        assert error is None
        assert host == "http://kodi.lan:8080"
    finally:
        app_module.KODI_HOST_ALLOWLIST = ()


def test_empty_allowlist_permits_any_host(app_module):
    app_module.KODI_HOST_ALLOWLIST = ()
    host, error = app_module.validate_server_host("http://192.168.5.5:8080")
    assert error is None
    assert host == "http://192.168.5.5:8080"


def test_add_custom_server_respects_allowlist(client, app_module):
    app_module.KODI_HOST_ALLOWLIST = ("10.0.0.1",)
    try:
        response = client.post("/api/servers", json={"host": "http://evil.example:8080"})
        assert response.status_code == 400
        assert response.get_json()["success"] is False
    finally:
        app_module.KODI_HOST_ALLOWLIST = ()

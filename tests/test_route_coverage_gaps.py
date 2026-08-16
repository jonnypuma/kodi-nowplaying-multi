"""Diagnostics, cast thumbnails, load-job status, and secret key (3.1.9)."""
import time

import pytest


# --- /api/diagnostics -------------------------------------------------------

def test_diagnostics_reports_version_and_servers(client, app_module):
    app_module.KODI_SERVERS = {
        2: {"id": 2, "host": "http://10.0.0.2:8080", "ip": "10.0.0.2", "label": "Den",
            "auth": None, "username": "", "password": "", "source": "env"},
        1: {"id": 1, "host": "http://10.0.0.1:8080", "ip": "10.0.0.1", "label": "TV",
            "auth": None, "username": "", "password": "", "source": "env"},
    }
    payload = client.get("/api/diagnostics").get_json()

    assert payload["version"] == app_module.APP_VERSION
    assert [server["id"] for server in payload["servers"]] == [1, 2]
    assert payload["servers"][0]["label"] == "TV"
    assert "cache" in payload


def test_diagnostics_never_exposes_credentials(client, app_module):
    app_module.KODI_SERVERS = {
        1: {"id": 1, "host": "http://10.0.0.1:8080", "ip": "10.0.0.1", "label": "TV",
            "auth": ("kodi", "hunter2"), "username": "kodi", "password": "hunter2",
            "source": "custom"},
    }
    body = client.get("/api/diagnostics").get_data(as_text=True)
    assert "hunter2" not in body


def test_diagnostics_with_no_servers(client, app_module):
    app_module.KODI_SERVERS = {}
    payload = client.get("/api/diagnostics").get_json()
    assert payload["servers"] == []


# --- /api/cast-thumb --------------------------------------------------------

@pytest.fixture
def one_server(app_module, tmp_path):
    app_module.ART_TMP_DIR = str(tmp_path)
    app_module.ART_TMP_PATH = tmp_path
    app_module.KODI_SERVERS = {
        1: {"id": 1, "host": "http://10.0.0.1:8080", "ip": "10.0.0.1", "label": "",
            "auth": None, "username": "", "password": "", "source": "env"},
    }
    return tmp_path


@pytest.mark.parametrize("body", [{}, {"path": ""}, {"path": "   "}, {"path": 42}])
def test_cast_thumb_requires_a_path(client, one_server, body):
    response = client.post("/api/cast-thumb", json=body)
    assert response.status_code == 400
    assert response.get_json()["success"] is False


def test_cast_thumb_rejects_overlong_path(client, one_server):
    response = client.post("/api/cast-thumb", json={"path": "image://" + "x" * 2100})
    assert response.status_code == 400
    assert "too long" in response.get_json()["error"].lower()


def test_cast_thumb_skips_kodi_placeholder_art(client, one_server):
    response = client.post(
        "/api/cast-thumb",
        json={"path": "image://DefaultActor.png/"},
    )
    assert response.status_code == 404
    assert response.get_json()["success"] is False


def test_cast_thumb_returns_existing_file_without_refetching(client, one_server, monkeypatch):
    from kodi_np.routes import extras as extras_mod

    monkeypatch.setattr(
        extras_mod, "download_cast_thumbnail",
        lambda path, server_id=None: "cast_deadbeef_actor.jpg",
    )
    response = client.post("/api/cast-thumb", json={"path": "image://nfs://x/actor.jpg/"})
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["success"] is True
    assert payload["url"] == "/media/cast_deadbeef_actor.jpg"


def test_cast_thumb_404s_when_download_fails(client, one_server, monkeypatch):
    from kodi_np.routes import extras as extras_mod

    monkeypatch.setattr(
        extras_mod, "download_cast_thumbnail", lambda path, server_id=None: None
    )
    response = client.post("/api/cast-thumb", json={"path": "image://nfs://x/actor.jpg/"})
    assert response.status_code == 404
    assert response.get_json()["url"] is None


# --- load job lifecycle -----------------------------------------------------

def test_load_status_404s_for_unknown_job(client):
    response = client.get("/nowplaying-load-status/does-not-exist")
    assert response.status_code == 404
    assert response.get_json()["status"] == "missing"


def test_load_status_reports_progress(client, app_module):
    job_id = "job-under-test"
    now = time.time()
    with app_module.load_lock:
        app_module.load_jobs[job_id] = {
            "status": "running", "progress": 42, "message": "Fetching artwork",
            "created_at": now, "updated_at": now, "html": None,
        }
    try:
        payload = client.get(f"/nowplaying-load-status/{job_id}").get_json()
        assert payload["status"] == "running"
        assert payload["progress"] == 42
        assert payload["message"] == "Fetching artwork"
    finally:
        with app_module.load_lock:
            app_module.load_jobs.pop(job_id, None)


def test_content_is_served_once_then_marked_consumed(client, app_module):
    job_id = "job-content"
    now = time.time()
    with app_module.load_lock:
        app_module.load_jobs[job_id] = {
            "status": "done", "progress": 100, "message": "",
            "created_at": now, "updated_at": now, "html": "<h1>Now Playing</h1>",
        }
    try:
        first = client.get(f"/nowplaying-content/{job_id}")
        assert first.status_code == 200
        assert "Now Playing" in first.get_data(as_text=True)

        second = client.get(f"/nowplaying-content/{job_id}")
        assert second.status_code == 410
    finally:
        with app_module.load_lock:
            app_module.load_jobs.pop(job_id, None)


def test_content_still_loading_returns_202(client, app_module):
    job_id = "job-pending"
    now = time.time()
    with app_module.load_lock:
        app_module.load_jobs[job_id] = {
            "status": "running", "progress": 10, "message": "",
            "created_at": now, "updated_at": now, "html": None,
        }
    try:
        assert client.get(f"/nowplaying-content/{job_id}").status_code == 202
    finally:
        with app_module.load_lock:
            app_module.load_jobs.pop(job_id, None)


def test_content_fallback_and_unknown_job(client):
    assert client.get("/nowplaying-content/fallback").status_code == 503
    assert client.get("/nowplaying-content/no-such-job").status_code == 404


# --- Flask secret key -------------------------------------------------------

def test_secret_key_prefers_the_environment(app_module, tmp_path, monkeypatch):
    from kodi_np import config as config_mod

    monkeypatch.setenv("FLASK_SECRET_KEY", "from-the-environment")
    monkeypatch.setattr(config_mod, "PREFERENCES_DIR", tmp_path)
    assert config_mod._resolve_secret_key() == "from-the-environment"
    assert not (tmp_path / "flask_secret_key").exists()


def test_secret_key_is_generated_then_reused(app_module, tmp_path, monkeypatch):
    """Sessions must survive a container restart, so the key is persisted."""
    from kodi_np import config as config_mod

    monkeypatch.delenv("FLASK_SECRET_KEY", raising=False)
    monkeypatch.setattr(config_mod, "PREFERENCES_DIR", tmp_path)

    first = config_mod._resolve_secret_key()
    assert len(first) == 64
    assert (tmp_path / "flask_secret_key").read_text(encoding="utf-8") == first

    assert config_mod._resolve_secret_key() == first


def test_secret_key_falls_back_when_directory_is_unwritable(app_module, tmp_path, monkeypatch):
    from pathlib import Path

    from kodi_np import config as config_mod

    monkeypatch.delenv("FLASK_SECRET_KEY", raising=False)
    monkeypatch.setattr(config_mod, "PREFERENCES_DIR", tmp_path)

    def deny(*args, **kwargs):
        raise OSError("read-only file system")

    monkeypatch.setattr(Path, "write_text", deny)
    key = config_mod._resolve_secret_key()
    assert len(key) == 32

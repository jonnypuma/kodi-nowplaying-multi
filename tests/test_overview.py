def test_format_overview_title_episode(app_module):
    title, media_type = app_module._format_overview_title({
        "type": "episode",
        "showtitle": "The Show",
        "season": 1,
        "episode": 2,
        "title": "Pilot",
    })
    assert media_type == "episode"
    assert "The Show" in title
    assert "S01E02" in title
    assert "Pilot" in title


def test_format_overview_title_song(app_module):
    title, media_type = app_module._format_overview_title({
        "type": "song",
        "title": "Track",
        "artist": ["Artist A", "Artist B"],
    })
    assert media_type == "song"
    assert title == "Artist A, Artist B · Track"


def test_format_overview_title_movie(app_module):
    title, media_type = app_module._format_overview_title({
        "type": "movie",
        "title": "Inception",
    })
    assert media_type == "movie"
    assert title == "Inception"


def test_probe_playback_fingerprint_uses_overview_title(app_module, patch_into):
    """Regression: cache probe must import _format_overview_title (post-refactor)."""
    app_module.server_backoff.clear()

    def fake_rpc(method, params=None, server_id=None):
        if method == "Player.GetActivePlayers":
            return {"result": [{"playerid": 1}]}
        if method == "Player.GetItem":
            return {
                "result": {
                    "item": {
                        "type": "episode",
                        "id": 9,
                        "title": "Pilot",
                        "showtitle": "Demo",
                        "season": 1,
                        "episode": 1,
                        "file": "/tv/demo/s01e01.mkv",
                    }
                }
            }
        if method == "Player.GetProperties":
            return {"result": {"speed": 1}}
        return {"result": {}}

    patch_into(app_module, "kodi_rpc", fake_rpc)
    probe = app_module.probe_playback_fingerprint(1)
    assert probe["connected"] is True
    assert probe["playing"] is True
    assert probe["media_type"] == "episode"
    assert "Demo" in probe["title"]
    assert "S01E01" in probe["title"]


def test_overview_page_renders(client):
    response = client.get("/overview")
    assert response.status_code == 200
    assert b"Kodi Overview" in response.data
    assert b"tile-retry" in response.data
    assert b"/api/retry-server/" in response.data


def test_api_overview_with_mocked_status(client, app_module, patch_into):
    app_module.nowplaying_cache.clear()
    app_module.server_backoff.clear()
    app_module.KODI_SERVERS = {
        1: {"id": 1, "host": "http://10.0.0.1:8080", "ip": "10.0.0.1", "auth": None, "username": "", "password": ""},
    }

    def fake_status(server_id):
        return {
            "id": server_id,
            "host": "http://10.0.0.1:8080",
            "ip": "10.0.0.1",
            "label": "Living Room",
            "name": "Living Room",
            "connected": True,
            "playing": True,
            "paused": False,
            "title": "Demo Movie",
            "media_type": "movie",
            "error": None,
        }

    patch_into(app_module, "get_server_overview_status", fake_status)
    # Force live probe path (no warm cache)
    patch_into(app_module, "overview_from_cache", lambda _sid: None)
    response = client.get("/api/overview")
    assert response.status_code == 200
    data = response.get_json()
    assert data["servers"][0]["title"] == "Demo Movie"
    assert data["servers"][0]["playing"] is True
    assert "backoff_remaining" in data["servers"][0]


def test_api_retry_server_clears_backoff(client, app_module, patch_into):
    app_module.nowplaying_cache.clear()
    app_module.server_backoff.clear()
    app_module.KODI_SERVERS = {
        1: {"id": 1, "host": "http://10.0.0.1:8080", "ip": "10.0.0.1", "label": "A", "auth": None, "username": "", "password": ""},
    }
    app_module.SERVER_FAIL_BACKOFF_AFTER = 1
    app_module.note_server_rpc_failure(1, "No route to host")
    assert app_module.server_backoff_remaining(1) > 0

    refreshed = {"n": 0}

    def fake_refresh(server_id):
        refreshed["n"] += 1
        app_module.clear_cache_playback(server_id, {"connected": True, "error": None})

    patch_into(app_module, "refresh_server_cache", fake_refresh)
    response = client.post("/api/retry-server/1")
    assert response.status_code == 200
    data = response.get_json()
    assert data["success"] is True
    assert refreshed["n"] == 1
    assert app_module.server_backoff_remaining(1) == 0
    assert data["server"]["id"] == 1


def test_api_retry_server_not_found(client, app_module):
    app_module.KODI_SERVERS = {
        1: {"id": 1, "host": "http://10.0.0.1:8080", "ip": "10.0.0.1", "auth": None},
    }
    response = client.post("/api/retry-server/99")
    assert response.status_code == 404

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

    def fake_rpc(method, params=None, server_id=None, **kwargs):
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
    assert b"Kodi Now Playing Overview" in response.data
    assert b"Checking servers" in response.data
    assert b"tile-retry" in response.data
    assert b"/api/retry-server/" in response.data


def test_api_overview_fast_snapshot(client, app_module, patch_into):
    """Overview list returns instantly without blocking on live Kodi RPC."""
    app_module.nowplaying_cache.clear()
    app_module.server_backoff.clear()
    app_module.KODI_SERVERS = {
        1: {"id": 1, "host": "http://10.0.0.1:8080", "ip": "10.0.0.1", "auth": None, "username": "", "password": ""},
    }
    live_calls = {"n": 0}

    def fake_live(server_id):
        live_calls["n"] += 1
        return {
            "id": server_id,
            "host": "http://10.0.0.1:8080",
            "connected": True,
            "playing": True,
            "loading": False,
            "title": "Demo Movie",
        }

    patch_into(app_module, "overview_live_status", fake_live)
    patch_into(app_module, "overview_from_cache", lambda _sid: None)

    response = client.get("/api/overview")
    assert response.status_code == 200
    data = response.get_json()
    assert live_calls["n"] == 0
    assert data["servers"][0]["loading"] is True
    assert data["servers"][0]["host"] == "http://10.0.0.1:8080"


def test_api_overview_server_live(client, app_module, patch_into):
    app_module.nowplaying_cache.clear()
    app_module.server_backoff.clear()
    app_module.KODI_SERVERS = {
        1: {"id": 1, "host": "http://10.0.0.1:8080", "ip": "10.0.0.1", "auth": None, "username": "", "password": ""},
    }

    def fake_live(server_id):
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
            "loading": False,
            "backoff_remaining": 0,
        }

    patch_into(app_module, "overview_live_status", fake_live)
    patch_into(app_module, "overview_from_cache", lambda _sid: None)
    response = client.get("/api/overview-server/1")
    assert response.status_code == 200
    data = response.get_json()
    assert data["success"] is True
    assert data["server"]["title"] == "Demo Movie"
    assert data["server"]["playing"] is True
    assert data["server"]["loading"] is False


def test_api_overview_with_mocked_status(client, app_module, patch_into):
    """Legacy /api/overview/all still returns live merged status."""
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
            "loading": False,
            "backoff_remaining": 0,
        }

    patch_into(app_module, "overview_live_status", fake_status)
    patch_into(app_module, "overview_from_cache", lambda _sid: None)
    response = client.get("/api/overview/all")
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
    assert data["server"]["loading"] is False
    assert data["server"]["connected"] is True


def test_overview_live_status_clears_stale_playing_cache(app_module, patch_into):
    """When Kodi is connected but idle, drop cached playing/title/thumb."""
    app_module.server_backoff.clear()
    patch_into(
        app_module,
        "get_server_overview_status",
        lambda server_id: {
            "id": server_id,
            "connected": True,
            "playing": False,
            "paused": False,
            "title": None,
            "media_type": None,
            "error": None,
            "auth_failed": False,
        },
    )
    patch_into(app_module, "server_backoff_remaining", lambda _sid: 0)
    patch_into(
        app_module,
        "overview_from_cache",
        lambda _sid: {
            "id": 1,
            "connected": True,
            "playing": True,
            "paused": False,
            "title": "Silo · S03E06",
            "media_type": "episode",
            "thumb": "/media/foo.jpg",
            "cache_ready": True,
        },
    )
    out = app_module.overview_live_status(1)
    assert out["playing"] is False
    assert out["cache_ready"] is False
    assert out["thumb"] is None
    assert "Nothing playing" in (out.get("title") or "")


def test_overview_live_status_skips_rpc_during_backoff(app_module, patch_into):
    app_module.server_backoff.clear()
    app_module.SERVER_FAIL_BACKOFF_AFTER = 1
    app_module.note_server_rpc_failure(1, "Connection refused")
    rpc_calls = {"n": 0}

    def boom(server_id):
        rpc_calls["n"] += 1
        raise AssertionError("live overview must not RPC during backoff")

    patch_into(app_module, "get_server_overview_status", boom)
    patch_into(
        app_module,
        "overview_from_cache",
        lambda _sid: {
            "id": 1,
            "connected": True,
            "playing": True,
            "paused": False,
            "title": "Stale",
            "error": "Connection failed",
            "backoff_remaining": 300,
        },
    )
    out = app_module.overview_live_status(1)
    assert rpc_calls["n"] == 0
    assert out["connected"] is False
    assert out["playing"] is False
    assert out["loading"] is False
    assert out["backoff_remaining"] > 0


def test_overview_page_refresh_uses_cache_snapshot():
    html = (
        __import__("pathlib").Path(__file__).resolve().parents[1]
        / "kodi-np-multi"
        / "templates"
        / "overview.html"
    ).read_text(encoding="utf-8")
    assert "async function refreshTiles()" in html
    refresh_fn = html.split("async function refreshTiles()", 1)[1].split("async function", 1)[0]
    assert "/api/overview'" in refresh_fn or '/api/overview"' in refresh_fn
    assert "/api/overview-server/" not in refresh_fn
    assert "backoff_remaining" in html


def test_api_retry_server_not_found(client, app_module):
    app_module.KODI_SERVERS = {
        1: {"id": 1, "host": "http://10.0.0.1:8080", "ip": "10.0.0.1", "auth": None},
    }
    response = client.post("/api/retry-server/99")
    assert response.status_code == 404

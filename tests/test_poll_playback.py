def test_poll_playback_rpc_failure_does_not_report_idle(client, app_module, patch_into):
    app_module.playback_poll_state.clear()
    app_module.server_backoff.clear()
    app_module.KODI_SERVERS = {
        1: {"id": 1, "host": "http://10.0.0.1:8080", "ip": "10.0.0.1", "label": "", "auth": None},
    }
    with client.session_transaction() as sess:
        sess["active_server_id"] = 1

    # Seed known playing item, then fail RPC
    state = app_module._poll_state_for(1)
    state["item_id"] = "movie_42"

    patch_into(app_module, "kodi_rpc", lambda *a, **k: None)
    response = client.get("/poll_playback")
    data = response.get_json()
    assert data.get("error") is True
    assert data.get("playing") is not False
    assert data.get("item_id") == "movie_42"


def test_poll_playback_error_streak_holds_page(client, app_module, patch_into):
    app_module.playback_poll_state.clear()
    app_module.server_backoff.clear()
    app_module.POLL_ERROR_IDLE_CONFIRMATIONS = 3
    app_module.KODI_SERVERS = {
        1: {"id": 1, "host": "http://10.0.0.1:8080", "ip": "10.0.0.1", "label": "", "auth": None},
    }
    with client.session_transaction() as sess:
        sess["active_server_id"] = 1

    state = app_module._poll_state_for(1)
    state["item_id"] = "movie_99"
    patch_into(app_module, "kodi_rpc", lambda *a, **k: None)

    assert client.get("/poll_playback").get_json()["playing"] is not False
    assert client.get("/poll_playback").get_json()["playing"] is not False
    data = client.get("/poll_playback").get_json()
    assert data["playing"] is True
    assert data.get("error") is True
    assert data.get("error_idle") is True
    assert data.get("item_id") == "movie_99"


def test_poll_playback_bypasses_unreachable_backoff(client, app_module, patch_into):
    app_module.playback_poll_state.clear()
    app_module.server_backoff.clear()
    app_module.KODI_SERVERS = {
        1: {"id": 1, "host": "http://10.0.0.1:8080", "ip": "10.0.0.1", "label": "", "auth": None},
    }
    with client.session_transaction() as sess:
        sess["active_server_id"] = 1

    state = app_module._poll_state_for(1)
    state["item_id"] = "episode_1"
    # Simulate background poller having put the server in backoff
    app_module.SERVER_FAIL_BACKOFF_AFTER = 1
    app_module.note_server_rpc_failure(1, "No route to host")
    assert app_module.server_backoff_remaining(1) > 0

    calls = {"n": 0}

    def fake_rpc(method, params=None, server_id=None, bypass_backoff=False):
        calls["n"] += 1
        assert bypass_backoff is True
        return {"result": []}

    patch_into(app_module, "kodi_rpc", fake_rpc)
    app_module.POLL_IDLE_CONFIRMATIONS = 1
    data = client.get("/poll_playback").get_json()
    assert calls["n"] >= 1
    assert data["playing"] is False


def test_poll_playback_requires_idle_confirmations(client, app_module, patch_into):
    app_module.playback_poll_state.clear()
    app_module.server_backoff.clear()
    app_module.POLL_IDLE_CONFIRMATIONS = 2
    app_module.KODI_SERVERS = {
        1: {"id": 1, "host": "http://10.0.0.1:8080", "ip": "10.0.0.1", "label": "", "auth": None},
    }
    with client.session_transaction() as sess:
        sess["active_server_id"] = 1

    state = app_module._poll_state_for(1)
    state["item_id"] = "movie_7"

    patch_into(app_module, "kodi_rpc", lambda *a, **k: {"result": []})

    # First empty-player poll should hold playing=true
    data = client.get("/poll_playback").get_json()
    assert data["playing"] is True
    assert data["item_id"] == "movie_7"

    # Second confirmation reports idle
    data = client.get("/poll_playback").get_json()
    assert data["playing"] is False


def test_poll_state_is_per_server(app_module):
    app_module.playback_poll_state.clear()
    s1 = app_module._poll_state_for(1)
    s2 = app_module._poll_state_for(2)
    s1["item_id"] = "movie_1"
    s2["item_id"] = "movie_2"
    assert app_module._poll_state_for(1)["item_id"] == "movie_1"
    assert app_module._poll_state_for(2)["item_id"] == "movie_2"


def test_cache_probe_failure_keeps_warm_html(app_module, patch_into):
    app_module.nowplaying_cache.clear()
    app_module.server_backoff.clear()
    app_module.KODI_SERVERS = {
        1: {"id": 1, "host": "http://10.0.0.1:8080", "ip": "10.0.0.1", "label": "A", "auth": None},
    }
    app_module.store_playing_cache(1, {
        "html": "<html>warm</html>",
        "downloaded_art": {"poster": "dddddddddddddddddddddddddddddddd_poster.jpg"},
        "fingerprint": "movie:1",
        "title": "Warm",
        "media_type": "movie",
        "paused": False,
        "session_id": "dddddddddddddddddddddddddddddddd",
    })

    def boom(server_id, bypass_backoff=False):
        raise RuntimeError("timeout")

    patch_into(app_module, "probe_playback_fingerprint", boom)
    app_module.refresh_server_cache(1)
    entry = app_module.get_cache_entry(1)
    assert entry["html"] == "<html>warm</html>"
    assert entry.get("probe_fail_streak", 0) >= 1

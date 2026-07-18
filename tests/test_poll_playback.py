def test_poll_playback_rpc_failure_does_not_report_idle(client, app_module, monkeypatch):
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

    monkeypatch.setattr(app_module, "kodi_rpc", lambda *a, **k: None)
    response = client.get("/poll_playback")
    data = response.get_json()
    assert data.get("error") is True
    assert data.get("playing") is not False
    assert data.get("item_id") == "movie_42"


def test_poll_playback_requires_idle_confirmations(client, app_module, monkeypatch):
    app_module.playback_poll_state.clear()
    app_module.server_backoff.clear()
    app_module.POLL_IDLE_CONFIRMATIONS = 3
    app_module.KODI_SERVERS = {
        1: {"id": 1, "host": "http://10.0.0.1:8080", "ip": "10.0.0.1", "label": "", "auth": None},
    }
    with client.session_transaction() as sess:
        sess["active_server_id"] = 1

    state = app_module._poll_state_for(1)
    state["item_id"] = "movie_7"

    monkeypatch.setattr(app_module, "kodi_rpc", lambda *a, **k: {"result": []})

    # First empty-player polls should hold playing=true
    for _ in range(2):
        data = client.get("/poll_playback").get_json()
        assert data["playing"] is True
        assert data["item_id"] == "movie_7"

    # Third confirmation reports idle
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


def test_cache_probe_failure_keeps_warm_html(app_module, monkeypatch):
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

    def boom(server_id):
        raise RuntimeError("timeout")

    monkeypatch.setattr(app_module, "probe_playback_fingerprint", boom)
    app_module.refresh_server_cache(1)
    entry = app_module.get_cache_entry(1)
    assert entry["html"] == "<html>warm</html>"
    assert entry.get("probe_fail_streak", 0) >= 1

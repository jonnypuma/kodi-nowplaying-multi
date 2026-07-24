def test_read_timeout_does_not_enter_backoff(app_module):
    app_module.server_backoff.clear()
    app_module.SERVER_FAIL_BACKOFF_AFTER = 1
    assert app_module.note_server_rpc_failure(
        1, "HTTPConnectionPool(host='192.168.0.19', port=6666): Read timed out. (read timeout=5.0)"
    ) is False
    assert app_module.server_backoff_remaining(1) == 0


def test_server_backoff_after_three_failures(app_module):
    app_module.server_backoff.clear()
    app_module.SERVER_FAIL_BACKOFF_AFTER = 3
    app_module.SERVER_FAIL_BACKOFF_SECONDS = 300

    assert app_module.note_server_rpc_failure(1, "No route to host") is False
    assert app_module.note_server_rpc_failure(1, "No route to host") is False
    assert app_module.server_backoff_remaining(1) == 0

    entered = app_module.note_server_rpc_failure(1, "No route to host")
    assert entered is True
    assert app_module.server_backoff_remaining(1) > 290

    # Further failures while in backoff stay quiet / still backed off
    assert app_module.note_server_rpc_failure(1, "No route to host") is True
    assert app_module.server_backoff_remaining(1) > 0


def test_server_backoff_cleared_on_success(app_module):
    app_module.server_backoff.clear()
    app_module.SERVER_FAIL_BACKOFF_AFTER = 3
    for _ in range(3):
        app_module.note_server_rpc_failure(2, "Connection refused")
    assert app_module.server_backoff_remaining(2) > 0
    app_module.note_server_rpc_success(2)
    assert app_module.server_backoff_remaining(2) == 0


def test_kodi_rpc_skips_during_backoff(app_module, monkeypatch):
    app_module.server_backoff.clear()
    app_module.KODI_SERVERS = {
        9: {"id": 9, "host": "http://10.0.0.9:8080", "ip": "10.0.0.9", "auth": None},
    }
    app_module.SERVER_FAIL_BACKOFF_AFTER = 1
    app_module.note_server_rpc_failure(9, "No route to host")
    assert app_module.server_backoff_remaining(9) > 0

    called = {"n": 0}

    def fake_post(*args, **kwargs):
        called["n"] += 1
        raise AssertionError("should not call requests during backoff")

    monkeypatch.setattr(app_module.requests, "post", fake_post)
    result = app_module.kodi_rpc("Player.GetActivePlayers", server_id=9)
    assert result is None
    assert called["n"] == 0


def test_refresh_skips_backed_off_server(app_module, patch_into):
    app_module.server_backoff.clear()
    app_module.nowplaying_cache.clear()
    app_module.KODI_SERVERS = {
        1: {"id": 1, "host": "http://10.0.0.1:8080", "ip": "10.0.0.1", "auth": None},
    }
    app_module.SERVER_FAIL_BACKOFF_AFTER = 1
    app_module.note_server_rpc_failure(1, "No route to host")

    probed = {"n": 0}

    def boom(server_id):
        probed["n"] += 1
        raise AssertionError("should not probe during backoff")

    patch_into(app_module, "probe_playback_fingerprint", boom)
    app_module.refresh_server_cache(1)
    assert probed["n"] == 0

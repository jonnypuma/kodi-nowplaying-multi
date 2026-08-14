def test_read_timeout_does_not_enter_backoff(app_module):
    app_module.server_backoff.clear()
    app_module.SERVER_FAIL_BACKOFF_AFTER = 1
    assert app_module.note_server_rpc_failure(
        1, "HTTPConnectionPool(host='192.168.0.19', port=6666): Read timed out. (read timeout=5.0)"
    ) is False
    assert app_module.server_backoff_remaining(1) == 0


def test_hard_down_backs_off_immediately(app_module):
    app_module.server_backoff.clear()
    app_module.SERVER_FAIL_BACKOFF_AFTER = 3
    app_module.SERVER_FAIL_BACKOFF_SECONDS = 300
    refused = (
        "HTTPConnectionPool(host='192.168.0.21', port=6666): Max retries exceeded with url: /jsonrpc "
        "(Caused by NewConnectionError(\"HTTPConnection(host='192.168.0.21', port=6666): "
        "Failed to establish a new connection: [Errno 111] Connection refused\"))"
    )
    assert app_module.note_server_rpc_failure(5, refused) is True
    assert app_module.server_backoff_remaining(5) > 290


def test_server_backoff_after_three_soft_failures(app_module):
    app_module.server_backoff.clear()
    app_module.SERVER_FAIL_BACKOFF_AFTER = 3
    app_module.SERVER_FAIL_BACKOFF_SECONDS = 300

    assert app_module.note_server_rpc_failure(1, "Connection reset") is False
    assert app_module.note_server_rpc_failure(1, "Connection reset") is False
    assert app_module.server_backoff_remaining(1) == 0

    entered = app_module.note_server_rpc_failure(1, "Connection reset")
    assert entered is True
    assert app_module.server_backoff_remaining(1) > 290

    assert app_module.note_server_rpc_failure(1, "Connection reset") is True
    assert app_module.server_backoff_remaining(1) > 0


def test_server_backoff_cleared_on_success(app_module):
    app_module.server_backoff.clear()
    app_module.SERVER_FAIL_BACKOFF_AFTER = 3
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

    monkeypatch.setattr("kodi_np.rpc.requests.post", fake_post)
    result = app_module.kodi_rpc("Player.GetActivePlayers", server_id=9)
    assert result is None
    assert called["n"] == 0


def test_probe_does_not_bypass_backoff(app_module, patch_into):
    seen = []

    def fake_rpc(method, params=None, server_id=None, bypass_backoff=False):
        seen.append(bypass_backoff)
        return None

    patch_into(app_module, "kodi_rpc", fake_rpc)
    probe = app_module.probe_playback_fingerprint(1)
    assert probe["connected"] is False
    assert seen
    assert all(flag is False for flag in seen)


def test_probe_honors_backoff(app_module, monkeypatch):
    app_module.server_backoff.clear()
    app_module.KODI_SERVERS = {
        1: {"id": 1, "host": "http://10.0.0.1:8080", "ip": "10.0.0.1", "auth": None},
    }
    app_module.SERVER_FAIL_BACKOFF_AFTER = 1
    app_module.note_server_rpc_failure(1, "Connection refused")
    called = {"n": 0}

    def fake_post(*args, **kwargs):
        called["n"] += 1
        raise AssertionError("should not HTTP during backoff")

    monkeypatch.setattr("kodi_np.rpc.requests.post", fake_post)
    probe = app_module.probe_playback_fingerprint(1)
    assert probe["connected"] is False
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

    def boom(server_id, bypass_backoff=False):
        probed["n"] += 1
        raise AssertionError("should not probe during backoff")

    patch_into(app_module, "probe_playback_fingerprint", boom)
    app_module.refresh_server_cache(1)
    assert probed["n"] == 0

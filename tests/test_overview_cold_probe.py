"""A server we have never reached must not be reported as confidently offline.

If the Kodi box is still booting when the poller first tries, that single
failure starts a backoff. Without a cold probe the overview page then shows
every server offline until the backoff expires, even though they are reachable,
and the only way out is the Retry button.
"""
import pytest


@pytest.fixture
def cold_server(app_module):
    app_module.server_backoff.clear()
    app_module.nowplaying_cache.clear()
    app_module.SERVER_FAIL_BACKOFF_AFTER = 1
    app_module.SERVER_FAIL_BACKOFF_INITIAL_SECONDS = 15
    app_module.note_server_rpc_failure(1, "Connection refused")
    assert app_module.server_backoff_remaining(1) > 0
    return 1


def playing_rpc(calls):
    def fake_rpc(method, params=None, server_id=None, bypass_backoff=False):
        calls.append((method, bypass_backoff))
        if method == "Player.GetActivePlayers":
            return {"result": [{"playerid": 1}]}
        if method == "Player.GetItem":
            return {"result": {"item": {"type": "movie", "title": "Arrival"}}}
        if method == "Player.GetProperties":
            return {"result": {"speed": 1}}
        return None

    return fake_rpc


def test_cold_server_is_probed_despite_backoff(app_module, patch_into, cold_server):
    calls = []
    patch_into(app_module, "kodi_rpc", playing_rpc(calls))

    status = app_module.overview_live_status(cold_server, allow_cold_probe=True)

    assert status["connected"] is True
    assert status["playing"] is True
    assert calls and calls[0] == ("Player.GetActivePlayers", True)


def test_background_path_still_honours_backoff(app_module, patch_into, cold_server):
    calls = []
    patch_into(app_module, "kodi_rpc", playing_rpc(calls))

    status = app_module.overview_live_status(cold_server)

    assert status["connected"] is False
    assert calls == []


def test_warm_server_in_backoff_is_not_reprobed(app_module, patch_into, monkeypatch, cold_server):
    """A host we have talked to before keeps its backoff; the cache answers instead."""
    monkeypatch.setattr(
        "kodi_np.cache.overview_from_cache",
        lambda server_id: {"id": server_id, "connected": True, "playing": False, "cache_ready": True},
    )
    calls = []
    patch_into(app_module, "kodi_rpc", playing_rpc(calls))

    status = app_module.overview_live_status(cold_server, allow_cold_probe=True)

    assert status["connected"] is False
    assert calls == []


def test_auth_failure_is_not_treated_as_cold(app_module, patch_into):
    """Wrong credentials are a definite answer, so do not keep retrying them."""
    app_module.server_backoff.clear()
    app_module.nowplaying_cache.clear()
    app_module.note_server_rpc_failure(1, "401 Client Error: Unauthorized")
    calls = []
    patch_into(app_module, "kodi_rpc", playing_rpc(calls))

    status = app_module.overview_live_status(1, allow_cold_probe=True)

    assert status["connected"] is False
    assert status["auth_failed"] is True
    assert calls == []


def test_successful_cold_probe_clears_the_backoff(app_module, patch_into, cold_server):
    calls = []

    def fake_rpc(method, params=None, server_id=None, bypass_backoff=False):
        calls.append(method)
        app_module.note_server_rpc_success(server_id)
        if method == "Player.GetActivePlayers":
            return {"result": []}
        return None

    patch_into(app_module, "kodi_rpc", fake_rpc)

    status = app_module.overview_live_status(cold_server, allow_cold_probe=True)

    assert status["connected"] is True
    assert app_module.server_backoff_remaining(cold_server) == 0

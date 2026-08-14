"""Tests for lyrics helpers, cast strip, and overview auth_failed."""


def test_parse_lrc_and_plain(app_module):
    from kodi_np.lyrics import parse_lrc, plain_lyrics_lines, lyrics_from_kodi_field

    synced = parse_lrc("[00:12.50]First line\n[00:15.00]Second line\n")
    assert synced[0]["text"] == "First line"
    assert abs(synced[0]["time"] - 12.5) < 0.01
    assert synced[1]["text"] == "Second line"

    plain = plain_lyrics_lines("Line A\n\nLine B\n")
    assert plain == [{"time": None, "text": "Line A"}, {"time": None, "text": "Line B"}]

    from_kodi = lyrics_from_kodi_field("[00:01.00]Hello")
    assert from_kodi["synced"] is True
    assert from_kodi["source"] == "kodi"


def test_resolve_lyrics_uses_kodi_synced_without_network(monkeypatch):
    from kodi_np import lyrics as lyrics_mod

    def boom(*_a, **_k):
        raise AssertionError("should not call LRCLib when Kodi LRC exists")

    monkeypatch.setattr(lyrics_mod, "fetch_lrclib", boom)
    result = lyrics_mod.resolve_lyrics("Artist", "Title", 120, "[00:01.00]Hello")
    assert result["synced"] is True
    assert result["lines"][0]["text"] == "Hello"


def test_api_lyrics_empty_artist(client):
    response = client.get("/api/lyrics?title=OnlyTitle")
    assert response.status_code == 200
    data = response.get_json()
    assert data["has_lyrics"] is False
    assert data["lines"] == []


def test_lyrics_panel_preference_enum(app_module):
    sanitized, error = app_module.validate_preferences_update({"lyricsPanelPreference": "lyrics"})
    assert error is None
    assert sanitized["lyricsPanelPreference"] == "lyrics"
    _, bad = app_module.validate_preferences_update({"lyricsPanelPreference": "bio"})
    assert bad


def test_build_cast_html_includes_lazy_thumb_hook():
    from kodi_np.util import build_cast_html

    html = build_cast_html([
        {"name": "Ada", "role": "Lead", "thumbnail": "image://nfs://server/actors/Ada.jpg/"},
        {"name": "Bob", "role": "", "thumbnail": "image://DefaultActor.png/"},
    ])
    assert "cast-strip" in html
    assert "Ada" in html
    assert "data-thumb=" in html
    assert "DefaultActor" not in html


def test_build_cast_html_dedupes_same_actor_name():
    from kodi_np.util import build_cast_html

    html = build_cast_html([
        {"name": "Nicholas Galitzine", "role": "Adam / He-Man", "thumbnail": ""},
        {"name": "Nicholas Galitzine", "role": "Adam Glenn / He-Man", "thumbnail": "image://actor.jpg/"},
        {"name": "Camila Mendes", "role": "Teela", "thumbnail": ""},
        {"name": "Jóhannes Haukur Jóhannesson", "role": "Malcolm / Fisto", "thumbnail": ""},
        {"name": "Jóhannes Haukur Jóhannesson", "role": "Fisto", "thumbnail": ""},
    ], limit=8)
    assert html.count('class="cast-card"') == 3
    assert html.count('class="cast-name">Nicholas Galitzine<') == 1
    assert html.count('class="cast-name">Jóhannes Haukur Jóhannesson<') == 1
    assert "Adam Glenn / He-Man" in html  # richer role kept
    assert "Malcolm / Fisto" in html
    assert "image://actor.jpg/" in html


def test_overview_auth_failed_flag(app_module, monkeypatch):
    app_module.server_backoff.clear()
    app_module.KODI_SERVERS = {
        1: {
            "id": 1,
            "host": "http://10.0.0.1:8080",
            "ip": "10.0.0.1",
            "label": "A",
            "auth": None,
            "username": "",
            "password": "",
        },
    }

    def _rpc(*_args, **_kwargs):
        return None

    monkeypatch.setattr("kodi_np.overview.kodi_rpc", _rpc)
    monkeypatch.setattr(
        "kodi_np.overview.server_backoff_status",
        lambda _sid: {"remaining": 10, "auth_failed": True, "error": "Authentication failed"},
    )
    status = app_module.get_server_overview_status(1)
    assert status["auth_failed"] is True
    assert status["error"] == "Authentication failed"
    assert status["connected"] is False


def test_unreachable_clears_auth_failed_backoff(app_module):
    app_module.server_backoff.clear()
    app_module.server_backoff[1] = {
        "fail_count": 1,
        "backoff_until": 0,
        "last_error": "Authentication failed",
        "auth_failed": True,
    }
    app_module.note_server_rpc_failure(
        1,
        "HTTPConnectionPool(host='192.168.0.19', port=6666): Max retries exceeded "
        "(Caused by NewConnectionError('Connection refused'))",
    )
    status = app_module.server_backoff_status(1)
    assert status["auth_failed"] is False


def test_overview_page_mentions_auto_refresh(client):
    response = client.get("/overview")
    assert response.status_code == 200
    assert b"Auto-refresh every" in response.data
    assert b"Auto-switch to playing" in response.data
    assert b"auth-failed" in response.data

"""Tests for same-identity soft-update eligibility and payloads."""


def _progress(elapsed=10, duration=1200, speed=1):
    h, rem = divmod(elapsed, 3600)
    m, s = divmod(rem, 60)
    th, trem = divmod(duration, 3600)
    tm, ts = divmod(trem, 60)
    return {
        "result": {
            "time": {"hours": h, "minutes": m, "seconds": s},
            "totaltime": {"hours": th, "minutes": tm, "seconds": ts},
            "speed": speed,
        }
    }


def test_soft_update_idle(app_module, patch_into):
    patch_into(app_module, "kodi_rpc", lambda *a, **k: {"result": []})
    out = app_module.build_nowplaying_soft_update({"media_type": "episode", "tvshow_id": 1})
    assert out == {"soft": False, "reason": "idle"}


def test_soft_update_episode_same_show(app_module, patch_into):
    def fake_rpc(method, params=None):
        if method == "Player.GetActivePlayers":
            return {"result": [{"playerid": 1}]}
        if method == "Player.GetItem":
            return {
                "result": {
                    "item": {
                        "type": "episode",
                        "id": 200,
                        "title": "Next Ep",
                        "showtitle": "Demo",
                        "tvshowid": 9,
                        "season": 1,
                        "episode": 2,
                        "plot": "Plot 2",
                    }
                }
            }
        if method == "Player.GetProperties":
            return _progress(30, 2400)
        if method == "VideoLibrary.GetEpisodeDetails":
            return {"result": {"episodedetails": {"plot": "Plot 2", "title": "Next Ep"}}}
        return {"result": {}}

    patch_into(app_module, "kodi_rpc", fake_rpc)
    patch_into(app_module, "get_active_server", lambda: {"id": 1})
    patch_into(app_module, "get_cache_entry", lambda _sid: {"share": app_module.empty_share()})

    out = app_module.build_nowplaying_soft_update({
        "media_type": "episode",
        "tvshow_id": 9,
        "season": 1,
        "item_id": "episode_100",
    })
    assert out["soft"] is True
    assert out["scope"] == "episode"
    assert out["tvshow_id"] == 9
    assert out["season_changed"] is False
    assert out["badges"]["title"] == "Next Ep"
    assert out["plot"] == "Plot 2"
    assert out["item_id"] == "episode_200"
    assert out["identity"]["tvshow_id"] == 9
    assert out["elapsed"] == 30
    assert out["duration"] == 2400


def test_soft_update_episode_different_show(app_module, patch_into):
    def fake_rpc(method, params=None):
        if method == "Player.GetActivePlayers":
            return {"result": [{"playerid": 1}]}
        if method == "Player.GetItem":
            return {
                "result": {
                    "item": {
                        "type": "episode",
                        "id": 50,
                        "title": "Other",
                        "tvshowid": 2,
                        "season": 1,
                        "episode": 1,
                    }
                }
            }
        if method == "Player.GetProperties":
            return _progress()
        return {"result": {}}

    patch_into(app_module, "kodi_rpc", fake_rpc)
    patch_into(app_module, "get_active_server", lambda: {"id": 1})
    patch_into(app_module, "get_cache_entry", lambda _sid: {"share": app_module.empty_share()})

    out = app_module.build_nowplaying_soft_update({
        "media_type": "episode",
        "tvshow_id": 9,
        "season": 1,
    })
    assert out == {"soft": False, "reason": "different_show"}


def test_soft_update_episode_type_mismatch(app_module, patch_into):
    def fake_rpc(method, params=None):
        if method == "Player.GetActivePlayers":
            return {"result": [{"playerid": 1}]}
        if method == "Player.GetItem":
            return {
                "result": {
                    "item": {
                        "type": "episode",
                        "id": 50,
                        "tvshowid": 9,
                        "season": 1,
                        "episode": 1,
                    }
                }
            }
        if method == "Player.GetProperties":
            return _progress()
        return {"result": {}}

    patch_into(app_module, "kodi_rpc", fake_rpc)
    patch_into(app_module, "get_active_server", lambda: {"id": 1})
    patch_into(app_module, "get_cache_entry", lambda _sid: {"share": app_module.empty_share()})

    out = app_module.build_nowplaying_soft_update({"media_type": "song", "album_id": 1})
    assert out == {"soft": False, "reason": "type_mismatch"}


def test_soft_update_song_same_album(app_module, patch_into):
    def fake_rpc(method, params=None):
        if method == "Player.GetActivePlayers":
            return {"result": [{"playerid": 1}]}
        if method == "Player.GetItem":
            return {
                "result": {
                    "item": {
                        "type": "song",
                        "id": 77,
                        "title": "Track Two",
                        "album": "Same Album",
                        "artist": ["Band"],
                    }
                }
            }
        if method == "Player.GetProperties":
            return _progress(5, 200)
        if method == "AudioLibrary.GetSongDetails":
            return {
                "result": {
                    "songdetails": {
                        "title": "Track Two",
                        "album": "Same Album",
                        "artist": ["Band"],
                        "albumid": 10,
                        "artistid": [3],
                        "track": 2,
                        "disc": 1,
                    }
                }
            }
        return {"result": {}}

    patch_into(app_module, "kodi_rpc", fake_rpc)
    patch_into(app_module, "get_active_server", lambda: {"id": 1})
    share = app_module.empty_share()
    share["album_details"] = {
        "title": "Same Album",
        "year": 1999,
        "description": "Desc",
        "totaldiscs": 1,
    }
    share["artist_details"] = {"description": "Bio"}
    patch_into(app_module, "get_cache_entry", lambda _sid: {"share": share})

    out = app_module.build_nowplaying_soft_update({
        "media_type": "song",
        "album_id": 10,
        "artist_id": 3,
        "item_id": "song_76",
    })
    assert out["soft"] is True
    assert out["scope"] == "song"
    assert out["album_changed"] is False
    assert out["artist_changed"] is False
    assert out["badges"]["track"] == "Track 02"
    assert out["badges"]["disc"] == ""  # single-disc album: hide even when track has disc=1
    assert out["badges"]["title"] == "Track Two"
    assert out["identity"]["album_id"] == 10
    assert "lyrics" in out
    assert out["lyrics"]["title"] == "Track Two"
    assert out["lyrics"]["artist"] == "Band"
    assert out["lyrics"]["album"] == "Same Album"


def test_soft_update_song_multi_disc_shows_badge(app_module, patch_into):
    def fake_rpc(method, params=None):
        if method == "Player.GetActivePlayers":
            return {"result": [{"playerid": 1}]}
        if method == "Player.GetItem":
            return {
                "result": {
                    "item": {
                        "type": "song",
                        "id": 88,
                        "title": "Side B",
                        "album": "Double LP",
                        "artist": ["Band"],
                    }
                }
            }
        if method == "Player.GetProperties":
            return _progress(5, 200)
        if method == "AudioLibrary.GetSongDetails":
            return {
                "result": {
                    "songdetails": {
                        "title": "Side B",
                        "album": "Double LP",
                        "artist": ["Band"],
                        "albumid": 20,
                        "artistid": [4],
                        "track": 1,
                        "disc": 2,
                    }
                }
            }
        return {"result": {}}

    patch_into(app_module, "kodi_rpc", fake_rpc)
    patch_into(app_module, "get_active_server", lambda: {"id": 1})
    share = app_module.empty_share()
    share["album_details"] = {"title": "Double LP", "totaldiscs": 2}
    patch_into(app_module, "get_cache_entry", lambda _sid: {"share": share})

    out = app_module.build_nowplaying_soft_update({
        "media_type": "song",
        "album_id": 20,
        "artist_id": 4,
        "item_id": "song_87",
    })
    assert out["soft"] is True
    assert out["badges"]["disc"] == "Disc 2"
    assert out["badges"]["track"] == "Track 01"


def test_soft_update_song_different_album_and_artist(app_module, patch_into):
    def fake_rpc(method, params=None):
        if method == "Player.GetActivePlayers":
            return {"result": [{"playerid": 1}]}
        if method == "Player.GetItem":
            return {"result": {"item": {"type": "song", "id": 99, "title": "X"}}}
        if method == "Player.GetProperties":
            return _progress()
        if method == "AudioLibrary.GetSongDetails":
            return {
                "result": {
                    "songdetails": {
                        "title": "X",
                        "albumid": 50,
                        "artistid": [8],
                        "track": 1,
                    }
                }
            }
        return {"result": {}}

    patch_into(app_module, "kodi_rpc", fake_rpc)
    patch_into(app_module, "get_active_server", lambda: {"id": 1})
    patch_into(app_module, "get_cache_entry", lambda _sid: {"share": app_module.empty_share()})

    out = app_module.build_nowplaying_soft_update({
        "media_type": "song",
        "album_id": 10,
        "artist_id": 3,
    })
    assert out == {"soft": False, "reason": "different_album_and_artist"}


def test_soft_update_movie_unsupported(app_module, patch_into):
    def fake_rpc(method, params=None):
        if method == "Player.GetActivePlayers":
            return {"result": [{"playerid": 1}]}
        if method == "Player.GetItem":
            return {"result": {"item": {"type": "movie", "id": 1, "title": "Film"}}}
        if method == "Player.GetProperties":
            return _progress()
        return {"result": {}}

    patch_into(app_module, "kodi_rpc", fake_rpc)
    patch_into(app_module, "get_active_server", lambda: {"id": 1})
    patch_into(app_module, "get_cache_entry", lambda _sid: {"share": app_module.empty_share()})

    out = app_module.build_nowplaying_soft_update({"media_type": "movie"})
    assert out["soft"] is False
    assert out["reason"] == "unsupported_type"


def test_api_soft_update_route(client, app_module, patch_into):
    app_module.server_backoff.clear()
    patch_into(
        app_module,
        "build_nowplaying_soft_update",
        lambda prev: {"soft": True, "scope": "episode", "item_id": "episode_1", "prev": prev},
    )
    res = client.get(
        "/api/nowplaying-soft-update"
        "?prev_type=episode&prev_tvshow_id=9&prev_season=1&prev_item_id=episode_0"
    )
    assert res.status_code == 200
    data = res.get_json()
    assert data["soft"] is True
    assert data["prev"]["tvshow_id"] == 9
    assert data["prev"]["season"] == 1


def test_templates_include_soft_identity(app_module, monkeypatch):
    import episode_nowplaying
    import music_nowplaying
    import requests

    monkeypatch.setattr(
        requests, "post", lambda *a, **k: (_ for _ in ()).throw(requests.exceptions.ConnectionError("no kodi"))
    )
    progress = {
        "percentage": 10,
        "time": {"hours": 0, "minutes": 1, "seconds": 0},
        "totaltime": {"hours": 0, "minutes": 40, "seconds": 0},
        "speed": 1,
    }
    with app_module.app.app_context():
        ep = episode_nowplaying.generate_html(
            {
                "id": 1,
                "title": "Pilot",
                "showtitle": "Demo",
                "season": 1,
                "episode": 1,
                "plot": "P",
                "tvshowid": 9,
                "genre": [],
            },
            "b" * 32,
            {},
            progress,
            {"rating": 8.0, "uniqueid": {}},
        )
        song = music_nowplaying.generate_html(
            {"id": 2, "title": "Song", "artist": ["A"], "album": "Alb", "genre": []},
            "c" * 32,
            {},
            progress,
            {"rating": 0, "albumid": 10, "artistid": [3]},
        )
    assert "window.SOFT_IDENTITY" in ep
    assert "soft-badge-title" in ep
    assert "attemptSoftUpdate" in ep
    assert "window.SOFT_IDENTITY" in song
    assert "soft-badge-track" in song
    assert "attemptSoftUpdate" in song

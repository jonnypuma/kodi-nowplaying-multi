def test_make_playback_fingerprint_changes_with_item(app_module):
    a = app_module.make_playback_fingerprint({
        "type": "movie",
        "id": 1,
        "title": "One",
        "file": "/a.mkv",
    })
    b = app_module.make_playback_fingerprint({
        "type": "movie",
        "id": 2,
        "title": "Two",
        "file": "/b.mkv",
    })
    assert a != b
    assert a.startswith("movie:1:")


def test_store_and_serve_cached_nowplaying(client, app_module, patch_into):
    app_module.nowplaying_cache.clear()
    app_module.server_backoff.clear()
    app_module.KODI_SERVERS = {
        1: {
            "id": 1,
            "host": "http://10.0.0.1:8080",
            "ip": "10.0.0.1",
            "label": "Living Room",
            "auth": None,
            "username": "",
            "password": "",
        },
    }
    payload = {
        "html": "<html><body>Cached NP</body></html>",
        "idle": False,
        "downloaded_art": {"poster": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa_poster.jpg"},
        "fingerprint": "movie:9:/x.mkv:Demo::None:None",
        "title": "Demo Movie",
        "media_type": "movie",
        "paused": False,
        "session_id": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    }
    app_module.store_playing_cache(1, payload)

    entry = app_module.get_cache_entry(1)
    assert entry["cache_ready"] is True
    assert entry["thumb"] == "/media/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa_poster.jpg"
    assert entry["title"] == "Demo Movie"

    overview = client.get("/api/overview").get_json()
    assert overview["servers"][0]["cache_ready"] is True
    assert overview["servers"][0]["thumb"].endswith("_poster.jpg")
    assert overview["servers"][0]["title"] == "Demo Movie"

    with client.session_transaction() as sess:
        sess["active_server_id"] = 1

    # Cache hit only when live fingerprint still matches the stored page.
    def matching_probe(server_id, bypass_backoff=False):
        return {
            "playing": True,
            "fingerprint": payload["fingerprint"],
            "media_type": "movie",
            "title": "Demo Movie",
        }

    patch_into(app_module, "probe_playback_fingerprint", matching_probe)
    start = client.get("/start-nowplaying-load").get_json()
    assert start["cache_hit"] is True
    content = client.get(f"/nowplaying-content/{start['job_id']}")
    assert content.status_code == 200
    assert b"Cached NP" in content.data
    page = client.get("/nowplaying")
    assert page.status_code == 200
    assert b"Cached NP" in page.data
    second = client.get(f"/nowplaying-content/{start['job_id']}")
    assert second.status_code == 410
    assert b"already consumed" in second.data


def test_start_nowplaying_load_skips_stale_cache(client, app_module, patch_into, monkeypatch):
    """Artist/track change must not return the previous now-playing HTML from cache."""
    app_module.nowplaying_cache.clear()
    app_module.load_jobs.clear()
    app_module.server_backoff.clear()
    app_module.KODI_SERVERS = {
        1: {
            "id": 1,
            "host": "http://10.0.0.1:8080",
            "ip": "10.0.0.1",
            "label": "Living Room",
            "auth": None,
            "username": "",
            "password": "",
        },
    }
    app_module.store_playing_cache(1, {
        "html": "<html><body>Aurora stale</body></html>",
        "idle": False,
        "downloaded_art": {},
        "fingerprint": "song:11299:/aurora.flac:Animal::None:None",
        "title": "Animal",
        "media_type": "song",
        "paused": False,
        "session_id": "aurora-session",
    })

    def oasis_probe(server_id, bypass_backoff=False):
        return {
            "playing": True,
            "fingerprint": "song:999:/oasis.flac:Fuckin in the Bushes::None:None",
            "media_type": "song",
            "title": "Fuckin in the Bushes",
        }

    patch_into(app_module, "probe_playback_fingerprint", oasis_probe)

    # Avoid a real background build; we only care that cache was not served.
    monkeypatch.setattr(
        "kodi_np.routes.playback.run_nowplaying_job",
        lambda job_id: None,
    )

    with client.session_transaction() as sess:
        sess["active_server_id"] = 1
    start = client.get("/start-nowplaying-load").get_json()
    assert start["cache_hit"] is False
    job = app_module.load_jobs[start["job_id"]]
    assert job["status"] == "pending"
    assert job.get("html") is None


def test_clear_cache_playback_marks_idle(app_module):
    app_module.nowplaying_cache.clear()
    app_module.KODI_SERVERS = {
        2: {
            "id": 2,
            "host": "http://10.0.0.2:8080",
            "ip": "10.0.0.2",
            "label": "",
            "auth": None,
            "username": "",
            "password": "",
        },
    }
    app_module.store_playing_cache(2, {
        "html": "<html>x</html>",
        "downloaded_art": {},
        "fingerprint": "movie:1",
        "title": "X",
        "media_type": "movie",
        "paused": False,
        "session_id": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
    })
    app_module.clear_cache_playback(2, {"connected": True, "error": None})
    entry = app_module.get_cache_entry(2)
    assert entry["playing"] is False
    assert entry["html"] is None
    assert entry["cache_ready"] is False


def test_cached_art_protected_from_cleanup(app_module, tmp_path):
    app_module.nowplaying_cache.clear()
    art_name = "cccccccccccccccccccccccccccccccc_poster.jpg"
    art_path = tmp_path / art_name
    art_path.write_bytes(b"fake")
    # Make it old enough to be cleaned
    old = 10 * 60 * 60
    import os
    os.utime(art_path, (os.path.getmtime(art_path) - old, os.path.getmtime(art_path) - old))

    previous_dir = app_module.ART_TMP_DIR
    app_module.ART_TMP_DIR = str(tmp_path)
    try:
        app_module.store_playing_cache(1, {
            "html": "<html>x</html>",
            "downloaded_art": {"poster": art_name},
            "fingerprint": "movie:1",
            "title": "X",
            "media_type": "movie",
            "paused": False,
            "session_id": "cccccccccccccccccccccccccccccccc",
        })
        app_module.cleanup_old_artwork_files()
        assert art_path.exists()
    finally:
        app_module.ART_TMP_DIR = previous_dir


def test_overview_link_in_nowplaying_templates():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1] / "kodi-np-multi" / "templates"
    partial = (root / "partials" / "side_panel.html").read_text(encoding="utf-8")
    assert 'href="/overview"' in partial
    assert "Multi-server overview" in partial
    for name in ("movie_nowplaying.html", "episode_nowplaying.html", "music_nowplaying.html"):
        text = (root / name).read_text(encoding="utf-8")
        assert "partials/side_panel.html" in text

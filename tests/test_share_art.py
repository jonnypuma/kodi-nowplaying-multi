"""Tests for identity-scoped artwork / metadata share reuse."""
import os


def _write_art(tmp_path, filename, content=b"art-bytes"):
    path = tmp_path / filename
    path.write_bytes(content)
    return str(path)


def test_classify_art_buckets_provenance(app_module):
    buckets = app_module.classify_art_buckets({
        "tvshow.poster": "show/poster.jpg",
        "tvshow.fanart": "show/fanart.jpg",
        "season.poster": "season/poster.jpg",
        "album.thumb": "album/cover.jpg",
        "album.front": "album/front.jpg",
        "artist.clearlogo": "artist/logo.png",
        "albumartist.fanart": "artist/fanart.jpg",
        "thumbnail": "episode/thumb.jpg",
    })
    assert buckets["tvshow"]["poster"] == "show/poster.jpg"
    assert buckets["tvshow"]["fanart"] == "show/fanart.jpg"
    assert buckets["season"]["season.poster"] == "season/poster.jpg"
    assert buckets["album"]["thumbnail"] == "album/cover.jpg"
    assert buckets["album"]["front"] == "album/front.jpg"
    assert buckets["artist"]["clearlogo"] == "artist/logo.png"
    assert buckets["artist"]["fanart"] == "artist/fanart.jpg"
    assert buckets["item"]["thumbnail"] == "episode/thumb.jpg"


def test_share_art_filename_is_servable(app_module):
    name = app_module.share_art_filename(1, "tvshow", 42, "season.poster")
    assert name.startswith("share_")
    assert name.endswith("_season.poster.jpg")
    assert app_module.is_artwork_filename(name)
    assert app_module.ARTWORK_FILENAME_RE.fullmatch(name)


def test_apply_share_reuse_same_show_same_season(app_module, tmp_path):
    previous = app_module.ART_TMP_DIR
    app_module.ART_TMP_DIR = str(tmp_path)
    try:
        poster = app_module.share_art_filename(1, "tvshow", 9, "poster")
        season = app_module.share_art_filename(1, "season", "9:1", "season.poster")
        _write_art(tmp_path, poster)
        _write_art(tmp_path, season)
        prior = app_module.empty_share()
        prior["tvshow_id"] = 9
        prior["season"] = 1
        prior["art_files"] = {
            "tvshow": {"poster": poster, "fanart": "missing.jpg"},
            "season": {"season.poster": season},
        }
        prior["art_sources"] = {
            "tvshow": {"poster": "nfs://show/poster.jpg"},
            "season": {"season.poster": "nfs://show/season1.jpg"},
        }
        downloaded = {}
        app_module.apply_share_reuse(
            1, "tvshow", 9,
            {"poster": "nfs://show/poster.jpg"},
            prior, downloaded,
        )
        app_module.apply_share_reuse(
            1, "season", "9:1",
            {"season.poster": "nfs://show/season1.jpg"},
            prior, downloaded,
        )
        assert downloaded["poster"] == poster
        assert downloaded["season.poster"] == season
        assert "fanart" not in downloaded  # missing file skipped
    finally:
        app_module.ART_TMP_DIR = previous


def test_apply_share_reuse_invalidates_changed_source(app_module, tmp_path):
    previous = app_module.ART_TMP_DIR
    app_module.ART_TMP_DIR = str(tmp_path)
    try:
        poster = app_module.share_art_filename(1, "tvshow", 9, "poster")
        _write_art(tmp_path, poster)
        prior = app_module.empty_share()
        prior["tvshow_id"] = 9
        prior["art_files"] = {"tvshow": {"poster": poster}}
        prior["art_sources"] = {"tvshow": {"poster": "nfs://old/poster.jpg"}}
        downloaded = {}
        app_module.apply_share_reuse(
            1, "tvshow", 9,
            {"poster": "nfs://new/poster.jpg"},
            prior, downloaded,
        )
        assert "poster" not in downloaded
    finally:
        app_module.ART_TMP_DIR = previous


def test_apply_share_reuse_new_season_keeps_show_drops_season(app_module, tmp_path):
    previous = app_module.ART_TMP_DIR
    app_module.ART_TMP_DIR = str(tmp_path)
    try:
        poster = app_module.share_art_filename(1, "tvshow", 9, "poster")
        season1 = app_module.share_art_filename(1, "season", "9:1", "season.poster")
        _write_art(tmp_path, poster)
        _write_art(tmp_path, season1)
        prior = app_module.empty_share()
        prior["tvshow_id"] = 9
        prior["season"] = 1
        prior["art_files"] = {
            "tvshow": {"poster": poster},
            "season": {"season.poster": season1},
        }
        prior["art_sources"] = {
            "tvshow": {"poster": "nfs://show/poster.jpg"},
            "season": {"season.poster": "nfs://show/s1.jpg"},
        }
        downloaded = {}
        app_module.apply_share_reuse(
            1, "tvshow", 9, {"poster": "nfs://show/poster.jpg"}, prior, downloaded
        )
        app_module.apply_share_reuse(
            1, "season", "9:2", {"season.poster": "nfs://show/s2.jpg"}, prior, downloaded
        )
        assert downloaded["poster"] == poster
        assert "season.poster" not in downloaded
    finally:
        app_module.ART_TMP_DIR = previous


def test_apply_share_reuse_music_album_and_artist(app_module, tmp_path):
    previous = app_module.ART_TMP_DIR
    app_module.ART_TMP_DIR = str(tmp_path)
    try:
        cover = app_module.share_art_filename(1, "album", 100, "thumbnail")
        logo = app_module.share_art_filename(1, "artist", 200, "clearlogo")
        _write_art(tmp_path, cover)
        _write_art(tmp_path, logo)
        prior = app_module.empty_share()
        prior["album_id"] = 100
        prior["artist_id"] = 200
        prior["art_files"] = {
            "album": {"thumbnail": cover},
            "artist": {"clearlogo": logo},
        }
        prior["art_sources"] = {
            "album": {"thumbnail": "nfs://album/cover.jpg"},
            "artist": {"clearlogo": "nfs://artist/logo.png"},
        }
        # Same album
        downloaded = {}
        app_module.apply_share_reuse(
            1, "album", 100, {"thumbnail": "nfs://album/cover.jpg"}, prior, downloaded
        )
        app_module.apply_share_reuse(
            1, "artist", 200, {"clearlogo": "nfs://artist/logo.png"}, prior, downloaded
        )
        assert downloaded["thumbnail"] == cover
        assert downloaded["clearlogo"] == logo

        # New album, same artist
        downloaded2 = {}
        app_module.apply_share_reuse(
            1, "album", 101, {"thumbnail": "nfs://album2/cover.jpg"}, prior, downloaded2
        )
        app_module.apply_share_reuse(
            1, "artist", 200, {"clearlogo": "nfs://artist/logo.png"}, prior, downloaded2
        )
        assert "thumbnail" not in downloaded2
        assert downloaded2["clearlogo"] == logo
    finally:
        app_module.ART_TMP_DIR = previous


def test_clear_cache_playback_keeps_share(app_module):
    app_module.nowplaying_cache.clear()
    app_module.KODI_SERVERS = {
        1: {"id": 1, "host": "http://10.0.0.1:8080", "ip": "10.0.0.1", "label": "", "auth": None},
    }
    share = app_module.empty_share()
    share["tvshow_id"] = 7
    share["season"] = 2
    share["art_files"] = {"tvshow": {"poster": "share_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa_poster.jpg"}}
    app_module.store_playing_cache(1, {
        "html": "<html>ep</html>",
        "downloaded_art": {"poster": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa_poster.jpg"},
        "fingerprint": "episode:1",
        "title": "Ep",
        "media_type": "episode",
        "paused": False,
        "session_id": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        "share": share,
    })
    app_module.clear_cache_playback(1, {"connected": True, "error": None})
    entry = app_module.get_cache_entry(1)
    assert entry["html"] is None
    assert entry["share"]["tvshow_id"] == 7
    assert entry["share"]["art_files"]["tvshow"]["poster"].startswith("share_")


def test_store_playing_cache_movie_does_not_require_share(app_module):
    app_module.nowplaying_cache.clear()
    app_module.KODI_SERVERS = {
        1: {"id": 1, "host": "http://10.0.0.1:8080", "ip": "10.0.0.1", "label": "", "auth": None},
    }
    prior_share = app_module.empty_share()
    prior_share["album_id"] = 55
    app_module.set_cache_entry(1, share=prior_share)
    app_module.store_playing_cache(1, {
        "html": "<html>movie</html>",
        "downloaded_art": {"poster": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb_poster.jpg"},
        "fingerprint": "movie:1",
        "title": "Film",
        "media_type": "movie",
        "paused": False,
        "session_id": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
        "share": prior_share,  # movies pass through prior share unchanged
    })
    entry = app_module.get_cache_entry(1)
    assert entry["media_type"] == "movie"
    assert entry["share"]["album_id"] == 55


def test_shared_art_protected_from_cleanup(app_module, tmp_path):
    app_module.nowplaying_cache.clear()
    previous = app_module.ART_TMP_DIR
    app_module.ART_TMP_DIR = str(tmp_path)
    try:
        share_name = app_module.share_art_filename(1, "tvshow", 3, "poster")
        art_path = tmp_path / share_name
        art_path.write_bytes(b"shared")
        old = 10 * 60 * 60
        os.utime(art_path, (os.path.getmtime(art_path) - old, os.path.getmtime(art_path) - old))

        share = app_module.empty_share()
        share["tvshow_id"] = 3
        share["art_files"] = {"tvshow": {"poster": share_name}}
        app_module.store_playing_cache(1, {
            "html": "<html>x</html>",
            "downloaded_art": {"poster": share_name},
            "fingerprint": "episode:1",
            "title": "X",
            "media_type": "episode",
            "paused": False,
            "session_id": "cccccccccccccccccccccccccccccccc",
            "share": share,
        })
        app_module.cleanup_old_artwork_files()
        assert art_path.exists()
    finally:
        app_module.ART_TMP_DIR = previous


def test_ensure_share_file_copies_session_file(app_module, tmp_path):
    previous = app_module.ART_TMP_DIR
    app_module.ART_TMP_DIR = str(tmp_path)
    try:
        session_name = "dddddddddddddddddddddddddddddddd_poster.jpg"
        _write_art(tmp_path, session_name, b"poster-data")
        share_name = app_module.ensure_share_file(
            1, "tvshow", 11, "poster", "nfs://show/poster.jpg", session_filename=session_name
        )
        assert share_name.startswith("share_")
        assert (tmp_path / share_name).read_bytes() == b"poster-data"
    finally:
        app_module.ART_TMP_DIR = previous


def test_primary_artist_id(app_module):
    assert app_module.primary_artist_id([10, 20]) == 10
    assert app_module.primary_artist_id(15) == 15
    assert app_module.primary_artist_id([]) is None
    assert app_module.primary_artist_id(None) is None

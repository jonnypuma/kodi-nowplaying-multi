"""Tests for album/artist metadata enrichment helpers."""

from kodi_np import music_meta


def test_enrich_album_skips_when_description_present(monkeypatch):
    called = {"n": 0}

    def boom(*_a, **_k):
        called["n"] += 1
        raise AssertionError("should not fetch when Kodi already has description")

    monkeypatch.setattr(music_meta, "fetch_album_description", boom)
    out = music_meta.enrich_album_details(
        {"title": "Lost in Space", "description": "From Kodi"},
        "Aimee Mann",
        "Lost in Space",
    )
    assert out["description"] == "From Kodi"
    assert called["n"] == 0


def test_enrich_artist_fills_from_external(monkeypatch):
    monkeypatch.setattr(
        music_meta,
        "fetch_artist_biography",
        lambda _name: {"text": "Bio from AudioDB", "source": "theaudiodb", "born": "1960"},
    )
    out = music_meta.enrich_artist_details({"description": ""}, "Aimee Mann")
    assert out["description"] == "Bio from AudioDB"
    assert out["description_source"] == "theaudiodb"
    assert out["born"] == "1960"


def test_enrich_album_fills_from_external(monkeypatch):
    monkeypatch.setattr(
        music_meta,
        "fetch_album_description",
        lambda _artist, _album: {"text": "Album blurb", "source": "wikipedia"},
    )
    out = music_meta.enrich_album_details({}, "Aimee Mann", "Lost in Space")
    assert out["description"] == "Album blurb"
    assert out["description_source"] == "wikipedia"


def test_api_music_meta_empty_request(client):
    response = client.post("/api/music-meta", json={"need_album": False, "need_artist": False})
    assert response.status_code == 200
    data = response.get_json()
    assert data["album_description"] is None
    assert data["artist_bio"] is None


def test_api_music_meta_fills_artist(client, monkeypatch):
    from kodi_np.routes import extras as extras_mod

    monkeypatch.setattr(
        extras_mod,
        "fetch_artist_biography",
        lambda _name: {"text": "Async bio", "source": "wikipedia", "born": "1960"},
    )
    monkeypatch.setattr(extras_mod, "fetch_album_description", lambda *_a, **_k: None)
    monkeypatch.setattr(extras_mod, "get_active_server", lambda: None)

    response = client.post("/api/music-meta", json={
        "artist": "Aimee Mann",
        "album": "Lost in Space",
        "need_album": False,
        "need_artist": True,
        "artist_id": 1295,
    })
    assert response.status_code == 200
    data = response.get_json()
    assert data["artist_bio"] == "Async bio"
    assert data["artist_source"] == "wikipedia"
    assert data["artist_born"] == "1960"

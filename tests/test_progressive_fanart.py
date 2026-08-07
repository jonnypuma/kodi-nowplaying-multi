"""Progressive fanart selection and lazy /api/fanart."""


def test_select_primary_fanart_movie_prefers_main(app_module):
    variants = {
        "fanart": "nfs://x/fanart.jpg",
        "fanart2": "nfs://x/fanart2.jpg",
        "extrafanart_main": "nfs://x/extrafanart/fanart.jpg",
    }
    assert app_module.select_primary_fanart_key("movie", variants, {}) == "fanart"


def test_select_primary_fanart_music_prefers_extra(app_module):
    variants = {
        "fanart": "nfs://x/fanart.jpg",
        "extrafanart_main": "nfs://x/extrafanart/fanart.jpg",
        "extrafanart_fanart2": "nfs://x/extrafanart/fanart2.jpg",
    }
    assert app_module.select_primary_fanart_key("song", variants, {}) == "extrafanart_main"


def test_select_primary_fanart_episode_falls_back_to_extra(app_module):
    variants = {"extrafanart_main": "nfs://x/extra/fanart.jpg", "fanart2": "nfs://x/fanart2.jpg"}
    assert app_module.select_primary_fanart_key("episode", variants, {}) == "fanart2"


def test_api_fanart_requires_fields(client):
    response = client.post("/api/fanart", json={})
    assert response.status_code == 400
    response = client.post("/api/fanart", json={"path": "image://x/", "key": "fanart2"})
    assert response.status_code == 400


def test_api_fanart_reuses_existing_file(client, app_module, tmp_path, monkeypatch):
    app_module.ART_TMP_DIR = str(tmp_path)
    app_module.ART_TMP_PATH = tmp_path
    app_module.KODI_SERVERS = {
        1: {"id": 1, "host": "http://10.0.0.1:8080", "ip": "10.0.0.1", "label": "", "auth": None},
    }
    with client.session_transaction() as sess:
        sess["active_server_id"] = 1

    session_id = "a" * 32
    key = "fanart2"
    filename = f"{session_id}_{key}.jpg"
    (tmp_path / filename).write_bytes(b"x" * 300_000)

    monkeypatch.setattr(
        "kodi_np.routes.extras.download_fanart_variant",
        lambda path, key, session_id, server_id=None: filename,
    )
    response = client.post(
        "/api/fanart",
        json={"path": "image://nfs://share/fanart2.jpg/", "key": key, "session_id": session_id},
    )
    assert response.status_code == 200
    data = response.get_json()
    assert data["success"] is True
    assert data["url"] == f"/media/{filename}"
    assert data["key"] == key


def test_download_fanart_variant_rejects_bad_key(app_module, tmp_path):
    app_module.ART_TMP_DIR = str(tmp_path)
    app_module.KODI_SERVERS = {
        1: {"id": 1, "host": "http://10.0.0.1:8080", "ip": "10.0.0.1", "label": "", "auth": None},
    }
    assert (
        app_module.download_fanart_variant(
            "image://x/", "poster", "a" * 32, server_id=1
        )
        is None
    )

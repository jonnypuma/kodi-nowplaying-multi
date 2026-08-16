"""Static asset and artwork serving routes (3.1.9)."""
import pytest

PNG_HEADER = b"\x89PNG\r\n\x1a\n"
JPEG_HEADER = b"\xff\xd8\xff\xe0"
GIF_HEADER = b"GIF89a"


@pytest.mark.parametrize("path,mimetype", [
    ("/favicon.ico", "image/x-icon"),
    ("/play-button.png", "image/png"),
    ("/pause-button.png", "image/png"),
])
def test_bundled_assets_are_served(client, path, mimetype):
    response = client.get(path)
    assert response.status_code == 200
    assert response.mimetype == mimetype
    assert len(response.get_data()) > 0


def test_shared_stylesheet_and_script_are_served(client):
    for name in ("nowplaying-common.css", "nowplaying-common.js"):
        response = client.get(f"/static/{name}")
        assert response.status_code == 200, name
        assert len(response.get_data()) > 0


def test_static_route_rejects_traversal(client):
    for candidate in ("..%2fconfig.py", "../kodi_np/config.py", "sub/dir.js"):
        response = client.get(f"/static/{candidate}")
        assert response.status_code in (400, 404), candidate


def test_unknown_static_file_is_404(client):
    assert client.get("/static/no-such-file.js").status_code == 404


def test_media_route_rejects_invalid_filename(client):
    response = client.get("/media/not a valid name.jpg")
    assert response.status_code in (400, 404)


def test_media_route_404s_for_missing_file(client, app_module, tmp_path):
    app_module.ART_TMP_DIR = str(tmp_path)
    app_module.ART_TMP_PATH = tmp_path
    response = client.get("/media/" + "a" * 32 + "_poster.jpg")
    assert response.status_code == 404


@pytest.mark.parametrize("header,expected", [
    (PNG_HEADER, "image/png"),
    (JPEG_HEADER, "image/jpeg"),
    (GIF_HEADER, "image/gif"),
    (b"RIFF" + b"\x00\x00\x00\x00" + b"WEBP", "image/webp"),
    (b"garbage bytes!!", "image/jpeg"),
])
def test_media_route_sniffs_real_image_type(client, app_module, tmp_path, header, expected):
    """Artwork is always saved as .jpg regardless of what Kodi actually sent."""
    app_module.ART_TMP_DIR = str(tmp_path)
    app_module.ART_TMP_PATH = tmp_path
    filename = "b" * 32 + "_poster.jpg"
    (tmp_path / filename).write_bytes(header + b"\x00" * 64)

    response = client.get(f"/media/{filename}")
    assert response.status_code == 200
    assert response.mimetype == expected


def test_sniff_falls_back_when_file_is_unreadable(app_module, tmp_path):
    from kodi_np.routes.static_media import sniff_image_mimetype

    assert sniff_image_mimetype(tmp_path / "missing.jpg") == "image/jpeg"

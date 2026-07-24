"""Tests for /media content-type sniffing."""


def test_sniff_image_mimetype_png(app_module, tmp_path):
    path = tmp_path / "logo.jpg"  # misleading extension
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 20)
    from kodi_np.routes.static_media import sniff_image_mimetype

    assert sniff_image_mimetype(path) == "image/png"


def test_sniff_image_mimetype_jpeg(app_module, tmp_path):
    path = tmp_path / "art.jpg"
    path.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 20)
    from kodi_np.routes.static_media import sniff_image_mimetype

    assert sniff_image_mimetype(path) == "image/jpeg"


def test_media_route_serves_png_as_png(client, app_module, tmp_path):
    previous = app_module.ART_TMP_DIR
    app_module.ART_TMP_DIR = str(tmp_path)
    app_module.ART_TMP_PATH = tmp_path
    try:
        name = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa_clearlogo.jpg"
        path = tmp_path / name
        # Minimal valid-ish PNG header is enough for sniff + send_file
        path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 64)
        resp = client.get(f"/media/{name}")
        assert resp.status_code == 200
        assert resp.mimetype == "image/png"
    finally:
        app_module.ART_TMP_DIR = previous
        from pathlib import Path

        app_module.ART_TMP_PATH = Path(previous).resolve()

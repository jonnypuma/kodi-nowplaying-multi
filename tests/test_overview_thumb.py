"""Overview tile thumb art selection."""
from kodi_np.art import pick_thumb_filename


def test_pick_thumb_prefers_banner_then_clearart_then_landscape():
    assert pick_thumb_filename({
        "poster": "p.jpg",
        "fanart": "f.jpg",
        "banner": "b.jpg",
        "clearart": "c.jpg",
        "landscape": "l.jpg",
    }) == "b.jpg"
    assert pick_thumb_filename({
        "poster": "p.jpg",
        "clearart": "c.jpg",
        "landscape": "l.jpg",
    }) == "c.jpg"
    assert pick_thumb_filename({
        "poster": "p.jpg",
        "landscape": "l.jpg",
        "thumbnail": "t.jpg",
    }) == "l.jpg"
    assert pick_thumb_filename({
        "poster": "p.jpg",
        "thumbnail": "t.jpg",
    }) == "p.jpg"


def test_landscape_in_art_types(app_module):
    assert "landscape" in app_module.ART_TYPES
    assert app_module.THUMB_ART_PRIORITY[:3] == ("banner", "clearart", "landscape")

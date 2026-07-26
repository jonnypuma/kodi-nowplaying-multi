"""Overview tile thumb art selection."""
from kodi_np.art import pick_fanart_filename, pick_thumb_art, pick_thumb_filename


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


def test_pick_thumb_art_marks_banner_key():
    assert pick_thumb_art({"banner": "b.jpg", "fanart": "f.jpg"}) == ("b.jpg", "banner")
    assert pick_thumb_art({"clearart": "c.jpg", "fanart": "f.jpg"}) == ("c.jpg", "clearart")


def test_pick_fanart_filename():
    assert pick_fanart_filename({"fanart2": "f2.jpg", "fanart": "f.jpg"}) == "f.jpg"
    assert pick_fanart_filename({"fanart3": "f3.jpg"}) == "f3.jpg"
    assert pick_fanart_filename({"poster": "p.jpg"}) is None


def test_store_playing_cache_exposes_banner_fanart_layer(app_module):
    app_module.nowplaying_cache.clear()
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
        "html": "<html></html>",
        "downloaded_art": {
            "banner": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb_banner.jpg",
            "fanart": "ffffffffffffffffffffffffffffffff_fanart.jpg",
            "poster": "pppppppppppppppppppppppppppppppp_poster.jpg",
        },
        "fingerprint": "episode:1",
        "title": "Demo",
        "media_type": "episode",
        "paused": False,
        "session_id": "sess",
    })
    overview = app_module.overview_from_cache(1)
    assert overview["thumb_is_banner"] is True
    assert overview["thumb"].endswith("_banner.jpg")
    assert overview["fanart"].endswith("_fanart.jpg")


def test_landscape_in_art_types(app_module):
    assert "landscape" in app_module.ART_TYPES
    assert app_module.THUMB_ART_PRIORITY[:3] == ("banner", "clearart", "landscape")

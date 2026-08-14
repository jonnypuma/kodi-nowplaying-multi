import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1] / "kodi-np-multi"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from kodi_np.media_info import (
    aspect_ratio_label,
    container_label,
    fanart_variant_urls,
    format_playback_time,
    kind_badge_html,
    language_sets,
    resolution_label,
    up_next_html,
)


def test_format_playback_time_mmss_and_hhmmss():
    assert format_playback_time(65, 90) == "01:05"
    assert format_playback_time(3661, 4000) == "01:01:01"


def test_resolution_and_container():
    assert resolution_label(3840, 2160) == "4K"
    assert resolution_label(1920, 1080) == "1080p"
    assert container_label({}, {"file": "movie.mkv"}) == "MKV"
    assert aspect_ratio_label({"VideoPlayer.VideoAspect": "1.78"}) == "16:9"


def test_language_sets_normalize_ger():
    langs = language_sets(
        [{"language": "ger"}],
        [{"language": "eng"}],
        {"VideoPlayer.AudioLanguage": "ger"},
    )
    assert langs["current_audio"] == "DEU"
    assert "DEU" in langs["all_audio"]


def test_fanart_and_up_next_html():
    urls = fanart_variant_urls({"fanart": "abc.jpg", "extrafanart_1": "def.jpg"})
    assert urls == ["/media/abc.jpg", "/media/def.jpg"]
    assert "Up next" in up_next_html({"up_next_label": "Next Track"})
    assert up_next_html({}) == ""
    assert "Live" in kind_badge_html("channel")
    assert kind_badge_html("movie") == ""


def test_playlist_item_label(patch_into, app_module):
    from kodi_np.playlist import _item_label, get_up_next_label

    assert _item_label({"artist": ["A"], "title": "Song", "album": "LP"}) == "A — Song (LP)"
    assert "S01E02" in _item_label({"showtitle": "Show", "season": 1, "episode": 2, "title": "Pilot"})

    def fake_rpc(method, params=None, **kwargs):
        if method == "Player.GetProperties":
            return {"result": {"playlistid": 0, "position": 0}}
        if method == "Playlist.GetItems":
            return {"result": {"items": [{"title": "One"}, {"title": "Two"}]}}
        return None

    patch_into(app_module, "kodi_rpc", fake_rpc)
    from kodi_np import playlist
    playlist.kodi_rpc = fake_rpc
    assert get_up_next_label(1) == "Two"

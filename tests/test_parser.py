import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1] / "kodi-np-multi"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from parser import infer_playback_type, get_media_handler


def test_infer_movie_by_type():
    assert infer_playback_type({"type": "movie", "title": "Inception"}) == "movie"


def test_infer_episode_by_fields():
    assert infer_playback_type({
        "showtitle": "Show",
        "episode": 3,
        "title": "Pilot",
    }) == "episode"


def test_infer_song_by_fields():
    assert infer_playback_type({
        "album": "Album",
        "artist": ["Artist"],
        "title": "Track",
    }) == "song"


def test_infer_unknown_falls_back_in_handler():
    assert infer_playback_type({"title": "Plugin Clip", "type": "unknown"}) == "video"
    handler = get_media_handler("unknown")
    assert handler.__name__.endswith("movie_nowplaying")


def test_infer_channel_and_musicvideo():
    assert infer_playback_type({"type": "channel", "title": "BBC One"}) == "channel"
    assert infer_playback_type({"type": "musicvideo", "title": "Video"}) == "musicvideo"
    assert get_media_handler("channel").__name__.endswith("movie_nowplaying")


def test_get_media_handlers():
    assert get_media_handler("movie").__name__.endswith("movie_nowplaying")
    assert get_media_handler("episode").__name__.endswith("episode_nowplaying")
    assert get_media_handler("song").__name__.endswith("music_nowplaying")

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
    assert infer_playback_type({"title": "Plugin Clip", "type": "unknown"}) == "unknown"
    handler = get_media_handler("unknown")
    assert handler.__name__ == "movie_nowplaying"


def test_get_media_handlers():
    assert get_media_handler("movie").__name__ == "movie_nowplaying"
    assert get_media_handler("episode").__name__ == "episode_nowplaying"
    assert get_media_handler("song").__name__ == "music_nowplaying"

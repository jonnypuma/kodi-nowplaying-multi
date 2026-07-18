import sys
from pathlib import Path

import pytest

APP_DIR = Path(__file__).resolve().parents[1] / "kodi-np-multi"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))


@pytest.fixture
def flask_app(app_module):
    return app_module.app


def test_movie_template_renders(flask_app, monkeypatch):
    import movie_nowplaying
    import requests

    monkeypatch.setattr(requests, "post", lambda *a, **k: (_ for _ in ()).throw(requests.exceptions.ConnectionError("no kodi")))

    item = {"title": "Test Movie", "plot": "A plot", "genre": ["Action"], "year": 2020}
    details = {"rating": 7.5, "uniqueid": {}}
    progress = {
        "percentage": 10,
        "time": {"hours": 0, "minutes": 5, "seconds": 0},
        "totaltime": {"hours": 1, "minutes": 0, "seconds": 0},
        "speed": 1,
    }

    with flask_app.app_context():
        html = movie_nowplaying.generate_html(item, "a" * 32, {}, progress, details)

    assert "Test Movie" in html
    assert "<html" in html.lower()


def test_episode_template_renders(flask_app, monkeypatch):
    import episode_nowplaying
    import requests

    monkeypatch.setattr(requests, "post", lambda *a, **k: (_ for _ in ()).throw(requests.exceptions.ConnectionError("no kodi")))

    item = {
        "title": "Pilot",
        "showtitle": "Demo Show",
        "season": 1,
        "episode": 1,
        "plot": "Starts here",
        "genre": ["Drama"],
    }
    details = {"rating": 8.0, "uniqueid": {}}
    progress = {
        "percentage": 20,
        "time": {"hours": 0, "minutes": 2, "seconds": 5},
        "totaltime": {"hours": 0, "minutes": 45, "seconds": 0},
        "speed": 1,
    }

    with flask_app.app_context():
        html = episode_nowplaying.generate_html(item, "b" * 32, {}, progress, details)

    assert "Demo Show" in html
    assert "Pilot" in html


def test_music_template_renders(flask_app, monkeypatch):
    import music_nowplaying
    import requests

    monkeypatch.setattr(requests, "post", lambda *a, **k: (_ for _ in ()).throw(requests.exceptions.ConnectionError("no kodi")))

    item = {
        "title": "Song Title",
        "artist": ["Artist"],
        "album": "Album",
        "genre": ["Rock"],
    }
    details = {"rating": 0, "album": {}}
    progress = {
        "percentage": 50,
        "time": {"hours": 0, "minutes": 1, "seconds": 30},
        "totaltime": {"hours": 0, "minutes": 3, "seconds": 0},
        "speed": 1,
    }

    with flask_app.app_context():
        html = music_nowplaying.generate_html(item, "c" * 32, {}, progress, details)

    assert "Song Title" in html or "Artist" in html

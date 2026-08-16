"""load_preferences() caching and the shared Kodi time helper (3.1.8)."""
import json

import pytest

from kodi_np.util import kodi_time_to_seconds


@pytest.fixture
def prefs_file(app_module, tmp_path):
    from kodi_np import preferences as prefs_mod

    app_module.PREFERENCES_DIR = tmp_path
    app_module.PREFERENCES_FILE = tmp_path / "preferences.json"
    prefs_mod.invalidate_preferences_cache()
    return app_module.PREFERENCES_FILE


def test_repeat_loads_do_not_reparse(prefs_file, monkeypatch):
    from kodi_np import preferences as prefs_mod

    prefs_file.write_text(json.dumps({"theme": "dark"}))

    reads = []
    original = prefs_mod._read_preferences_unlocked

    def counting_read():
        reads.append(1)
        return original()

    monkeypatch.setattr(prefs_mod, "_read_preferences_unlocked", counting_read)

    assert prefs_mod.load_preferences() == {"theme": "dark"}
    for _ in range(5):
        assert prefs_mod.load_preferences() == {"theme": "dark"}
    assert len(reads) == 1


def test_write_through_update_is_visible_immediately(prefs_file):
    from kodi_np import preferences as prefs_mod

    prefs_file.write_text(json.dumps({"theme": "dark"}))
    assert prefs_mod.load_preferences() == {"theme": "dark"}

    prefs_mod.update_preferences({"theme": "light", "blur": "on"})
    assert prefs_mod.load_preferences() == {"theme": "light", "blur": "on"}


def test_external_edit_is_picked_up(prefs_file):
    from kodi_np import preferences as prefs_mod

    prefs_file.write_text(json.dumps({"theme": "dark"}))
    assert prefs_mod.load_preferences() == {"theme": "dark"}

    # A different size guarantees the stat fingerprint changes even if the
    # filesystem's mtime resolution is coarse.
    prefs_file.write_text(json.dumps({"theme": "midnight", "extra": "value"}))
    prefs_mod.invalidate_preferences_cache()
    assert prefs_mod.load_preferences()["theme"] == "midnight"


def test_callers_cannot_mutate_the_cache(prefs_file):
    from kodi_np import preferences as prefs_mod

    prefs_file.write_text(json.dumps({"theme": "dark"}))
    first = prefs_mod.load_preferences()
    first["theme"] = "tampered"
    assert prefs_mod.load_preferences() == {"theme": "dark"}


def test_missing_file_returns_empty(prefs_file):
    from kodi_np import preferences as prefs_mod

    assert prefs_mod.load_preferences() == {}


@pytest.mark.parametrize("chunk,expected", [
    ({"hours": 1, "minutes": 2, "seconds": 3}, 3723),
    ({"minutes": 5, "seconds": 0}, 300),
    ({}, 0),
    ({"hours": None, "minutes": None, "seconds": None}, 0),
    ({"hours": "1", "minutes": "0", "seconds": "30"}, 3630),
    (None, 0),
    ("nonsense", 0),
    ({"hours": "abc"}, 0),
])
def test_kodi_time_to_seconds(chunk, expected):
    assert kodi_time_to_seconds(chunk) == expected

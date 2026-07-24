"""Preference persistence / concurrent update tests."""
import threading


def test_update_preferences_merges_under_concurrency(app_module, tmp_path):
    prefs_dir = tmp_path / "preferences"
    prefs_dir.mkdir()
    app_module.PREFERENCES_DIR = prefs_dir
    app_module.PREFERENCES_FILE = prefs_dir / "preferences.json"

    # Seed one key
    assert app_module.update_preferences({"overlayPreference": "enabled"})

    errors = []

    def writer(key, value):
        try:
            ok = app_module.update_preferences({key: value})
            if not ok:
                errors.append(f"{key} save failed")
        except Exception as exc:
            errors.append(str(exc))

    threads = [
        threading.Thread(target=writer, args=("blurAmount", "71")),
        threading.Thread(target=writer, args=("marqueeInterval", "14")),
        threading.Thread(target=writer, args=("fanartInterval", "12")),
        threading.Thread(target=writer, args=("overlayOpacity", "72")),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
    prefs = app_module.load_preferences()
    assert prefs["overlayPreference"] == "enabled"
    assert prefs["blurAmount"] == "71"
    assert prefs["marqueeInterval"] == "14"
    assert prefs["fanartInterval"] == "12"
    assert prefs["overlayOpacity"] == "72"


def test_preferences_post_uses_atomic_merge(client, app_module, tmp_path):
    prefs_dir = tmp_path / "preferences"
    prefs_dir.mkdir()
    app_module.PREFERENCES_DIR = prefs_dir
    app_module.PREFERENCES_FILE = prefs_dir / "preferences.json"
    app_module.update_preferences({"overlayPreference": "enabled"})

    r1 = client.post("/api/preferences", json={"blurAmount": "40"})
    r2 = client.post("/api/preferences", json={"overlayPreference": "enabled"})
    assert r1.status_code == 200
    assert r2.status_code == 200

    prefs = app_module.load_preferences()
    assert prefs["overlayPreference"] == "enabled"
    assert prefs["blurAmount"] == "40"

import importlib.util
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
APP_DIR = ROOT / "kodi-np-multi"


@pytest.fixture(scope="session")
def app_module(tmp_path_factory):
    """Load kodi-nowplaying.py via importlib (hyphenated filename)."""
    art_dir = tmp_path_factory.mktemp("art")
    prefs_dir = tmp_path_factory.mktemp("prefs")

    os.environ.setdefault("LOG_LEVEL", "WARNING")
    os.environ["ART_TMP_DIR"] = str(art_dir)
    os.environ["FLASK_SECRET_KEY"] = "test-secret-key"
    os.environ["CACHE_POLLER_ENABLED"] = "0"
    # Clear server env so tests control it explicitly
    for key in list(os.environ):
        if key.startswith("KODI_HOST") or key.startswith("KODI_USERNAME") or key.startswith("KODI_PASSWORD") or key in ("KODI_USER", "KODI_PASS"):
            os.environ.pop(key, None)

    os.environ["KODI_HOST_1"] = "http://192.168.0.10:8080"
    os.environ["KODI_HOST_LABEL_1"] = "Living Room"
    os.environ["KODI_USERNAME_1"] = "kodi"
    os.environ["KODI_PASSWORD_1"] = "secret"
    os.environ["KODI_HOST_2"] = "http://192.168.0.11:8080"
    os.environ["KODI_HOST_LABEL_2"] = "Bedroom"

    if str(APP_DIR) not in sys.path:
        sys.path.insert(0, str(APP_DIR))

    spec = importlib.util.spec_from_file_location(
        "kodi_nowplaying",
        APP_DIR / "kodi-nowplaying.py",
    )
    module = importlib.util.module_from_spec(spec)
    # Preferences path is fixed to /app/preferences in the module; override after load.
    spec.loader.exec_module(module)
    module.PREFERENCES_DIR = prefs_dir
    module.PREFERENCES_FILE = prefs_dir / "preferences.json"
    module.KODI_SERVERS = module.parse_kodi_servers()
    return module


@pytest.fixture
def client(app_module):
    app_module.app.config["TESTING"] = True
    with app_module.app.test_client() as test_client:
        yield test_client

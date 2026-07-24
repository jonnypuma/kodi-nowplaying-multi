import importlib.util
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
APP_DIR = ROOT / "kodi-np-multi"

_CONFIG_MIRROR = {
    "ART_TMP_DIR",
    "ART_TMP_PATH",
    "POLL_IDLE_CONFIRMATIONS",
    "POLL_ERROR_IDLE_CONFIRMATIONS",
    "SERVER_FAIL_BACKOFF_AFTER",
    "SERVER_FAIL_BACKOFF_SECONDS",
    "CACHE_POLLER_ENABLED",
    "CACHE_POLLER_INTERVAL",
    "PREFERENCES_DIR",
    "PREFERENCES_FILE",
    "KODI_SERVERS",
    "LOAD_JOB_TTL_SECONDS",
    "LOAD_JOB_STALE_SECONDS",
    "LOAD_JOB_MAX",
    "CACHE_PROBE_FAIL_CLEAR_AFTER",
}


class AppModuleFacade:
    """Proxy so app_module.X reads/writes hit kodi_np.config for shared state."""

    def __init__(self, module, config):
        object.__setattr__(self, "_module", module)
        object.__setattr__(self, "_config", config)

    def __getattr__(self, name):
        cfg = object.__getattribute__(self, "_config")
        mod = object.__getattribute__(self, "_module")
        if name in _CONFIG_MIRROR:
            return getattr(cfg, name)
        if hasattr(mod, name):
            return getattr(mod, name)
        if hasattr(cfg, name):
            return getattr(cfg, name)
        raise AttributeError(name)

    def __setattr__(self, name, value):
        if name in ("_module", "_config"):
            object.__setattr__(self, name, value)
            return
        cfg = object.__getattribute__(self, "_config")
        mod = object.__getattribute__(self, "_module")
        if name in _CONFIG_MIRROR:
            setattr(cfg, name, value)
            if name == "ART_TMP_DIR":
                setattr(cfg, "ART_TMP_PATH", Path(value).resolve())
            return
        # Allow monkeypatch / tests to attach callables onto the entry module
        setattr(mod, name, value)


@pytest.fixture(scope="session")
def app_module(tmp_path_factory):
    """Load kodi-nowplaying entry shim as kodi_nowplaying with config facade."""
    art_dir = tmp_path_factory.mktemp("art")
    prefs_dir = tmp_path_factory.mktemp("prefs")

    os.environ.setdefault("LOG_LEVEL", "WARNING")
    os.environ["ART_TMP_DIR"] = str(art_dir)
    os.environ["FLASK_SECRET_KEY"] = "test-secret-key"
    os.environ["CACHE_POLLER_ENABLED"] = "0"
    for key in list(os.environ):
        if key.startswith("KODI_HOST") or key.startswith("KODI_USERNAME") or key.startswith("KODI_PASSWORD") or key in (
            "KODI_USER",
            "KODI_PASS",
        ):
            os.environ.pop(key, None)

    os.environ["KODI_HOST_1"] = "http://192.168.0.10:8080"
    os.environ["KODI_HOST_LABEL_1"] = "Living Room"
    os.environ["KODI_USERNAME_1"] = "kodi"
    os.environ["KODI_PASSWORD_1"] = "secret"
    os.environ["KODI_HOST_2"] = "http://192.168.0.11:8080"
    os.environ["KODI_HOST_LABEL_2"] = "Bedroom"

    if str(APP_DIR) not in sys.path:
        sys.path.insert(0, str(APP_DIR))

    for name in list(sys.modules):
        if name == "kodi_np" or name.startswith("kodi_np.") or name == "kodi_nowplaying":
            del sys.modules[name]

    spec = importlib.util.spec_from_file_location(
        "kodi_nowplaying",
        APP_DIR / "kodi-nowplaying.py",
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["kodi_nowplaying"] = module
    spec.loader.exec_module(module)

    from kodi_np import config as config_mod
    from kodi_np.servers import init_servers

    config_mod.PREFERENCES_DIR = prefs_dir
    config_mod.PREFERENCES_FILE = prefs_dir / "preferences.json"
    config_mod.ART_TMP_DIR = str(art_dir)
    config_mod.ART_TMP_PATH = art_dir.resolve()
    init_servers()

    return AppModuleFacade(module, config_mod)


@pytest.fixture
def client(app_module):
    app_module.app.config["TESTING"] = True
    with app_module.app.test_client() as test_client:
        yield test_client


@pytest.fixture
def patch_into(monkeypatch):
    """Patch a name on app_module and on package modules that import it."""

    targets = {
        "kodi_rpc": [
            "kodi_np.rpc.kodi_rpc",
            "kodi_np.nowplaying.kodi_rpc",
            "kodi_np.cache.kodi_rpc",
            "kodi_np.art.kodi_rpc",
            "kodi_np.overview.kodi_rpc",
            "kodi_np.routes.playback.kodi_rpc",
            "kodi_np.routes.servers_prefs.kodi_rpc",
        ],
        "get_active_server": [
            "kodi_np.servers.get_active_server",
            "kodi_np.nowplaying.get_active_server",
            "kodi_np.cache.get_active_server",
            "kodi_np.art.get_active_server",
            "kodi_np.rpc.get_active_server",
            "kodi_np.routes.playback.get_active_server",
        ],
        "get_cache_entry": [
            "kodi_np.cache.get_cache_entry",
            "kodi_np.nowplaying.get_cache_entry",
            "kodi_np.routes.playback.get_cache_entry",
        ],
        "probe_playback_fingerprint": [
            "kodi_np.cache.probe_playback_fingerprint",
        ],
        "refresh_server_cache": [
            "kodi_np.cache.refresh_server_cache",
            "kodi_np.routes.overview.refresh_server_cache",
        ],
        "get_server_overview_status": [
            "kodi_np.overview.get_server_overview_status",
            "kodi_np.routes.overview.get_server_overview_status",
        ],
        "overview_from_cache": [
            "kodi_np.cache.overview_from_cache",
            "kodi_np.routes.overview.overview_from_cache",
        ],
        "build_nowplaying_soft_update": [
            "kodi_np.nowplaying.build_nowplaying_soft_update",
            "kodi_np.routes.playback.build_nowplaying_soft_update",
        ],
    }

    def _patch(app_module, name, value):
        monkeypatch.setattr(app_module, name, value, raising=False)
        for path in targets.get(name, []):
            monkeypatch.setattr(path, value, raising=False)

    return _patch

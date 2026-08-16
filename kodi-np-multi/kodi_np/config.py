"""Shared process configuration. Mutable runtime lives in kodi_np.state."""
from __future__ import annotations

import os
import re
import threading
import time
import uuid
from pathlib import Path

from flask import Flask

from logging_config import configure_logging
from kodi_np import state as _state

_tz = os.getenv("TZ", "").strip()
if _tz:
    os.environ["TZ"] = _tz
    if hasattr(time, "tzset"):
        time.tzset()

configure_logging()

APP_VERSION = "3.4.1"
APP_DIR = Path(__file__).resolve().parent.parent
PREFERENCES_DIR = Path(os.getenv("PREFERENCES_DIR", "/app/preferences"))
PREFERENCES_FILE = PREFERENCES_DIR / "preferences.json"


def _resolve_secret_key() -> str:
    env_key = os.getenv("FLASK_SECRET_KEY", "").strip()
    if env_key:
        return env_key
    secret_path = PREFERENCES_DIR / "flask_secret_key"
    try:
        if secret_path.exists():
            stored = secret_path.read_text(encoding="utf-8").strip()
            if stored:
                return stored
        PREFERENCES_DIR.mkdir(parents=True, exist_ok=True)
        generated = uuid.uuid4().hex + uuid.uuid4().hex
        secret_path.write_text(generated, encoding="utf-8")
        return generated
    except OSError:
        return uuid.uuid4().hex


app = Flask(__name__, template_folder=str(APP_DIR / "templates"))
app.secret_key = _resolve_secret_key()
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = os.getenv("SESSION_COOKIE_SECURE", "0") == "1"
BASIC_AUTH = os.getenv("BASIC_AUTH", "").strip()
# Optional comma-separated hostnames that custom Kodi servers may point at.
# Empty (default) keeps any reachable host allowed.
KODI_HOST_ALLOWLIST = tuple(
    entry.strip().lower()
    for entry in os.getenv("KODI_HOST_ALLOWLIST", "").split(",")
    if entry.strip()
)
CACHE_MAX_ART_FILES = int(os.getenv("CACHE_MAX_ART_FILES", "500"))
CACHE_MAX_ART_MB = int(os.getenv("CACHE_MAX_ART_MB", "1024"))

load_jobs = _state.load_jobs
load_lock = _state.load_lock
active_server_override = _state.active_server_override
LOAD_JOB_TTL_SECONDS = int(os.getenv("LOAD_JOB_TTL_SECONDS", "600"))
LOAD_JOB_STALE_SECONDS = int(os.getenv("LOAD_JOB_STALE_SECONDS", "1800"))
LOAD_JOB_MAX = int(os.getenv("LOAD_JOB_MAX", "50"))

nowplaying_cache = _state.nowplaying_cache
cache_lock = _state.cache_lock
cache_building = _state.cache_building
CACHE_POLLER_ENABLED = os.getenv("CACHE_POLLER_ENABLED", "1") != "0"
CACHE_POLLER_INTERVAL = float(os.getenv("CACHE_POLLER_INTERVAL", "12"))
THUMB_ART_PRIORITY = (
    "banner",
    "clearart",
    "landscape",
    "poster",
    "front",
    "season.poster",
    "thumbnail",
    "fanart",
)
CACHE_PROBE_FAIL_CLEAR_AFTER = int(os.getenv("CACHE_PROBE_FAIL_CLEAR_AFTER", "3"))
SERVER_FAIL_BACKOFF_AFTER = int(os.getenv("SERVER_FAIL_BACKOFF_AFTER", "3"))
SERVER_FAIL_BACKOFF_SECONDS = int(os.getenv("SERVER_FAIL_BACKOFF_SECONDS", "300"))
# The first pause after a host stops answering. It doubles on each further
# failed round up to SERVER_FAIL_BACKOFF_SECONDS. A host that is merely slow to
# boot is retried within seconds, while one that is genuinely gone still ends
# up polled at long, quiet intervals.
SERVER_FAIL_BACKOFF_INITIAL_SECONDS = int(os.getenv("SERVER_FAIL_BACKOFF_INITIAL_SECONDS", "15"))
SERVER_AUTH_BACKOFF_SECONDS = int(os.getenv("SERVER_AUTH_BACKOFF_SECONDS", "900"))
KODI_RPC_TIMEOUT = float(os.getenv("KODI_RPC_TIMEOUT", "5"))
KODI_CONNECT_TIMEOUT = float(os.getenv("KODI_CONNECT_TIMEOUT", "2"))
ART_DOWNLOAD_WORKERS = max(1, min(4, int(os.getenv("ART_DOWNLOAD_WORKERS", "2"))))

server_backoff = _state.server_backoff
server_backoff_lock = _state.server_backoff_lock

HEADERS = {"Content-Type": "application/json"}

MUSIC_COVER_KEYS = frozenset({
    "front", "back", "thumbnail", "poster", "discart", "cdart",
    "thumb", "frontcover", "backcover", "cover", "rear",
})

KODI_SERVERS = _state.KODI_SERVERS

ART_TYPES = [
    "poster", "front", "back", "fanart", "clearlogo", "clearart", "discart", "cdart",
    "banner", "landscape", "season.poster", "thumbnail",
]
ART_TMP_DIR = os.getenv("ART_TMP_DIR", "/app/tmp")
ART_TMP_PATH = Path(ART_TMP_DIR).resolve()
ART_FILE_PREFIX_LEN = 33
ART_CLEANUP_AGE_SECONDS = 6 * 60 * 60
ARTWORK_FILENAME_RE = re.compile(r"^(?:share_|cast_)?[0-9a-f]{32}_[A-Za-z0-9_.-]+\.jpg$")
STATIC_FILENAME_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
ART_TMP_PATH.mkdir(parents=True, exist_ok=True)

playback_poll_state = _state.playback_poll_state
playback_poll_lock = _state.playback_poll_lock
EPISODE_CHECK_INTERVAL = 10
POLL_IDLE_CONFIRMATIONS = int(os.getenv("POLL_IDLE_CONFIRMATIONS", "2"))
POLL_ERROR_IDLE_CONFIRMATIONS = int(os.getenv("POLL_ERROR_IDLE_CONFIRMATIONS", "6"))

art_download_locks = _state.art_download_locks
art_download_locks_guard = _state.art_download_locks_guard
cache_rebuild_lock = _state.cache_rebuild_lock

PREFERENCES_LOCK = _state.preferences_lock
PREFERENCE_ENUMS = {
    "blurPreference": {"blurred", "non-blurred"},
    "overlayPreference": {"enabled", "disabled"},
    "reducedMotionPreference": {"enabled", "disabled"},
    "lyricsPanelPreference": {"lyrics", "album", "artist"},
    "episodeTaglinePreference": {"enabled", "disabled"},
    "episodeSeasonPlotPreference": {"enabled", "disabled"},
    "episodeSeasonLabelPreference": {"named_only", "number_and_named"},
    "autoSwitchPlayingPreference": {"enabled", "disabled"},
}
PREFERENCE_RANGES = {
    "blurAmount": (0, 100),
    "overlayOpacity": (0, 100),
    "marqueeInterval": (5, 60),
    "fanartInterval": (5, 120),
    "fanartMinSizeKB": (0, 1000),
}

_cache_poller_started = False
_cache_poller_start_lock = threading.Lock()

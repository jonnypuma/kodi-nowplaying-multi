"""Shared process configuration and mutable state."""
from __future__ import annotations

import os
import re
import threading
import uuid
from pathlib import Path

from flask import Flask

from logging_config import configure_logging

configure_logging()

APP_DIR = Path(__file__).resolve().parent.parent
app = Flask(__name__, template_folder=str(APP_DIR / "templates"))
app.secret_key = os.getenv("FLASK_SECRET_KEY", uuid.uuid4().hex)
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024

load_jobs = {}
load_lock = threading.Lock()
active_server_override = threading.local()
LOAD_JOB_TTL_SECONDS = int(os.getenv("LOAD_JOB_TTL_SECONDS", "600"))
LOAD_JOB_STALE_SECONDS = int(os.getenv("LOAD_JOB_STALE_SECONDS", "1800"))
LOAD_JOB_MAX = int(os.getenv("LOAD_JOB_MAX", "50"))

nowplaying_cache = {}
cache_lock = threading.Lock()
cache_building = set()
CACHE_POLLER_ENABLED = os.getenv("CACHE_POLLER_ENABLED", "1") != "0"
CACHE_POLLER_INTERVAL = float(os.getenv("CACHE_POLLER_INTERVAL", "12"))
THUMB_ART_PRIORITY = ("poster", "front", "season.poster", "thumbnail", "fanart", "banner")
CACHE_PROBE_FAIL_CLEAR_AFTER = int(os.getenv("CACHE_PROBE_FAIL_CLEAR_AFTER", "3"))
SERVER_FAIL_BACKOFF_AFTER = int(os.getenv("SERVER_FAIL_BACKOFF_AFTER", "3"))
SERVER_FAIL_BACKOFF_SECONDS = int(os.getenv("SERVER_FAIL_BACKOFF_SECONDS", "300"))
KODI_RPC_TIMEOUT = float(os.getenv("KODI_RPC_TIMEOUT", "5"))

server_backoff = {}
server_backoff_lock = threading.Lock()

HEADERS = {"Content-Type": "application/json"}

MUSIC_COVER_KEYS = frozenset({
    "front", "back", "thumbnail", "poster", "discart", "cdart",
    "thumb", "frontcover", "backcover", "cover", "rear",
})

KODI_SERVERS = {}

ART_TYPES = [
    "poster", "front", "back", "fanart", "clearlogo", "clearart", "discart", "cdart",
    "banner", "season.poster", "thumbnail",
]
ART_TMP_DIR = os.getenv("ART_TMP_DIR", "/app/tmp")
ART_TMP_PATH = Path(ART_TMP_DIR).resolve()
ART_FILE_PREFIX_LEN = 33
ART_CLEANUP_AGE_SECONDS = 6 * 60 * 60
ARTWORK_FILENAME_RE = re.compile(r"^(?:share_)?[0-9a-f]{32}_[A-Za-z0-9_.-]+\.jpg$")
STATIC_FILENAME_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
ART_TMP_PATH.mkdir(parents=True, exist_ok=True)

playback_poll_state = {}
playback_poll_lock = threading.Lock()
EPISODE_CHECK_INTERVAL = 10
POLL_IDLE_CONFIRMATIONS = int(os.getenv("POLL_IDLE_CONFIRMATIONS", "2"))
# Consecutive /poll_playback RPC failures before treating as stopped (safety valve)
POLL_ERROR_IDLE_CONFIRMATIONS = int(os.getenv("POLL_ERROR_IDLE_CONFIRMATIONS", "6"))

art_download_locks = {}
art_download_locks_guard = threading.Lock()
cache_rebuild_lock = threading.Lock()

PREFERENCES_DIR = Path("/app/preferences")
PREFERENCES_FILE = PREFERENCES_DIR / "preferences.json"
PREFERENCES_LOCK = threading.Lock()
PREFERENCE_ENUMS = {
    "blurPreference": {"blurred", "non-blurred"},
    "overlayPreference": {"enabled", "disabled"},
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

"""Mutable process-wide runtime state.

Cache, load jobs, backoff, and the server registry live here so config.py
can stay limited to env knobs and Flask app setup. Gunicorn must still run
with a single worker: this state is in-process memory, not shared.
"""
from __future__ import annotations

import threading

load_jobs = {}
load_lock = threading.Lock()
active_server_override = threading.local()

nowplaying_cache = {}
cache_lock = threading.Lock()
cache_building = set()

server_backoff = {}
server_backoff_lock = threading.Lock()

KODI_SERVERS = {}

playback_poll_state = {}
playback_poll_lock = threading.Lock()

art_download_locks = {}
art_download_locks_guard = threading.Lock()
cache_rebuild_lock = threading.Lock()

cache_poller_started = False
cache_poller_start_lock = threading.Lock()
preferences_lock = threading.Lock()

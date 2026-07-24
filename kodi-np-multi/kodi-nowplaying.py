"""
Kodi Now Playing entrypoint (Docker CMD compatibility).

COMPAT surfaces re-exported for tests (app_module.*):
  app, requests, kodi_rpc, nowplaying_cache, KODI_SERVERS, ART_TMP_DIR,
  ARTWORK_FILENAME_RE, empty_share, classify_art_buckets, share_art_filename,
  is_artwork_filename, apply_share_reuse, ensure_share_file, primary_artist_id,
  store_playing_cache, clear_cache_playback, get_cache_entry, set_cache_entry,
  cleanup_old_artwork_files, make_playback_fingerprint, overview_from_cache,
  probe_playback_fingerprint, build_nowplaying_soft_update, parse_kodi_servers,
  server_display_name, get_active_server, get_server_overview_status,
  validate_preferences_update, prune_load_jobs, load_jobs, load_lock,
  playback_poll_state, server_backoff, _poll_state_for, POLL_IDLE_CONFIRMATIONS,
  SERVER_FAIL_BACKOFF_*, note_server_rpc_*, server_backoff_remaining,
  refresh_server_cache, resolve_safe_child, _format_overview_title,
  PREFERENCES_DIR, PREFERENCES_FILE, start_cache_poller
"""
from __future__ import annotations

import requests

from kodi_np import config as _config
from kodi_np.app import app, create_app
from kodi_np.art import (
    apply_share_reuse,
    classify_art_buckets,
    cleanup_old_artwork_files,
    empty_share,
    ensure_share_file,
    is_artwork_filename,
    primary_artist_id,
    resolve_safe_child,
    share_art_filename,
)
from kodi_np.cache import (
    _poll_state_for,
    clear_cache_playback,
    get_cache_entry,
    make_playback_fingerprint,
    overview_from_cache,
    probe_playback_fingerprint,
    refresh_server_cache,
    set_cache_entry,
    start_cache_poller,
    store_playing_cache,
)
from kodi_np.nowplaying import build_nowplaying_soft_update
from kodi_np.overview import _format_overview_title, get_server_overview_status
from kodi_np.preferences import (
    load_preferences,
    update_preferences,
    validate_preferences_update,
)
from kodi_np.rpc import (
    kodi_rpc,
    note_server_rpc_failure,
    note_server_rpc_success,
    server_backoff_remaining,
)
from kodi_np.servers import get_active_server, parse_kodi_servers, server_display_name
from kodi_np.util import prune_load_jobs

# Same object identity as config — mutations and .clear() work across modules
nowplaying_cache = _config.nowplaying_cache
KODI_SERVERS = _config.KODI_SERVERS
server_backoff = _config.server_backoff
playback_poll_state = _config.playback_poll_state
load_jobs = _config.load_jobs
load_lock = _config.load_lock
ARTWORK_FILENAME_RE = _config.ARTWORK_FILENAME_RE


def __getattr__(name: str):
    """Forward scalar state reads (ART_TMP_DIR, POLL_*, etc.) to kodi_np.config."""
    if hasattr(_config, name):
        return getattr(_config, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


if __name__ == "__main__":
    start_cache_poller()
    app.run(host="0.0.0.0", port=6001)

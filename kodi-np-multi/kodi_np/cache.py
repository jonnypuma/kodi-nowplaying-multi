"""Per-server now-playing cache and background poller."""
from __future__ import annotations

import hashlib
import logging
import os
import threading
import time
import uuid

from kodi_np import config as _c
from kodi_np.art import (
    cached_art_filenames,
    cleanup_old_artwork_files,
    empty_share,
    pick_fanart_filename,
    pick_thumb_art,
    pick_thumb_filename,
)
from kodi_np.rpc import (
    kodi_rpc,
    note_server_rpc_failure,
    note_server_rpc_success,
    server_backoff_remaining,
)
from kodi_np.servers import server_display_name
from kodi_np.overview import _format_overview_title

logger = logging.getLogger("kodi.nowplaying")

def make_playback_fingerprint(item):
    """Stable id for the currently playing item (changes when media changes)."""
    if not item:
        return None
    media_type = item.get("type") or "unknown"
    item_id = item.get("id") or item.get("songid") or item.get("movieid") or item.get("episodeid") or ""
    file_path = item.get("file") or ""
    title = item.get("title") or ""
    show = item.get("showtitle") or ""
    season = item.get("season")
    episode = item.get("episode")
    return f"{media_type}:{item_id}:{file_path}:{title}:{show}:{season}:{episode}"


def cache_session_id_for(server_id, fingerprint):
    return hashlib.md5(f"{server_id}:{fingerprint}".encode("utf-8")).hexdigest()


def get_cache_entry(server_id):
    with _c.cache_lock:
        entry = _c.nowplaying_cache.get(server_id)
        return dict(entry) if entry else None


def set_cache_entry(server_id, **fields):
    with _c.cache_lock:
        entry = _c.nowplaying_cache.get(server_id) or {}
        entry.update(fields)
        entry["updated_at"] = time.time()
        _c.nowplaying_cache[server_id] = entry
        return dict(entry)


def clear_cache_playback(server_id, status=None):
    """Drop HTML/art for a server that is idle/offline; keep lightweight status fields.

    Intentionally does not clear ``share`` so episode/music art+metadata can warm the
    next same-show / same-album / same-artist transition after a brief idle.
    """
    server = _c.KODI_SERVERS.get(server_id) or {}
    base = {
        "id": server_id,
        "host": server.get("host"),
        "ip": server.get("ip"),
        "label": server.get("label") or "",
        "name": server_display_name(server) if server else f"Server {server_id}",
        "connected": bool(status and status.get("connected")),
        "playing": False,
        "paused": False,
        "title": None,
        "media_type": None,
        "error": (status or {}).get("error"),
        "fingerprint": None,
        "html": None,
        "session_id": None,
        "art_files": [],
        "thumb_file": None,
        "thumb": None,
        "thumb_is_banner": False,
        "fanart_file": None,
        "fanart": None,
        "cache_ready": False,
    }
    if status:
        base["connected"] = bool(status.get("connected"))
        base["error"] = status.get("error")
    set_cache_entry(server_id, **base)


def store_playing_cache(server_id, payload, status=None):
    """Persist a successful now-playing build for instant serve + overview tiles."""
    server = _c.KODI_SERVERS.get(server_id) or {}
    downloaded_art = payload.get("downloaded_art") or {}
    art_files = [name for name in downloaded_art.values() if name]
    thumb_pick = pick_thumb_art(downloaded_art)
    thumb_file = thumb_pick[0] if thumb_pick else None
    thumb_key = thumb_pick[1] if thumb_pick else None
    fanart_file = pick_fanart_filename(downloaded_art)
    title = payload.get("title")
    media_type = payload.get("media_type")
    if status and status.get("title"):
        title = status.get("title")
    if status and status.get("media_type"):
        media_type = status.get("media_type")
    fields = dict(
        id=server_id,
        host=server.get("host"),
        ip=server.get("ip"),
        label=server.get("label") or "",
        name=server_display_name(server) if server else f"Server {server_id}",
        connected=True,
        playing=True,
        paused=bool(payload.get("paused")),
        title=title,
        media_type=media_type,
        error=None,
        fingerprint=payload.get("fingerprint"),
        html=payload.get("html"),
        session_id=payload.get("session_id"),
        art_files=art_files,
        thumb_file=thumb_file,
        thumb=f"/media/{thumb_file}" if thumb_file else None,
        thumb_is_banner=(thumb_key == "banner"),
        fanart_file=fanart_file,
        fanart=f"/media/{fanart_file}" if fanart_file else None,
        cache_ready=bool(payload.get("html")),
    )
    if "share" in payload and payload.get("share") is not None:
        fields["share"] = payload["share"]
    set_cache_entry(server_id, **fields)


def overview_from_cache(server_id):
    entry = get_cache_entry(server_id)
    if not entry:
        return None
    remaining = int(server_backoff_remaining(server_id))
    return {
        "id": server_id,
        "host": entry.get("host"),
        "ip": entry.get("ip"),
        "label": entry.get("label") or "",
        "name": entry.get("name") or "",
        "connected": bool(entry.get("connected")),
        "playing": bool(entry.get("playing")),
        "paused": bool(entry.get("paused")),
        "title": entry.get("title"),
        "media_type": entry.get("media_type"),
        "error": entry.get("error"),
        "thumb": entry.get("thumb"),
        "thumb_is_banner": bool(entry.get("thumb_is_banner")),
        "fanart": entry.get("fanart") if entry.get("thumb_is_banner") else None,
        "cache_ready": bool(entry.get("cache_ready") and entry.get("html")),
        "backoff_remaining": remaining,
    }


def probe_playback_fingerprint(server_id):
    """Cheap RPC to detect what (if anything) is playing on a server."""
    players_response = kodi_rpc("Player.GetActivePlayers", {}, server_id=server_id)
    if players_response is None:
        return {"connected": False, "playing": False, "fingerprint": None, "error": "Connection failed"}
    players = players_response.get("result") or []
    if not players:
        return {"connected": True, "playing": False, "fingerprint": None, "error": None, "paused": False}

    player_id = players[0].get("playerid")
    item_response = kodi_rpc(
        "Player.GetItem",
        {
            "playerid": player_id,
            "properties": ["title", "album", "artist", "showtitle", "season", "episode", "file"],
        },
        server_id=server_id,
    )
    props_response = kodi_rpc(
        "Player.GetProperties",
        {"playerid": player_id, "properties": ["speed"]},
        server_id=server_id,
    )
    item = {}
    if item_response and item_response.get("result"):
        item = item_response["result"].get("item") or {}
    speed = 0
    if props_response and props_response.get("result"):
        speed = props_response["result"].get("speed", 0)
    display_title, media_type = _format_overview_title(item)
    return {
        "connected": True,
        "playing": True,
        "paused": speed == 0,
        "fingerprint": make_playback_fingerprint(item),
        "title": display_title,
        "media_type": media_type,
        "error": None,
        "item": item,
    }


def _poll_state_for(server_id):
    with _c.playback_poll_lock:
        state = _c.playback_poll_state.get(server_id)
        if state is None:
            state = {
                "item_id": None,
                "last_check": 0.0,
                "idle_streak": 0,
                "error_streak": 0,
            }
            _c.playback_poll_state[server_id] = state
        return state

def refresh_server_cache(server_id):
    """Update cache for one server: status always; full HTML rebuild when media changes."""
    if server_id not in _c.KODI_SERVERS:
        return
    remaining = server_backoff_remaining(server_id)
    if remaining > 0:
        logger.debug("Skipping cache refresh for server %s (backoff %.0fs left)", server_id, remaining)
        return

    existing = get_cache_entry(server_id)
    try:
        probe = probe_playback_fingerprint(server_id)
    except Exception as e:
        logger.warning(f"Cache probe failed for server {server_id}: {e}")
        note_server_rpc_failure(server_id, e)
        fail_count = int((existing or {}).get("probe_fail_streak", 0)) + 1
        if existing and existing.get("html") and fail_count < _c.CACHE_PROBE_FAIL_CLEAR_AFTER:
            set_cache_entry(server_id, probe_fail_streak=fail_count, error=str(e))
        else:
            clear_cache_playback(server_id, {"connected": False, "error": str(e)})
        return

    if not probe.get("connected"):
        note_server_rpc_failure(server_id, probe.get("error") or "Connection failed")
        fail_count = int((existing or {}).get("probe_fail_streak", 0)) + 1
        if existing and existing.get("html") and fail_count < _c.CACHE_PROBE_FAIL_CLEAR_AFTER:
            set_cache_entry(
                server_id,
                connected=False,
                probe_fail_streak=fail_count,
                error=probe.get("error") or "Connection failed",
            )
        else:
            clear_cache_playback(server_id, probe)
        return

    note_server_rpc_success(server_id)

    if not probe.get("playing"):
        # Require a confirmed idle probe before wiping a warm cache (avoids blips while Kodi is busy)
        idle_streak = int((existing or {}).get("idle_streak", 0)) + 1
        if existing and existing.get("html") and idle_streak < _c.CACHE_PROBE_FAIL_CLEAR_AFTER:
            set_cache_entry(server_id, idle_streak=idle_streak, probe_fail_streak=0)
            return
        clear_cache_playback(server_id, probe)
        return

    fingerprint = probe.get("fingerprint")
    existing = get_cache_entry(server_id)
    if (
        existing
        and existing.get("fingerprint") == fingerprint
        and existing.get("html")
        and existing.get("cache_ready")
    ):
        set_cache_entry(
            server_id,
            connected=True,
            playing=True,
            paused=bool(probe.get("paused")),
            title=probe.get("title") or existing.get("title"),
            media_type=probe.get("media_type") or existing.get("media_type"),
            error=None,
            cache_ready=True,
            probe_fail_streak=0,
            idle_streak=0,
        )
        return

    with _c.cache_lock:
        if server_id in _c.cache_building:
            return
        _c.cache_building.add(server_id)

    # Only one full rebuild across all servers — art downloads hammer Kodi hard
    if not _c.cache_rebuild_lock.acquire(blocking=False):
        with _c.cache_lock:
            _c.cache_building.discard(server_id)
        return

    try:
        session_id = cache_session_id_for(server_id, fingerprint) if fingerprint else uuid.uuid4().hex
        _c.active_server_override.server_id = server_id
        try:
            from kodi_np.nowplaying import build_nowplaying_html
            with _c.app.app_context():
                payload = build_nowplaying_html(session_id=session_id, as_payload=True)
        finally:
            if hasattr(_c.active_server_override, "server_id"):
                del _c.active_server_override.server_id

        if not payload or payload.get("idle") or not payload.get("html"):
            # Don't wipe a previous good cache on a flaky rebuild
            if existing and existing.get("html") and existing.get("fingerprint") == fingerprint:
                set_cache_entry(server_id, probe_fail_streak=0, idle_streak=0)
            else:
                clear_cache_playback(server_id, {"connected": True, "error": None})
            return

        if probe.get("title"):
            payload["title"] = probe["title"]
        if probe.get("media_type"):
            payload["media_type"] = probe["media_type"]
        if fingerprint and not payload.get("fingerprint"):
            payload["fingerprint"] = fingerprint
        payload["paused"] = bool(probe.get("paused"))
        store_playing_cache(server_id, payload, status=probe)
        set_cache_entry(server_id, probe_fail_streak=0, idle_streak=0)
        logger.info(f"Cached now-playing for server {server_id}: {payload.get('title')}")
    except Exception as e:
        logger.warning(f"Cache rebuild failed for server {server_id}: {e}")
        # Keep prior HTML if we have it for this fingerprint
        if existing and existing.get("html") and existing.get("fingerprint") == fingerprint:
            set_cache_entry(server_id, error=f"Cache build failed: {e}", probe_fail_streak=0)
        else:
            set_cache_entry(
                server_id,
                connected=True,
                playing=True,
                paused=bool(probe.get("paused")),
                title=probe.get("title"),
                media_type=probe.get("media_type"),
                error=f"Cache build failed: {e}",
                cache_ready=False,
                html=None,
            )
    finally:
        _c.cache_rebuild_lock.release()
        with _c.cache_lock:
            _c.cache_building.discard(server_id)


def _cache_poller_loop():
    # Stagger first run slightly so Flask finishes starting
    time.sleep(2)
    while True:
        try:
            for server_id in list(_c.KODI_SERVERS.keys()):
                try:
                    refresh_server_cache(server_id)
                except Exception as e:
                    logger.warning(f"Cache poller error for server {server_id}: {e}")
        except Exception as e:
            logger.warning(f"Cache poller loop error: {e}")
        time.sleep(_c.CACHE_POLLER_INTERVAL)


def start_cache_poller():
    # state: _c._cache_poller_started
    if not _c.CACHE_POLLER_ENABLED:
        return
    with _c._cache_poller_start_lock:
        if _c._cache_poller_started:
            return
        # Avoid duplicate pollers when the reloader spawns a parent watcher process
        if os.environ.get("WERKZEUG_RUN_MAIN") == "false":
            return
        _c._cache_poller_started = True
        thread = threading.Thread(target=_cache_poller_loop, daemon=True, name="np-cache-poller")
        thread.start()
        logger.info(
            f"Started now-playing cache poller (interval={_c.CACHE_POLLER_INTERVAL}s, servers={len(_c.KODI_SERVERS)})"
        )

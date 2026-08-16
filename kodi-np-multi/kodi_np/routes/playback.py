"""Playback polling, load jobs, soft-update, and /nowplaying."""
from __future__ import annotations

import logging
import threading
import time
import uuid

from flask import Blueprint, has_request_context, jsonify, request, session

from kodi_np import config as _c
from kodi_np.cache import (
    _poll_state_for,
    get_cache_entry,
    probe_playback_fingerprint,
)
from kodi_np.nowplaying import (
    build_nowplaying_html,
    build_nowplaying_soft_update,
    run_nowplaying_job,
)
from kodi_np.rpc import kodi_rpc
from kodi_np.servers import get_active_server
from kodi_np.util import kodi_time_to_seconds, prune_load_jobs

logger = logging.getLogger("kodi.nowplaying")

bp = Blueprint("playback", __name__)


@bp.route("/poll_playback")
def poll_playback():
    """Poll active server playback. Transient RPC failures must not look like idle."""
    active = get_active_server()
    server_id = active.get("id") if active else None
    if server_id is None:
        return jsonify({"playing": False, "error": True})

    state = _poll_state_for(server_id)

    def _rpc(method, params=None):
        # Interactive poll always attempts RPC (background cache poller still respects backoff).
        return kodi_rpc(method, params, bypass_backoff=True)

    try:
        players = _rpc("Player.GetActivePlayers")
        if players is None:
            with _c.playback_poll_lock:
                state["error_streak"] = int(state.get("error_streak", 0)) + 1
                error_streak = state["error_streak"]
                known_item = state.get("item_id")
            if error_streak >= _c.POLL_ERROR_IDLE_CONFIRMATIONS and known_item:
                logger.info(
                    "Poll playback - prolonged RPC failures for server %s; holding page (streak %s)",
                    server_id,
                    error_streak,
                )
                return jsonify({
                    "playing": True,
                    "error": True,
                    "error_idle": True,
                    "item_id": known_item,
                    "error_streak": error_streak,
                })
            return jsonify({
                "playing": True if known_item else None,
                "error": True,
                "item_id": known_item,
                "error_streak": error_streak,
            })

        if players.get("result"):
            with _c.playback_poll_lock:
                state["idle_streak"] = 0
                state["error_streak"] = 0

            current_time = time.time()
            current_item_id = state.get("item_id")

            # Always resolve the playing item on interactive polls so song/artist
            # changes are detected promptly (frontend already polls ~every 4s).
            try:
                active_players = players.get("result") or []
                if active_players:
                    player_id = active_players[0].get("playerid")
                    item = _rpc(
                        "Player.GetItem",
                        {
                            "playerid": player_id,
                            "properties": ["title", "album", "artist", "showtitle", "season", "episode", "file"],
                        },
                    )
                    if item and item.get("result") and item.get("result", {}).get("item"):
                        current_item = item.get("result", {}).get("item", {})
                        item_id = current_item.get("id")
                        if current_item.get("type") == "song" and item_id:
                            current_item_id = f"song_{item_id}"
                        elif current_item.get("type") == "episode" and item_id:
                            current_item_id = f"episode_{item_id}"
                        elif current_item.get("type") == "movie" and item_id:
                            current_item_id = f"movie_{item_id}"
                        else:
                            current_item_id = f"other_{current_item.get('title', 'unknown')}"

                        with _c.playback_poll_lock:
                            state["item_id"] = current_item_id
                            state["last_check"] = current_time
                    elif item is None:
                        return jsonify({
                            "playing": True if state.get("item_id") else None,
                            "error": True,
                            "item_id": state.get("item_id"),
                        })
            except Exception as e:
                logger.debug(f"Failed to check episode: {e}")
                return jsonify({
                    "playing": True if state.get("item_id") else None,
                    "error": True,
                    "item_id": state.get("item_id"),
                })

            active_players = players.get("result", [])
            is_paused = False
            current_audio_lang = ""
            current_subtitle_lang = ""
            if active_players:
                player_id = active_players[0].get("playerid")
                progress_response = _rpc("Player.GetProperties", {
                    "playerid": player_id,
                    "properties": ["speed"]
                })
                if progress_response is None:
                    return jsonify({
                        "playing": True,
                        "error": True,
                        "item_id": state.get("item_id") or current_item_id or "episode_unknown",
                    })
                speed = 0
                if progress_response.get("result"):
                    speed = progress_response.get("result", {}).get("speed", 0)
                is_paused = speed == 0

                try:
                    language_response = _rpc("XBMC.GetInfoLabels", {
                        "labels": ["VideoPlayer.AudioLanguage", "VideoPlayer.SubtitlesLanguage"]
                    })
                    if language_response and language_response.get("result"):
                        result = language_response.get("result", {})
                        current_audio_lang = result.get("VideoPlayer.AudioLanguage", "")[:3].upper()
                        current_subtitle_lang = result.get("VideoPlayer.SubtitlesLanguage", "")[:3].upper()
                        language_normalization = {
                            'GER': 'DEU', 'ENG': 'ENG', 'FRE': 'FRA', 'SPA': 'SPA',
                            'ITA': 'ITA', 'POR': 'POR', 'RUS': 'RUS', 'JPN': 'JPN',
                            'KOR': 'KOR', 'CHI': 'CHI',
                        }
                        current_audio_lang = language_normalization.get(current_audio_lang, current_audio_lang)
                        current_subtitle_lang = language_normalization.get(current_subtitle_lang, current_subtitle_lang)
                except Exception as e:
                    logger.debug(f"Failed to get current languages: {e}")

            item_id = state.get("item_id") or current_item_id or "episode_unknown"
            return jsonify({
                "playing": True,
                "paused": is_paused,
                "item_id": item_id,
                "item_type": "episode",
                "current_audio_lang": current_audio_lang,
                "current_subtitle_lang": current_subtitle_lang,
            })

        # Empty player list — confirm idle across several polls before reporting stopped
        with _c.playback_poll_lock:
            state["idle_streak"] = int(state.get("idle_streak", 0)) + 1
            state["error_streak"] = 0
            idle_streak = state["idle_streak"]
            known_item = state.get("item_id")

        if idle_streak < _c.POLL_IDLE_CONFIRMATIONS and known_item:
            logger.debug(
                "Poll playback - empty players (streak %s/%s), holding playing state for server %s",
                idle_streak,
                _c.POLL_IDLE_CONFIRMATIONS,
                server_id,
            )
            return jsonify({
                "playing": True,
                "paused": False,
                "item_id": known_item,
                "item_type": "episode",
                "transient_idle": True,
            })

        with _c.playback_poll_lock:
            state["item_id"] = None
            state["last_check"] = 0.0
            state["idle_streak"] = 0
        logger.info(
            "Poll playback - confirmed idle (playing: false) for server %s",
            server_id,
        )
        return jsonify({"playing": False})
    except Exception as e:
        logger.error(f"Poll playback failed: {e}")
        return jsonify({
            "playing": True if state.get("item_id") else None,
            "error": True,
            "item_id": state.get("item_id"),
        })

@bp.route("/start-nowplaying-load")
def start_nowplaying_load():
    prune_load_jobs()
    job_id = uuid.uuid4().hex
    server_id = session.get('active_server_id', 1) if has_request_context() else 1
    cached = get_cache_entry(server_id)
    # Only serve cache when it matches what Kodi is actually playing now.
    # Otherwise a track/artist change returns the previous page until the poller catches up.
    if cached and cached.get("html") and cached.get("playing") and cached.get("cache_ready"):
        probe = None
        try:
            probe = probe_playback_fingerprint(server_id, bypass_backoff=True)
        except Exception as e:
            logger.debug("Cache-hit probe failed for server %s: %s", server_id, e)
        cache_fp = cached.get("fingerprint")
        live_fp = (probe or {}).get("fingerprint")
        if (
            probe
            and probe.get("playing")
            and cache_fp
            and live_fp
            and cache_fp == live_fp
        ):
            with _c.load_lock:
                _c.load_jobs[job_id] = {
                    "status": "done",
                    "progress": 100,
                    "message": "Cached",
                    "created_at": time.time(),
                    "updated_at": time.time(),
                    "html": cached["html"],
                    "server_id": server_id,
                    "cache_hit": True,
                }
            return jsonify({"job_id": job_id, "cache_hit": True})
        logger.info(
            "Skipping stale cache for server %s (cache_fp=%s live_fp=%s playing=%s)",
            server_id,
            cache_fp,
            live_fp,
            (probe or {}).get("playing"),
        )

    with _c.load_lock:
        _c.load_jobs[job_id] = {
            "status": "pending",
            "progress": 0,
            "message": "Starting",
            "created_at": time.time(),
            "updated_at": time.time(),
            "html": None,
            "server_id": server_id
        }
    thread = threading.Thread(target=run_nowplaying_job, args=(job_id,), daemon=True)
    thread.start()
    return jsonify({"job_id": job_id, "cache_hit": False})

@bp.route("/nowplaying-load-status/<job_id>")
def nowplaying_load_status(job_id):
    prune_load_jobs()
    with _c.load_lock:
        job = _c.load_jobs.get(job_id)
        if not job:
            return jsonify({"status": "missing", "progress": 0, "message": "Not found"}), 404
        return jsonify({
            "status": job["status"],
            "progress": job["progress"],
            "message": job.get("message", "")
        })

@bp.route("/nowplaying-content/<job_id>")
def nowplaying_content(job_id):
    if job_id == "fallback":
        return "<h1>Loading failed. Please refresh.</h1>", 503
    with _c.load_lock:
        job = _c.load_jobs.get(job_id)
        if not job:
            return "<h1>Loading job not found.</h1>", 404
        if job.get("status") == "consumed":
            return "<h1>Content already consumed.</h1>", 410
        if job["status"] != "done" or not job.get("html"):
            return "<h1>Still loading...</h1>", 202
        html_content = job["html"]
        # Free large HTML payload immediately after first successful fetch
        job["html"] = None
        job["status"] = "consumed"
        job["updated_at"] = time.time()
    prune_load_jobs()
    return html_content

@bp.route("/api/nowplaying-soft-update")
def api_nowplaying_soft_update():
    """Return a soft-update delta when identity is shared; else soft=false for full reload."""
    def _opt_int(raw):
        if raw is None or raw == "" or raw == "null" or raw == "undefined":
            return None
        try:
            return int(raw)
        except (TypeError, ValueError):
            return None

    prev = {
        "media_type": (request.args.get("prev_type") or "").strip().lower(),
        "tvshow_id": _opt_int(request.args.get("prev_tvshow_id")),
        "season": _opt_int(request.args.get("prev_season")),
        "album_id": _opt_int(request.args.get("prev_album_id")),
        "artist_id": _opt_int(request.args.get("prev_artist_id")),
        "item_id": request.args.get("prev_item_id") or "",
    }
    try:
        payload = build_nowplaying_soft_update(prev)
    except Exception as e:
        logger.warning("Soft update failed: %s", e)
        return jsonify({"soft": False, "reason": "error", "error": str(e)})
    return jsonify(payload)

@bp.route("/nowplaying")
def now_playing():
    if request.args.get("json") == "1":
        active_response = kodi_rpc("Player.GetActivePlayers", bypass_backoff=True)
        active = active_response.get("result") if active_response else None
        if not active:
            return jsonify({"elapsed": 0, "duration": 0, "paused": True})
        player_id = active[0]["playerid"]
        progress_response = kodi_rpc("Player.GetProperties", {
            "playerid": player_id,
            "properties": ["time", "totaltime", "speed"]
        }, bypass_backoff=True)
        progress = progress_response.get("result") if progress_response else {}
        t = progress.get("time", {})
        d = progress.get("totaltime", {})
        speed = progress.get("speed", 0)
        return jsonify({
            "elapsed": kodi_time_to_seconds(t),
            "duration": kodi_time_to_seconds(d),
            "paused": speed == 0
        })
    return build_nowplaying_html()

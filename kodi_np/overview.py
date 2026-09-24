"""Overview status helpers."""
from __future__ import annotations

import logging

from kodi_np import config as _c
from kodi_np.rpc import kodi_rpc, server_backoff_remaining, server_backoff_status
from kodi_np.servers import server_display_name

logger = logging.getLogger("kodi.nowplaying")

def _format_overview_title(item):
    """Build a short display title for overview tiles."""
    media_type = item.get("type") or "unknown"
    title = item.get("title") or "Unknown"
    if media_type == "episode":
        show = item.get("showtitle") or title
        season = item.get("season")
        episode = item.get("episode")
        if season is not None and episode is not None:
            ep_label = f"S{int(season):02d}E{int(episode):02d}"
            if title and title != show:
                return f"{show} · {ep_label} · {title}", "episode"
            return f"{show} · {ep_label}", "episode"
        return show, "episode"
    if media_type == "song":
        artist = item.get("artist")
        if isinstance(artist, list):
            artist = ", ".join(artist) if artist else ""
        artist = artist or "Unknown artist"
        return f"{artist} · {title}", "song"
    if media_type == "movie":
        return title, "movie"
    return title, media_type if media_type != "unknown" else "other"

def get_server_overview_status(server_id, bypass_backoff=False):
    """Return lightweight playback status for one configured Kodi server."""
    server = _c.KODI_SERVERS.get(server_id)
    if not server:
        return {
            "id": server_id,
            "connected": False,
            "playing": False,
            "error": "Server not found",
        }

    status = {
        "id": server_id,
        "host": server["host"],
        "ip": server["ip"],
        "label": server.get("label") or "",
        "name": server_display_name(server),
        "connected": False,
        "playing": False,
        "paused": False,
        "title": None,
        "media_type": None,
        "error": None,
        "auth_failed": False,
    }

    try:
        players_response = kodi_rpc(
            "Player.GetActivePlayers",
            {},
            server_id=server_id,
            bypass_backoff=bypass_backoff,
        )
        if players_response is None:
            backoff = server_backoff_status(server_id)
            status["auth_failed"] = bool(backoff["auth_failed"])
            status["error"] = "Authentication failed" if status["auth_failed"] else "Connection failed"
            return status

        status["connected"] = True
        players = players_response.get("result") or []
        if not players:
            return status

        player_id = players[0].get("playerid")
        item_response = kodi_rpc(
            "Player.GetItem",
            {
                "playerid": player_id,
                "properties": ["title", "album", "artist", "showtitle", "season", "episode"],
            },
            server_id=server_id,
            bypass_backoff=bypass_backoff,
        )
        props_response = kodi_rpc(
            "Player.GetProperties",
            {"playerid": player_id, "properties": ["speed"]},
            server_id=server_id,
            bypass_backoff=bypass_backoff,
        )

        item = {}
        if item_response and item_response.get("result"):
            item = item_response["result"].get("item") or {}

        speed = 0
        if props_response and props_response.get("result"):
            speed = props_response["result"].get("speed", 0)

        display_title, media_type = _format_overview_title(item)
        status["playing"] = True
        status["paused"] = speed == 0
        status["title"] = display_title
        status["media_type"] = media_type
        return status
    except Exception as e:
        status["error"] = str(e)
        return status


def overview_fast_snapshot(server_id):
    """Instant tile data from warm cache or static config (no Kodi RPC)."""
    from kodi_np.cache import overview_from_cache
    from kodi_np.rpc import server_backoff_remaining

    cached = overview_from_cache(server_id)
    if cached is not None:
        out = dict(cached)
        out["loading"] = False
        if int(out.get("backoff_remaining") or 0) > 0:
            out["connected"] = False
            out["playing"] = False
            out["paused"] = False
        return out

    server = _c.KODI_SERVERS.get(server_id)
    if not server:
        return None

    remaining = int(server_backoff_remaining(server_id))
    backoff = server_backoff_status(server_id)
    return {
        "id": server_id,
        "host": server["host"],
        "ip": server["ip"],
        "label": server.get("label") or "",
        "name": server_display_name(server),
        "connected": False,
        "playing": False,
        "paused": False,
        "title": None,
        "media_type": None,
        "error": None,
        "auth_failed": bool(backoff["auth_failed"]),
        "thumb": None,
        "thumb_is_banner": False,
        "fanart": None,
        "cache_ready": False,
        "backoff_remaining": remaining,
        "loading": remaining <= 0,
    }


def server_is_cold(server_id) -> bool:
    """True when we hold no cache for this server, i.e. never reached it yet.

    A cold server has nothing to report but a guess, so a backoff started by one
    failed attempt would otherwise be shown as a confident "offline".
    """
    from kodi_np.cache import overview_from_cache

    if overview_from_cache(server_id) is not None:
        return False
    return not server_backoff_status(server_id)["auth_failed"]


def overview_live_status(server_id, allow_cold_probe=False):
    """Live Kodi probe merged with warm cache fields for one overview tile.

    ``allow_cold_probe`` lets an explicit page load look past the backoff for a
    server that has never answered. Without it a host that was still booting
    when the poller first tried stays "offline" until the backoff expires, even
    though it is reachable now.
    """
    from kodi_np.cache import overview_from_cache

    remaining = int(server_backoff_remaining(server_id))
    cold_probe = remaining > 0 and allow_cold_probe and server_is_cold(server_id)
    if remaining > 0 and not cold_probe:
        cached = overview_from_cache(server_id)
        if cached is not None:
            out = dict(cached)
        else:
            out = overview_fast_snapshot(server_id) or {
                "id": server_id,
                "connected": False,
                "playing": False,
                "error": "Connection failed",
            }
            out = dict(out)
        out["connected"] = False
        out["playing"] = False
        out["paused"] = False
        out["loading"] = False
        out["backoff_remaining"] = remaining
        backoff = server_backoff_status(server_id)
        out["auth_failed"] = bool(backoff["auth_failed"])
        if backoff["auth_failed"]:
            out["error"] = "Authentication failed"
        elif not out.get("error"):
            out["error"] = "Connection failed"
        return out

    live = get_server_overview_status(server_id, bypass_backoff=cold_probe)
    live["backoff_remaining"] = int(server_backoff_remaining(server_id))
    cached = overview_from_cache(server_id)
    if cached is not None:
        cached = dict(cached)
        cached["connected"] = live["connected"]
        cached["auth_failed"] = live["auth_failed"]
        cached["error"] = live["error"]
        cached["backoff_remaining"] = live["backoff_remaining"]
        if not live["connected"]:
            cached["playing"] = False
            cached["paused"] = False
            cached["cache_ready"] = False
            if live.get("title"):
                cached["title"] = live["title"]
        elif live.get("playing"):
            cached["playing"] = True
            cached["paused"] = live.get("paused", False)
            if live.get("title"):
                cached["title"] = live["title"]
            if live.get("media_type"):
                cached["media_type"] = live["media_type"]
        else:
            cached["playing"] = False
            cached["paused"] = False
            cached["cache_ready"] = False
            cached["title"] = live.get("title") or "Nothing playing"
            cached["media_type"] = live.get("media_type")
            cached["thumb"] = None
            cached["fanart"] = None
            cached["thumb_is_banner"] = False
        cached["loading"] = False
        return cached

    live["thumb"] = None
    live["cache_ready"] = False
    live.setdefault("auth_failed", live.get("error") == "Authentication failed")
    live["loading"] = False
    return live

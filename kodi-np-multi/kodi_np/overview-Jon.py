"""Overview status helpers."""
from __future__ import annotations

import logging

from kodi_np import config as _c
from kodi_np.rpc import kodi_rpc, server_backoff_status
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

def get_server_overview_status(server_id):
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
    }

    try:
        backoff = server_backoff_status(server_id)
        if backoff["auth_failed"]:
            status["error"] = "Authentication failed"
            return status
        players_response = kodi_rpc("Player.GetActivePlayers", {}, server_id=server_id)
        if players_response is None:
            status["error"] = "Connection failed"
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
        status["playing"] = True
        status["paused"] = speed == 0
        status["title"] = display_title
        status["media_type"] = media_type
        return status
    except Exception as e:
        status["error"] = str(e)
        return status

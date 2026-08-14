"""Kodi playlist / up-next helper."""
from __future__ import annotations

import logging

from kodi_np.rpc import kodi_rpc

logger = logging.getLogger("kodi.nowplaying")


def _item_label(item: dict) -> str:
    if not isinstance(item, dict):
        return ""
    title = (item.get("title") or item.get("label") or "").strip()
    show = (item.get("showtitle") or "").strip()
    artist = item.get("artist")
    if isinstance(artist, list):
        artist = ", ".join(str(a) for a in artist if a)
    artist = (artist or "").strip()
    album = (item.get("album") or "").strip()
    season = item.get("season")
    episode = item.get("episode")
    if show and title:
        if season not in (None, "", -1) and episode not in (None, "", -1):
            return f"{show} · S{int(season):02d}E{int(episode):02d} · {title}"
        return f"{show} · {title}"
    if artist and title:
        return f"{artist} — {title}" + (f" ({album})" if album else "")
    return title or album or show or ""


def get_up_next_label(player_id, current_item=None) -> str:
    """Return a short label for the next playlist item, or empty."""
    if player_id is None:
        return ""
    try:
        props = kodi_rpc("Player.GetProperties", {
            "playerid": player_id,
            "properties": ["playlistid", "position"],
        })
        result = (props or {}).get("result") or {}
        playlist_id = result.get("playlistid")
        position = result.get("position")
        if playlist_id is None or position is None:
            return ""
        listing = kodi_rpc("Playlist.GetItems", {
            "playlistid": playlist_id,
            "properties": [
                "title", "artist", "album", "showtitle", "season", "episode", "file",
            ],
        })
        items = ((listing or {}).get("result") or {}).get("items") or []
        nxt = position + 1
        if nxt < 0 or nxt >= len(items):
            return ""
        label = _item_label(items[nxt])
        if not label:
            return ""
        current_title = ""
        if isinstance(current_item, dict):
            current_title = (current_item.get("title") or "").strip()
        if current_title and label.casefold() == current_title.casefold():
            return ""
        return label
    except Exception as e:
        logger.debug("Failed to resolve up-next item: %s", e)
        return ""

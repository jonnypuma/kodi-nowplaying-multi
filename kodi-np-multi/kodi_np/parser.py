"""Media type parser — routes playback to movie / episode / music handlers."""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_PVR_TYPES = {"channel", "tvchannel", "radio", "broadcast"}
_VIDEO_FALLBACK_TYPES = {"unknown", "video", "trailer", "plugin", "picture"}


def infer_playback_type(item):
    """Return movie, episode, song, musicvideo, channel, video, or unknown."""
    if not isinstance(item, dict):
        return "unknown"
    declared = (item.get("type") or "").strip().lower()
    if declared in {"movie", "episode", "song"}:
        return declared
    if declared == "musicvideo":
        return "musicvideo"
    if declared in _PVR_TYPES or item.get("channelid") or item.get("channel"):
        return "channel"
    if item.get("showtitle") and item.get("episode") is not None:
        return "episode"
    if item.get("album") and item.get("artist"):
        return "song"
    if declared in _VIDEO_FALLBACK_TYPES:
        return "video" if (item.get("title") or item.get("label")) else "unknown"
    if item.get("title") and not item.get("showtitle") and declared not in {"unknown", ""}:
        return "movie"
    if item.get("title") or item.get("label") or item.get("file"):
        return "video"
    return "unknown"


def get_media_handler(playback_type):
    """Return the handler module for a playback type."""
    if playback_type == "episode":
        from kodi_np import episode_nowplaying
        return episode_nowplaying
    if playback_type == "song":
        from kodi_np import music_nowplaying
        return music_nowplaying
    from kodi_np import movie_nowplaying
    return movie_nowplaying


def route_media_display(item, session_id, downloaded_art, progress_data, details):
    playback_type = infer_playback_type(item)
    logger.debug("Parser - Playback type: %s", playback_type)
    if isinstance(details, dict):
        details["display_kind"] = playback_type
    handler = get_media_handler(playback_type)
    logger.debug("Parser - Handler: %s", handler)
    return handler.generate_html(item, session_id, downloaded_art, progress_data, details)

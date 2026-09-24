"""Shared video stream / badge helpers for movie, episode, and generic video."""
from __future__ import annotations

import json
import logging
from html import escape
from pathlib import Path

from kodi_np.codecs import format_audio_codec, format_video_codec

logger = logging.getLogger(__name__)

LANGUAGE_NORMALIZATION = {
    "GER": "DEU",
    "ENG": "ENG",
    "FRE": "FRA",
    "SPA": "SPA",
    "ITA": "ITA",
    "POR": "POR",
    "RUS": "RUS",
    "JPN": "JPN",
    "KOR": "KOR",
    "CHI": "CHI",
}

FANART_KEYS = tuple(["fanart"] + [f"fanart{i}" for i in range(1, 10)])


def html_escape(value):
    return escape(str(value), quote=True) if value is not None else ""


def format_playback_time(seconds: int, reference_duration: int | None = None) -> str:
    duration = reference_duration if reference_duration is not None else seconds
    seconds = int(seconds or 0)
    duration = int(duration or 0)
    if duration < 3600:
        return f"{seconds // 60:02d}:{seconds % 60:02d}"
    return f"{seconds // 3600:02d}:{(seconds // 60) % 60:02d}:{seconds % 60:02d}"


def fanart_variant_urls(downloaded_art: dict | None) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()
    art = downloaded_art or {}
    for key in FANART_KEYS:
        name = art.get(key)
        if name and name not in seen:
            urls.append(f"/media/{name}")
            seen.add(name)
    for key, value in art.items():
        if not value or not str(key).startswith("extrafanart"):
            continue
        if value in seen:
            continue
        urls.append(f"/media/{value}")
        seen.add(value)
    return urls


def fanart_slides_html(fanart_variants, empty: str = "") -> str:
    """Background slideshow markup; the first slide starts active."""
    if not fanart_variants:
        return empty
    return "".join(
        f'<div class="fanart-slide{" active" if i == 0 else ""}" '
        f"style=\"background-image: url('{fanart}')\"></div>"
        for i, fanart in enumerate(fanart_variants)
    )


def fanart_pending_json(details, session_id) -> str:
    """Payload the page uses to lazily pull fanart that was deferred at build time."""
    pending_items = []
    art_session_id = session_id
    if isinstance(details, dict):
        pending_items = list(details.get("pending_fanarts") or [])
        art_session_id = details.get("art_session_id") or session_id
    return json.dumps({"session_id": art_session_id, "items": pending_items})


def normalize_lang(code: str) -> str:
    raw = (code or "")[:3].upper()
    if not raw:
        return ""
    return LANGUAGE_NORMALIZATION.get(raw, raw)


def language_sets(audio_info, subtitle_info, enhanced_video_info) -> dict:
    enhanced = enhanced_video_info or {}
    all_audio = sorted({
        normalize_lang(a.get("language", ""))
        for a in (audio_info or [])
        if a.get("language")
    } - {""})
    all_subs = sorted({
        normalize_lang(s.get("language", ""))
        for s in (subtitle_info or [])
        if s.get("language")
    } - {""})
    audio_label = enhanced.get("VideoPlayer.AudioLanguage", "")
    sub_label = enhanced.get("VideoPlayer.SubtitlesLanguage", "")
    current_audio = normalize_lang(audio_label) if audio_label else (all_audio[0] if all_audio else "N/A")
    current_sub = normalize_lang(sub_label) if sub_label else (all_subs[0] if all_subs else "N/A")
    if current_audio and current_audio != "N/A" and current_audio not in all_audio:
        all_audio = sorted(set(all_audio) | {current_audio})
    if current_sub and current_sub != "N/A" and current_sub not in all_subs:
        all_subs = sorted(set(all_subs) | {current_sub})
    return {
        "current_audio": current_audio or "N/A",
        "current_subtitle": current_sub or "N/A",
        "all_audio": all_audio,
        "all_subtitles": all_subs,
    }


def video_dimensions(enhanced_video_info, video_info) -> tuple[int, int]:
    """Pixel size of the playing video, preferring live InfoLabels.

    Kodi reports these as strings and sometimes as a literal ``"0"``, which is
    truthy, so the InfoLabel is parsed before deciding whether to fall back to
    the library's streamdetails.
    """
    enhanced = enhanced_video_info or {}
    video_info = video_info or {}

    def as_int(value) -> int:
        try:
            return int(str(value or 0).replace(",", ""))
        except (ValueError, TypeError):
            return 0

    width = as_int(enhanced.get("Player.Process(VideoWidth)")) or as_int(video_info.get("width"))
    height = as_int(enhanced.get("Player.Process(VideoHeight)")) or as_int(video_info.get("height"))
    return width, height


def resolution_label(width, height) -> str:
    try:
        height = int(str(height or 0).replace(",", ""))
    except (ValueError, TypeError):
        height = 0
    try:
        width = int(str(width or 0).replace(",", ""))
    except (ValueError, TypeError):
        width = 0
    if width >= 3840 or height >= 2160:
        return "4K"
    if height >= 1080:
        return "1080p"
    if height >= 720:
        return "720p"
    return ""


def aspect_ratio_label(enhanced_video_info) -> str:
    enhanced = enhanced_video_info or {}
    aspect_ratio = enhanced.get("VideoPlayer.VideoAspectLabel", "") or ""
    if aspect_ratio:
        return aspect_ratio
    raw = enhanced.get("VideoPlayer.VideoAspect")
    try:
        aspect_numeric = float(raw or 0)
    except (TypeError, ValueError):
        return ""
    if aspect_numeric <= 0:
        return ""
    if 1.77 <= aspect_numeric <= 1.78:
        return "16:9"
    if 2.35 <= aspect_numeric <= 2.40:
        return "21:9"
    if 1.33 <= aspect_numeric <= 1.37:
        return "4:3"
    if 1.85 <= aspect_numeric <= 1.90:
        return "1.85:1"
    if 2.20 <= aspect_numeric <= 2.25:
        return "2.20:1"
    return f"{aspect_numeric:.2f}:1"


def container_label(enhanced_video_info, item) -> str:
    enhanced = enhanced_video_info or {}
    container_format = (enhanced.get("VideoPlayer.Container") or "").upper()
    if container_format:
        return container_format
    file_path = str((item or {}).get("file") or "")
    suffix = Path(file_path).suffix.lower().lstrip(".")
    return suffix.upper() if suffix else ""


def codecs_and_channels(enhanced_video_info, video_info, audio_info) -> dict:
    enhanced = enhanced_video_info or {}
    video_info = video_info or {}
    audio_info = audio_info or []
    video_codec = format_video_codec(
        enhanced.get("VideoPlayer.VideoCodec", video_info.get("codec", "Unknown"))
    )
    audio_codec = format_audio_codec(
        enhanced.get(
            "VideoPlayer.AudioCodec",
            audio_info[0].get("codec", "Unknown") if audio_info else "Unknown",
        )
    )
    channels = audio_info[0].get("channels", 0) if audio_info else 0
    return {"video_codec": video_codec, "audio_codec": audio_codec, "channels": channels}


def fetch_player_streams(existing_audio=None, existing_subs=None, server_id=None) -> dict:
    """Live InfoLabels + stream lists from the active Kodi player.

    ``server_id`` pins the calls to one server; ``None`` targets the active one.
    """
    from kodi_np.rpc import kodi_rpc

    audio_info = list(existing_audio or [])
    subtitle_info = list(existing_subs or [])
    enhanced_video_info = {}
    player_id = 1
    try:
        active_players_response = kodi_rpc("Player.GetActivePlayers", {}, server_id=server_id)
        if active_players_response and active_players_response.get("result"):
            active_players = active_players_response.get("result") or []
            if active_players:
                player_id = active_players[0].get("playerid", 1)
    except Exception as e:
        logger.debug("Failed to get active player ID, using default 1: %s", e)

    try:
        infolabels_response = kodi_rpc("XBMC.GetInfoLabels", {
            "labels": [
                "VideoPlayer.VideoAspect",
                "VideoPlayer.VideoAspectLabel",
                "VideoPlayer.VideoCodec",
                "VideoPlayer.Container",
                "VideoPlayer.AudioCodec",
                "Player.Process(VideoHeight)",
                "Player.Process(VideoWidth)",
                "VideoPlayer.AudioLanguage",
                "VideoPlayer.SubtitlesLanguage",
                "VideoPlayer.Year",
            ]
        }, server_id=server_id)
        if infolabels_response and infolabels_response.get("result"):
            enhanced_video_info = infolabels_response.get("result") or {}
    except Exception as e:
        logger.debug("Failed to get enhanced video info: %s", e)

    try:
        audio_streams_response = kodi_rpc("Player.GetProperties", {
            "playerid": player_id,
            "properties": ["audiostreams"],
        }, server_id=server_id)
        if audio_streams_response and audio_streams_response.get("result"):
            audio_streams = audio_streams_response.get("result", {}).get("audiostreams") or []
            converted = []
            for stream in audio_streams:
                if isinstance(stream, dict) and stream.get("language"):
                    converted.append({
                        "language": stream.get("language", ""),
                        "name": stream.get("name", ""),
                        "index": stream.get("index", 0),
                        "codec": stream.get("codec", ""),
                        "channels": stream.get("channels", 0),
                    })
            if converted:
                audio_info = converted
    except Exception as e:
        logger.debug("Failed to get audio streams: %s", e)

    try:
        subtitle_streams_response = kodi_rpc("Player.GetProperties", {
            "playerid": player_id,
            "properties": ["subtitles"],
        }, server_id=server_id)
        if subtitle_streams_response and subtitle_streams_response.get("result"):
            subtitle_streams = subtitle_streams_response.get("result", {}).get("subtitles") or []
            converted = []
            for stream in subtitle_streams:
                if isinstance(stream, dict) and stream.get("language"):
                    converted.append({
                        "language": stream.get("language", ""),
                        "name": stream.get("name", ""),
                        "index": stream.get("index", 0),
                    })
            if converted:
                subtitle_info = converted
    except Exception as e:
        logger.debug("Failed to get subtitle streams: %s", e)

    return {
        "player_id": player_id,
        "enhanced_video_info": enhanced_video_info,
        "audio_info": audio_info,
        "subtitle_info": subtitle_info,
    }


def up_next_html(details) -> str:
    label = ""
    if isinstance(details, dict):
        label = (details.get("up_next_label") or "").strip()
    if not label:
        return ""
    return (
        f'<div class="up-next" id="up-next">'
        f'<span class="up-next-label">Up next</span> '
        f'<span class="up-next-title">{html_escape(label)}</span></div>'
    )


def kind_badge_html(kind: str) -> str:
    mapping = {
        "channel": ("Live", "live-badge"),
        "musicvideo": ("Music video", ""),
        "video": ("Video", ""),
        "unknown": ("Playing", ""),
    }
    if kind not in mapping:
        return ""
    text, extra = mapping[kind]
    cls = f"badge {extra}".strip()
    return f'<span class="{cls}">{html_escape(text)}</span>'

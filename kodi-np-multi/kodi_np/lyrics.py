"""Synced lyrics helpers (Kodi tags + LRCLib)."""
from __future__ import annotations

import json
import logging
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

logger = logging.getLogger("kodi.nowplaying")

_LRC_LINE_RE = re.compile(
    r"\[(\d{1,2}):(\d{1,2})(?:\.(\d{1,3}))?\]\s*(.*)$"
)
_LRCLIB_UA = "KodiNowPlaying/3.0.2 (https://github.com/)"


def parse_lrc(lrc_text: str | None) -> list[dict[str, Any]]:
    """Parse LRC text into [{time, text}, ...]."""
    if not lrc_text or not str(lrc_text).strip():
        return []
    lines: list[dict[str, Any]] = []
    for raw in str(lrc_text).replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = raw.strip()
        if not line or not line.startswith("["):
            continue
        match = _LRC_LINE_RE.match(line)
        if not match:
            continue
        minutes = int(match.group(1))
        seconds = int(match.group(2))
        frac = match.group(3) or "0"
        # Normalize fractional seconds (1→0.1, 2→0.01-ish via padding)
        if len(frac) == 1:
            millis = int(frac) * 100
        elif len(frac) == 2:
            millis = int(frac) * 10
        else:
            millis = int(frac[:3])
        text = (match.group(4) or "").strip()
        total = minutes * 60 + seconds + millis / 1000.0
        lines.append({"time": total, "text": text})
    lines.sort(key=lambda item: item["time"])
    return lines


def plain_lyrics_lines(text: str | None) -> list[dict[str, Any]]:
    """Convert unsynced lyrics into scrollable lines (time=None)."""
    if not text or not str(text).strip():
        return []
    out = []
    for raw in str(text).replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = raw.strip()
        if line:
            out.append({"time": None, "text": line})
    return out


def lyrics_from_kodi_field(raw: str | None) -> dict[str, Any]:
    """Prefer synced LRC from Kodi; otherwise plain lines."""
    synced = parse_lrc(raw)
    if synced:
        return {"lines": synced, "synced": True, "source": "kodi"}
    plain = plain_lyrics_lines(raw)
    if plain:
        return {"lines": plain, "synced": False, "source": "kodi"}
    return {"lines": [], "synced": False, "source": None}


def _http_json(url: str) -> Any | None:
    req = urllib.request.Request(url, headers={"User-Agent": _LRCLIB_UA})
    try:
        with urllib.request.urlopen(req, timeout=8) as response:
            return json.loads(response.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        logger.warning("LRCLib HTTP error %s: %s", url.split("?", 1)[0], exc)
        return None
    except Exception as exc:
        logger.warning("LRCLib fetch failed %s: %s", url.split("?", 1)[0], exc)
        return None


def _payload_to_lyrics(payload: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    synced_raw = payload.get("syncedLyrics") or ""
    synced = parse_lrc(synced_raw)
    if synced:
        return {
            "lines": synced,
            "synced": True,
            "source": "lrclib",
            "lrclib_id": payload.get("id"),
            "lrclib_name": payload.get("name") or payload.get("trackName"),
            "lrclib_artist": payload.get("artistName"),
            "lrclib_album": payload.get("albumName"),
            "lrclib_duration": payload.get("duration"),
        }
    plain_raw = payload.get("plainLyrics") or ""
    plain = plain_lyrics_lines(plain_raw)
    if plain:
        return {
            "lines": plain,
            "synced": False,
            "source": "lrclib",
            "lrclib_id": payload.get("id"),
            "lrclib_name": payload.get("name") or payload.get("trackName"),
            "lrclib_artist": payload.get("artistName"),
            "lrclib_album": payload.get("albumName"),
            "lrclib_duration": payload.get("duration"),
        }
    return None


def _norm(value: str | None) -> str:
    return re.sub(r"\s+", " ", (value or "").casefold().strip())


def _score_lrclib_hit(
    item: dict[str, Any],
    artist: str,
    title: str,
    duration: float | int | None,
    album: str | None,
) -> float:
    """Higher is better. Heavily prefer duration + exact title/artist."""
    if not isinstance(item, dict):
        return -1e9
    score = 0.0
    hit_title = _norm(item.get("trackName") or item.get("name"))
    hit_artist = _norm(item.get("artistName"))
    hit_album = _norm(item.get("albumName"))
    want_title = _norm(title)
    want_artist = _norm(artist)
    want_album = _norm(album)

    if hit_title == want_title:
        score += 40
    elif want_title and want_title in hit_title:
        score += 20
    elif hit_title and hit_title in want_title:
        score += 15
    else:
        score -= 30

    if hit_artist == want_artist:
        score += 30
    elif want_artist and want_artist in hit_artist:
        score += 15
    elif hit_artist and hit_artist in want_artist:
        score += 10
    else:
        score -= 20

    if want_album and hit_album:
        if hit_album == want_album:
            score += 15
        elif want_album in hit_album or hit_album in want_album:
            score += 6

    hit_dur = item.get("duration")
    if duration and float(duration) > 0 and hit_dur is not None:
        try:
            delta = abs(float(hit_dur) - float(duration))
        except (TypeError, ValueError):
            delta = 999
        if delta <= 2:
            score += 35
        elif delta <= 5:
            score += 20
        elif delta <= 12:
            score += 5
        else:
            score -= 40

    if item.get("syncedLyrics"):
        score += 5
    return score


def fetch_lrclib(
    artist: str,
    title: str,
    duration: float | int | None = None,
    album: str | None = None,
) -> dict[str, Any]:
    """Fetch synced (or plain) lyrics from lrclib.net. No API key required."""
    artist = (artist or "").strip()
    title = (title or "").strip()
    album = (album or "").strip() or None
    if not artist or not title:
        return {"lines": [], "synced": False, "source": None}

    params: dict[str, Any] = {
        "artist_name": artist,
        "track_name": title,
    }
    if duration and float(duration) > 0:
        params["duration"] = int(round(float(duration)))
    if album:
        params["album_name"] = album

    get_url = "https://lrclib.net/api/get?" + urllib.parse.urlencode(params)
    payload = _http_json(get_url)
    best: dict[str, Any] | None = None
    best_score = -1e9

    if isinstance(payload, dict):
        score = _score_lrclib_hit(payload, artist, title, duration, album)
        # Accept direct /get only when it looks like the right track
        if score >= 40:
            parsed = _payload_to_lyrics(payload)
            if parsed:
                best = parsed
                best_score = score

    # Always consult search as a safety net when /get is weak or missing
    search_params = {
        "artist_name": artist,
        "track_name": title,
    }
    search_url = "https://lrclib.net/api/search?" + urllib.parse.urlencode(search_params)
    results = _http_json(search_url)
    if isinstance(results, list):
        for item in results[:12]:
            if not isinstance(item, dict):
                continue
            score = _score_lrclib_hit(item, artist, title, duration, album)
            if score <= best_score:
                continue
            # Need enough confidence to avoid wrong-song lyrics
            if score < 45:
                continue
            parsed = _payload_to_lyrics(item)
            if not parsed and item.get("id") is not None:
                detail = _http_json(f"https://lrclib.net/api/get/{item['id']}")
                parsed = _payload_to_lyrics(detail) if isinstance(detail, dict) else None
            if parsed:
                best = parsed
                best_score = score

    if best:
        logger.debug(
            "LRCLib chose id=%s name=%r artist=%r score=%.1f for %s – %s",
            best.get("lrclib_id"),
            best.get("lrclib_name"),
            best.get("lrclib_artist"),
            best_score,
            artist,
            title,
        )
        return best

    logger.debug("LRCLib: no confident match for %s – %s", artist, title)
    return {"lines": [], "synced": False, "source": None}


def resolve_lyrics(
    artist: str,
    title: str,
    duration: float | int | None = None,
    kodi_lyrics: str | None = None,
    album: str | None = None,
) -> dict[str, Any]:
    """Resolve lyrics: Kodi first (especially if synced), then LRCLib."""
    local = lyrics_from_kodi_field(kodi_lyrics)
    if local.get("synced") and local.get("lines"):
        logger.info(
            "Lyrics source=kodi synced=true lines=%d for %s – %s",
            len(local["lines"]),
            artist,
            title,
        )
        return local
    remote = fetch_lrclib(artist, title, duration, album=album)
    if remote.get("lines"):
        logger.info(
            "Lyrics source=lrclib synced=%s lines=%d match=%r / %r for %s – %s",
            bool(remote.get("synced")),
            len(remote["lines"]),
            remote.get("lrclib_artist"),
            remote.get("lrclib_name"),
            artist,
            title,
        )
        return remote
    if local.get("lines"):
        logger.info(
            "Lyrics source=kodi synced=false lines=%d for %s – %s",
            len(local["lines"]),
            artist,
            title,
        )
        return local
    logger.info("Lyrics source=none for %s – %s", artist, title)
    return {"lines": [], "synced": False, "source": None, "artist": artist, "title": title}

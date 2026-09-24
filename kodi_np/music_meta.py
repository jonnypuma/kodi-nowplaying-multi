"""External album/artist metadata fallbacks (TheAudioDB + Wikipedia).

Used only when Kodi library fields are empty. Results are meant to be stored in
the per-server share cache so same-album / same-artist soft updates reuse them.
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

logger = logging.getLogger("kodi.nowplaying")

_AUDIODB_KEY = os.getenv("AUDIODB_API_KEY", "123").strip() or "123"
_AUDIODB_BASE = f"https://www.theaudiodb.com/api/v1/json/{_AUDIODB_KEY}"
_UA = "KodiNowPlaying/3.0.2 (album/artist metadata; +https://github.com/)"
_CACHE_TTL = int(os.getenv("MUSIC_META_CACHE_TTL", str(6 * 60 * 60)))
_cache_lock = threading.Lock()
_cache: dict[str, tuple[float, dict[str, Any]]] = {}


def _norm(value: str | None) -> str:
    return re.sub(r"\s+", " ", (value or "").strip())


def _cache_get(key: str) -> dict[str, Any] | None:
    now = time.time()
    with _cache_lock:
        hit = _cache.get(key)
        if not hit:
            return None
        expires, payload = hit
        if expires < now:
            _cache.pop(key, None)
            return None
        return dict(payload)


def _cache_set(key: str, payload: dict[str, Any]) -> None:
    with _cache_lock:
        _cache[key] = (time.time() + _CACHE_TTL, dict(payload))


def _http_json(url: str, timeout: float = 6.0) -> Any | None:
    req = urllib.request.Request(url, headers={"User-Agent": _UA, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as exc:
        logger.debug("Music meta HTTP %s for %s", exc.code, url.split("?", 1)[0])
        return None
    except Exception as exc:
        logger.debug("Music meta fetch failed for %s: %s", url.split("?", 1)[0], exc)
        return None


def _pick_text(*values: Any) -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _wikipedia_summary(title: str) -> dict[str, Any] | None:
    title = _norm(title)
    if not title:
        return None
    url = "https://en.wikipedia.org/api/rest_v1/page/summary/" + urllib.parse.quote(title.replace(" ", "_"))
    payload = _http_json(url)
    if not isinstance(payload, dict):
        return None
    if payload.get("type") == "disambiguation":
        return None
    extract = _pick_text(payload.get("extract"))
    if not extract or len(extract) < 40:
        return None
    return {"text": extract, "source": "wikipedia", "title": payload.get("title") or title}


def fetch_artist_biography(artist: str) -> dict[str, Any] | None:
    """Return {text, source, born?, genre?} for an artist name."""
    artist = _norm(artist)
    if not artist or artist.lower() in {"unknown artist", "various artists", "various"}:
        return None
    cache_key = "artist:" + artist.casefold()
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached or None

    result: dict[str, Any] | None = None
    search = _http_json(_AUDIODB_BASE + "/search.php?" + urllib.parse.urlencode({"s": artist}))
    artists = (search or {}).get("artists") if isinstance(search, dict) else None
    if isinstance(artists, list) and artists:
        row = artists[0] if isinstance(artists[0], dict) else {}
        bio = _pick_text(
            row.get("strBiographyEN"),
            row.get("strBiography"),
            row.get("strBiographyDE"),
            row.get("strBiographyFR"),
        )
        if bio:
            result = {
                "text": bio,
                "source": "theaudiodb",
                "born": _pick_text(row.get("intBornYear"), row.get("strBorn")),
                "genre": _pick_text(row.get("strGenre")),
                "style": _pick_text(row.get("strStyle")),
                "name": _pick_text(row.get("strArtist")) or artist,
            }

    if result is None:
        wiki = _wikipedia_summary(artist)
        if wiki:
            result = wiki

    _cache_set(cache_key, result or {})
    if result:
        logger.info("Artist bio source=%s for %s (%d chars)", result.get("source"), artist, len(result.get("text") or ""))
    else:
        logger.debug("No external artist bio for %s", artist)
    return result


def fetch_album_description(artist: str, album: str) -> dict[str, Any] | None:
    """Return {text, source} for an album."""
    artist = _norm(artist)
    album = _norm(album)
    if not album:
        return None
    cache_key = "album:" + artist.casefold() + "|" + album.casefold()
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached or None

    result: dict[str, Any] | None = None
    params = {"s": artist or album, "a": album}
    search = _http_json(_AUDIODB_BASE + "/searchalbum.php?" + urllib.parse.urlencode(params))
    albums = (search or {}).get("album") if isinstance(search, dict) else None
    if isinstance(albums, list) and albums:
        row = albums[0] if isinstance(albums[0], dict) else {}
        desc = _pick_text(
            row.get("strDescriptionEN"),
            row.get("strDescription"),
            row.get("strDescriptionDE"),
            row.get("strDescriptionFR"),
        )
        if desc:
            result = {
                "text": desc,
                "source": "theaudiodb",
                "title": _pick_text(row.get("strAlbum")) or album,
                "year": row.get("intYearReleased"),
                "label": _pick_text(row.get("strLabel")),
            }

    if result is None:
        # Wikipedia album pages are often "Album (Artist album)" or "Album (album)"
        candidates = []
        if artist:
            candidates.append(f"{album} ({artist} album)")
        candidates.append(f"{album} (album)")
        candidates.append(album)
        for candidate in candidates:
            wiki = _wikipedia_summary(candidate)
            if wiki:
                result = wiki
                break

    _cache_set(cache_key, result or {})
    if result:
        logger.info(
            "Album description source=%s for %s – %s (%d chars)",
            result.get("source"),
            artist,
            album,
            len(result.get("text") or ""),
        )
    else:
        logger.debug("No external album description for %s – %s", artist, album)
    return result


def enrich_artist_details(artist_details: dict[str, Any] | None, artist_name: str) -> dict[str, Any]:
    """Fill empty Kodi artist description from TheAudioDB/Wikipedia."""
    details = dict(artist_details or {})
    if _pick_text(details.get("description")):
        return details
    fetched = fetch_artist_biography(artist_name or details.get("label") or details.get("artist") or "")
    if not fetched:
        return details
    details["description"] = fetched["text"]
    details["description_source"] = fetched.get("source")
    if fetched.get("born") and not _pick_text(details.get("born")):
        details["born"] = str(fetched["born"])
    if fetched.get("genre") and not details.get("genre"):
        details["genre"] = [fetched["genre"]]
    if fetched.get("style") and not details.get("style"):
        details["style"] = [fetched["style"]]
    return details


def enrich_album_details(
    album_details: dict[str, Any] | None,
    artist_name: str,
    album_title: str | None = None,
) -> dict[str, Any]:
    """Fill empty Kodi album description from TheAudioDB/Wikipedia."""
    details = dict(album_details or {})
    if _pick_text(details.get("description")):
        return details
    title = _norm(album_title) or _norm(details.get("title") or details.get("label"))
    fetched = fetch_album_description(artist_name, title)
    if not fetched:
        return details
    details["description"] = fetched["text"]
    details["description_source"] = fetched.get("source")
    if fetched.get("label") and not _pick_text(details.get("albumlabel")):
        details["albumlabel"] = fetched["label"]
    return details

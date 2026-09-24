"""Lyrics, music-meta, lazy cast-thumb, and progressive fanart API routes."""
from __future__ import annotations

import logging

from flask import Blueprint, jsonify, request

from kodi_np.art import download_cast_thumbnail, download_fanart_variant, empty_share
from kodi_np.cache import get_cache_entry, set_cache_entry
from kodi_np.lyrics import resolve_lyrics
from kodi_np.music_meta import fetch_album_description, fetch_artist_biography
from kodi_np.servers import get_active_server

logger = logging.getLogger("kodi.nowplaying")

bp = Blueprint("extras_api", __name__)


@bp.route("/api/lyrics", methods=["GET", "POST"])
def api_lyrics():
    """Resolve synced/plain lyrics for the current track (Kodi field + LRCLib)."""
    if request.method == "POST":
        payload = request.get_json(silent=True) or {}
        artist = str(payload.get("artist") or "").strip()
        title = str(payload.get("title") or "").strip()
        album = str(payload.get("album") or "").strip()
        kodi_lyrics = str(payload.get("kodi_lyrics") or "")
        duration_raw = payload.get("duration")
    else:
        artist = (request.args.get("artist") or "").strip()
        title = (request.args.get("title") or "").strip()
        album = (request.args.get("album") or "").strip()
        kodi_lyrics = request.args.get("kodi_lyrics") or ""
        duration_raw = request.args.get("duration")
    duration = None
    try:
        if duration_raw is not None and str(duration_raw).strip() != "":
            duration = float(duration_raw)
    except (TypeError, ValueError):
        duration = None

    if not artist or not title:
        return jsonify({
            "artist": artist,
            "title": title,
            "album": album,
            "lines": [],
            "synced": False,
            "source": None,
            "has_lyrics": False,
        })

    result = resolve_lyrics(artist, title, duration, kodi_lyrics, album=album)
    lines = result.get("lines") or []
    return jsonify({
        "artist": artist,
        "title": title,
        "album": album,
        "lines": lines,
        "synced": bool(result.get("synced")),
        "source": result.get("source"),
        "has_lyrics": bool(lines),
        "lrclib_name": result.get("lrclib_name"),
        "lrclib_artist": result.get("lrclib_artist"),
    })


def _opt_int(raw):
    if raw is None or raw == "" or raw == "null" or raw == "undefined":
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


@bp.route("/api/music-meta", methods=["POST"])
def api_music_meta():
    """Lazy album/artist text from TheAudioDB/Wikipedia after the page is shown."""
    payload = request.get_json(silent=True) or {}
    artist = str(payload.get("artist") or "").strip()
    album = str(payload.get("album") or "").strip()
    need_album = bool(payload.get("need_album"))
    need_artist = bool(payload.get("need_artist"))
    album_id = _opt_int(payload.get("album_id"))
    artist_id = _opt_int(payload.get("artist_id"))

    out = {
        "artist": artist,
        "album": album,
        "album_description": None,
        "artist_bio": None,
        "artist_born": None,
        "album_source": None,
        "artist_source": None,
    }
    if not need_album and not need_artist:
        return jsonify(out)

    if need_album and album:
        fetched = fetch_album_description(artist, album)
        if fetched and fetched.get("text"):
            out["album_description"] = fetched["text"]
            out["album_source"] = fetched.get("source")

    if need_artist and artist:
        fetched = fetch_artist_biography(artist)
        if fetched and fetched.get("text"):
            out["artist_bio"] = fetched["text"]
            out["artist_source"] = fetched.get("source")
            if fetched.get("born"):
                out["artist_born"] = str(fetched["born"])

    # Persist into share cache so soft updates reuse without another remote hit
    server = get_active_server()
    server_id = server.get("id") if server else None
    if server_id is not None and (out["album_description"] or out["artist_bio"]):
        try:
            entry = get_cache_entry(server_id) or {}
            share = dict(entry.get("share") or empty_share())
            if out["album_description"] and album_id is not None:
                if share.get("album_id") in (None, album_id):
                    details = dict(share.get("album_details") or {})
                    if not (details.get("description") or "").strip():
                        details["description"] = out["album_description"]
                        details["description_source"] = out["album_source"]
                        share["album_details"] = details
                        share["album_id"] = album_id
            if out["artist_bio"] and artist_id is not None:
                if share.get("artist_id") in (None, artist_id):
                    details = dict(share.get("artist_details") or {})
                    if not (details.get("description") or "").strip():
                        details["description"] = out["artist_bio"]
                        details["description_source"] = out["artist_source"]
                        if out["artist_born"] and not (details.get("born") or "").strip():
                            details["born"] = out["artist_born"]
                        share["artist_details"] = details
                        share["artist_id"] = artist_id
            set_cache_entry(server_id, share=share)
        except Exception as exc:
            logger.debug("music-meta share cache update skipped: %s", exc)

    return jsonify(out)


@bp.route("/api/fanart", methods=["POST"])
def api_fanart():
    """Download one deferred fanart after page load. Body: {path, key, session_id}."""
    payload = request.get_json(silent=True) or {}
    path = payload.get("path") or ""
    key = payload.get("key") or ""
    session_id = payload.get("session_id") or ""
    if not isinstance(path, str) or not path.strip():
        return jsonify({"success": False, "error": "Missing path"}), 400
    if not isinstance(key, str) or not key.strip():
        return jsonify({"success": False, "error": "Missing key"}), 400
    if not isinstance(session_id, str) or not session_id.strip():
        return jsonify({"success": False, "error": "Missing session_id"}), 400
    if len(path) > 2000 or len(key) > 120 or len(session_id) > 64:
        return jsonify({"success": False, "error": "Input too long"}), 400

    server = get_active_server()
    server_id = server.get("id") if server else None
    filename = download_fanart_variant(
        path.strip(), key.strip(), session_id.strip(), server_id=server_id
    )
    if not filename:
        return jsonify({"success": False, "url": None, "key": key}), 404
    return jsonify({"success": True, "url": f"/media/{filename}", "key": key})


@bp.route("/api/cast-thumb", methods=["POST"])
def api_cast_thumb():
    """Download one cast thumbnail after page load. Body: {\"path\": \"image://...\"}."""
    payload = request.get_json(silent=True) or {}
    path = payload.get("path") or ""
    if not isinstance(path, str) or not path.strip():
        return jsonify({"success": False, "error": "Missing path"}), 400
    if len(path) > 2000:
        return jsonify({"success": False, "error": "Path too long"}), 400

    server = get_active_server()
    server_id = server.get("id") if server else None
    filename = download_cast_thumbnail(path.strip(), server_id=server_id)
    if not filename:
        return jsonify({"success": False, "url": None}), 404
    return jsonify({"success": True, "url": f"/media/{filename}"})

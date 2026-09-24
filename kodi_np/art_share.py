"""Share-file identity, scoping, and reuse across episodes of a show or an artist's songs."""
from __future__ import annotations

import hashlib
import logging
import os
import re
import shutil


from kodi_np import config as _c
from kodi_np.art_paths import normalize_art_source

logger = logging.getLogger("kodi.nowplaying")



def empty_share():
    return {
        "tvshow_id": None,
        "season": None,
        "tvshow_meta": None,
        "album_id": None,
        "album_details": None,
        "artist_id": None,
        "artist_details": None,
        "art_sources": {"tvshow": {}, "season": {}, "album": {}, "artist": {}},
        "art_files": {"tvshow": {}, "season": {}, "album": {}, "artist": {}},
    }



def primary_artist_id(artistid):
    if artistid is None:
        return None
    if isinstance(artistid, list):
        return artistid[0] if artistid else None
    return artistid



def share_identity_hash(server_id, scope, identity):
    return hashlib.md5(f"{server_id}:{scope}:{identity}".encode("utf-8")).hexdigest()



def share_art_filename(server_id, scope, identity, art_key):
    safe_key = re.sub(r"[^A-Za-z0-9_.-]", "_", str(art_key))
    return f"share_{share_identity_hash(server_id, scope, identity)}_{safe_key}.jpg"



def season_share_identity(tvshow_id, season):
    if tvshow_id is None or season is None:
        return None
    return f"{tvshow_id}:{season}"



def classify_art_buckets(raw_art):
    """Split item['art'] into provenance buckets (clean key -> source path)."""
    buckets = {"tvshow": {}, "season": {}, "album": {}, "artist": {}, "item": {}}
    if not isinstance(raw_art, dict):
        return buckets
    for key, value in raw_art.items():
        if not value:
            continue
        if key.startswith("tvshow."):
            buckets["tvshow"][key.replace("tvshow.", "", 1)] = value
        elif key == "season.poster" or key.startswith("season."):
            buckets["season"][key] = value
        elif key.startswith("album."):
            clean = key.replace("album.", "", 1)
            if clean == "thumb":
                clean = "thumbnail"
            buckets["album"][clean] = value
        elif key.startswith("artist."):
            buckets["artist"][key.replace("artist.", "", 1)] = value
        elif key.startswith("albumartist."):
            buckets["artist"][key.replace("albumartist.", "", 1)] = value
        else:
            buckets["item"][key] = value
    return buckets



def build_key_scope_map(buckets, media_type):
    """Map clean art keys to share scope (or None for session-only)."""
    key_scope = {}
    if media_type == "episode":
        for key in buckets.get("item") or {}:
            key_scope[key] = None
        for key in buckets.get("season") or {}:
            key_scope[key] = "season"
        for key in buckets.get("tvshow") or {}:
            key_scope[key] = "tvshow"
    elif media_type == "song":
        for key in buckets.get("item") or {}:
            key_scope[key] = None
        for key in buckets.get("album") or {}:
            key_scope[key] = "album"
        for key in buckets.get("artist") or {}:
            if key in _c.MUSIC_COVER_KEYS:
                continue
            key_scope[key] = "artist"
    return key_scope



def share_scope_matches(prior_share, scope, identity):
    if not prior_share or identity is None:
        return False
    if scope == "tvshow":
        return prior_share.get("tvshow_id") == identity
    if scope == "season":
        return season_share_identity(prior_share.get("tvshow_id"), prior_share.get("season")) == str(identity)
    if scope == "album":
        return prior_share.get("album_id") == identity
    if scope == "artist":
        return prior_share.get("artist_id") == identity
    return False



def scope_identity(scope, tvshow_id=None, season=None, album_id=None, artist_id=None):
    if scope == "tvshow":
        return tvshow_id
    if scope == "season":
        return season_share_identity(tvshow_id, season)
    if scope == "album":
        return album_id
    if scope == "artist":
        return artist_id
    return None



def apply_share_reuse(server_id, scope, identity, new_sources, prior_share, downloaded):
    """Reuse share files for a bucket when identity matches and sources are unchanged."""
    if not share_scope_matches(prior_share, scope, identity):
        return {}
    prior_files = (prior_share.get("art_files") or {}).get(scope) or {}
    prior_sources = (prior_share.get("art_sources") or {}).get(scope) or {}
    reused = {}
    new_sources = new_sources or {}
    # Reuse all prior keys that still exist; invalidate when source URL changed
    keys = set(prior_files) | set(new_sources)
    for art_key in keys:
        filename = prior_files.get(art_key)
        if not filename:
            continue
        local_path = os.path.join(_c.ART_TMP_DIR, filename)
        if not (os.path.exists(local_path) and os.path.getsize(local_path) > 0):
            continue
        if art_key in new_sources:
            new_src = normalize_art_source(new_sources[art_key])
            old_src = normalize_art_source(prior_sources.get(art_key))
            if new_src and old_src and new_src != old_src:
                continue
        downloaded[art_key] = filename
        reused[art_key] = filename
        logger.debug("Reusing shared %s art %s -> %s", scope, art_key, filename)
    return reused



def ensure_share_file(server_id, scope, identity, art_key, source_path, session_filename=None):
    """Ensure art lives at the share path; copy/link from session file if needed. Returns share filename."""
    if identity is None:
        return session_filename
    share_name = share_art_filename(server_id, scope, identity, art_key)
    share_path = os.path.join(_c.ART_TMP_DIR, share_name)
    if os.path.exists(share_path) and os.path.getsize(share_path) > 0:
        return share_name
    if session_filename:
        src_path = os.path.join(_c.ART_TMP_DIR, session_filename)
        if os.path.exists(src_path) and os.path.getsize(src_path) > 0:
            try:
                if os.path.abspath(src_path) != os.path.abspath(share_path):
                    try:
                        os.link(src_path, share_path)
                    except OSError:
                        shutil.copy2(src_path, share_path)
                return share_name
            except Exception as e:
                logger.debug("Failed to promote %s to share file: %s", art_key, e)
    return session_filename

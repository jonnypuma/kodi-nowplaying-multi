"""Choosing which downloaded artwork to show first."""
from __future__ import annotations

import logging
import os


from kodi_np import config as _c

logger = logging.getLogger("kodi.nowplaying")



def select_primary_fanart_key(media_type, fanart_variants: dict, downloaded: dict) -> str | None:
    """Pick which fanart key should be on the critical path for first paint."""
    if not fanart_variants and not any(
        k.startswith(("fanart", "extrafanart")) for k in downloaded
    ):
        return None
    if media_type == "song":
        for key in fanart_variants:
            if key.startswith("extrafanart"):
                return key
        for key in ("fanart", "fanart1", "fanart2", "fanart3", "fanart4",
                    "fanart5", "fanart6", "fanart7", "fanart8", "fanart9"):
            if key in fanart_variants or key in downloaded:
                return key
        for key in fanart_variants:
            return key
        return None
    # movie / episode / other: prefer main fanart
    if "fanart" in fanart_variants or "fanart" in downloaded:
        return "fanart"
    for key in ("fanart1", "fanart2", "fanart3", "fanart4", "fanart5",
                "fanart6", "fanart7", "fanart8", "fanart9"):
        if key in fanart_variants or key in downloaded:
            return key
    for key in fanart_variants:
        if key.startswith("extrafanart"):
            return key
    for key in fanart_variants:
        return key
    return None



def collect_extrafanart_variants(extrafanart_files) -> dict:
    """Map an ``extrafanart`` directory listing to fanart variant keys.

    Non-image entries (subfolders, .nfo files) are skipped outright. They must
    never fall through and reuse the previous entry's filename, which would
    register a duplicate variant under the wrong key.
    """
    variants = {}
    for entry in extrafanart_files or []:
        if not isinstance(entry, dict):
            continue
        path = entry.get("file") or ""
        if not path or not path.lower().endswith((".jpg", ".jpeg", ".png")):
            continue
        filename = os.path.basename(path)
        if filename.lower() == "fanart.jpg":
            variants["extrafanart_main"] = path
            continue
        stem = filename.lower()
        for suffix in (".jpg", ".jpeg", ".png"):
            stem = stem.replace(suffix, "")
        variants[f"extrafanart_{stem}"] = path
    return variants



def pick_thumb_filename(downloaded_art):
    """Return preferred overview tile image filename, or None."""
    picked = pick_thumb_art(downloaded_art)
    return picked[0] if picked else None



def pick_thumb_art(downloaded_art):
    """Return (filename, art_key) for overview tile primary art."""
    if not isinstance(downloaded_art, dict):
        return None
    for key in _c.THUMB_ART_PRIORITY:
        filename = downloaded_art.get(key)
        if filename:
            return filename, key
    for key, filename in downloaded_art.items():
        if filename and str(key).startswith("fanart"):
            return filename, key
    return None



def pick_fanart_filename(downloaded_art):
    """Primary fanart file for overview banner backgrounds."""
    if not isinstance(downloaded_art, dict):
        return None
    for key in ("fanart", "fanart1", "fanart2", "fanart3", "extrafanart_main"):
        filename = downloaded_art.get(key)
        if filename:
            return filename
    for key, filename in downloaded_art.items():
        if filename and str(key).startswith("fanart"):
            return filename
    return None



def cached_art_filenames():
    """Filenames currently referenced by the now-playing cache (must not be deleted)."""
    protected = set()
    with _c.cache_lock:
        for entry in _c.nowplaying_cache.values():
            for name in entry.get("art_files") or []:
                protected.add(name)
            thumb = entry.get("thumb_file")
            if thumb:
                protected.add(thumb)
            fanart = entry.get("fanart_file")
            if fanart:
                protected.add(fanart)
            share = entry.get("share") or {}
            for bucket_files in (share.get("art_files") or {}).values():
                if isinstance(bucket_files, dict):
                    for name in bucket_files.values():
                        if name:
                            protected.add(name)
    return protected

"""Artwork HTTP fetching, per-server locks, deferred downloads, and cache trimming."""
from __future__ import annotations

import hashlib
import logging
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

from kodi_np import config as _c
from kodi_np.preferences import load_preferences
from kodi_np.servers import get_active_server
from kodi_np.art_paths import (
    _kodi_image_download_url,
    is_kodi_host_url,
    normalize_art_source,
)
from kodi_np.art_paths import is_artwork_filename
from kodi_np.art_select import cached_art_filenames
from kodi_np.art_share import empty_share, share_art_filename

logger = logging.getLogger("kodi.nowplaying")



def _art_download_workers() -> int:
    try:
        n = int(getattr(_c, "ART_DOWNLOAD_WORKERS", 2))
    except (TypeError, ValueError):
        n = 2
    return max(1, min(4, n))



def _http_get_to_file(image_url: str, local_path: str, server: dict, timeout: int = 5) -> None:
    """Download one URL to a local path (raises on failure)."""
    if image_url.startswith(server.get("host") or ""):
        response = requests.get(image_url, auth=server.get("auth"), timeout=timeout)
    else:
        response = requests.get(image_url, timeout=timeout)
    response.raise_for_status()
    with open(local_path, "wb") as handle:
        handle.write(response.content)



def _download_urls_parallel(jobs, server, size_ok_fn=None):
    """Download prepared HTTP jobs in a small pool.

    Each job: {art_key, image_url, local_path, filename, raw_path}
    Returns list of (job, success: bool).
    PrepareDownload must already have been done; this only parallelizes GETs.
    """
    if not jobs:
        return []
    workers = min(_art_download_workers(), len(jobs))

    def _one(job):
        key = job.get("art_key") or "?"
        try:
            _http_get_to_file(job["image_url"], job["local_path"], server)
            if size_ok_fn and not size_ok_fn(job["local_path"], key):
                return job, False
            return job, True
        except Exception as exc:
            logger.error("Failed to download %s: %s", key, exc)
            return job, False

    if workers <= 1:
        return [_one(job) for job in jobs]

    results = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(_one, job) for job in jobs]
        for fut in as_completed(futures):
            results.append(fut.result())
    return results



def _art_lock_for(server_id):
    with _c.art_download_locks_guard:
        lock = _c.art_download_locks.get(server_id)
        if lock is None:
            lock = threading.Lock()
            _c.art_download_locks[server_id] = lock
        return lock



def cleanup_old_artwork_files():
    try:
        now_ts = time.time()
        removed = 0
        protected = cached_art_filenames()
        for filename in os.listdir(_c.ART_TMP_DIR):
            if not is_artwork_filename(filename):
                continue
            if filename in protected:
                continue
            path = os.path.join(_c.ART_TMP_DIR, filename)
            try:
                stat = os.stat(path)
                if (now_ts - stat.st_mtime) >= _c.ART_CLEANUP_AGE_SECONDS:
                    os.remove(path)
                    removed += 1
            except Exception as file_e:
                logger.debug(f"Artwork cleanup skipped {path}: {file_e}")
        candidates = []
        total_bytes = 0
        for filename in os.listdir(_c.ART_TMP_DIR):
            if not is_artwork_filename(filename) or filename in protected:
                continue
            path = os.path.join(_c.ART_TMP_DIR, filename)
            try:
                stat = os.stat(path)
                candidates.append((stat.st_mtime, filename, stat.st_size))
                total_bytes += stat.st_size
            except OSError:
                continue
        max_bytes = max(0, _c.CACHE_MAX_ART_MB) * 1024 * 1024
        candidates.sort()
        while (
            len(candidates) > max(0, _c.CACHE_MAX_ART_FILES)
            or (max_bytes and total_bytes > max_bytes)
        ):
            _, filename, size = candidates.pop(0)
            try:
                os.remove(os.path.join(_c.ART_TMP_DIR, filename))
                total_bytes -= size
                removed += 1
            except OSError:
                break
        if removed:
            logger.info(f"Artwork cleanup removed {removed} files")
    except Exception as e:
        logger.debug(f"Artwork cleanup failed: {e}")



def download_fanart_variant(path: str, key: str, session_id: str, server_id=None):
    """Download one deferred fanart after first paint. Returns local filename or None.

    Uses the per-server art lock. Prefers share filenames when cache share identity
    is available (episode tvshow / song artist); otherwise session-scoped files.
    """
    if not path or not isinstance(path, str) or not key or not isinstance(key, str):
        return None
    if not session_id or not isinstance(session_id, str):
        return None
    # Sanitize key for filenames
    safe_key = re.sub(r"[^A-Za-z0-9_.-]", "_", key)[:80]
    if not safe_key.startswith(("fanart", "extrafanart")):
        return None

    server = get_active_server() if server_id is None else _c.KODI_SERVERS.get(server_id)
    if not server:
        return None
    sid = server.get("id")

    prefs = load_preferences()
    try:
        min_fanart_kb = int(prefs.get("fanartMinSizeKB", 200))
    except (TypeError, ValueError):
        min_fanart_kb = 200
    min_fanart_bytes = max(0, min_fanart_kb) * 1024

    def _size_ok(local_path: str) -> bool:
        if min_fanart_bytes <= 0:
            return True
        try:
            size = os.path.getsize(local_path)
            if size >= min_fanart_bytes:
                return True
            os.remove(local_path)
            return False
        except Exception:
            return True

    with _art_lock_for(sid):
        filename = f"{session_id}_{safe_key}.jpg"
        # Prefer share file when we know show/artist identity from cache
        try:
            from kodi_np.cache import get_cache_entry, set_cache_entry
            entry = get_cache_entry(sid) or {}
            share = dict(entry.get("share") or empty_share())
            tvshow_id = share.get("tvshow_id")
            artist_id = share.get("artist_id")
            if tvshow_id is not None:
                filename = share_art_filename(sid, "tvshow", tvshow_id, safe_key)
            elif artist_id is not None and safe_key.startswith(("fanart", "extrafanart")):
                filename = share_art_filename(sid, "artist", artist_id, safe_key)
        except Exception:
            share = None
            entry = None

        local_path = os.path.join(_c.ART_TMP_DIR, filename)
        if os.path.exists(local_path) and os.path.getsize(local_path) > 0:
            if _size_ok(local_path):
                return filename
            try:
                os.remove(local_path)
            except Exception:
                pass

        image_url = None
        if path.startswith("http://") or path.startswith("https://"):
            if not is_kodi_host_url(path, server):
                logger.warning(
                    "Rejected deferred fanart URL outside the Kodi host: %s", path[:120]
                )
                return None
            image_url = path
        else:
            image_url = _kodi_image_download_url(path, server)
        if not image_url:
            return None
        try:
            _http_get_to_file(image_url, local_path, server, timeout=8)
            if not _size_ok(local_path):
                return None
            # Persist into share cache art_files when applicable
            try:
                if share is not None and entry is not None:
                    scope = "tvshow" if share.get("tvshow_id") is not None else (
                        "artist" if share.get("artist_id") is not None else None
                    )
                    if scope:
                        share.setdefault("art_files", {}).setdefault(scope, {})[safe_key] = filename
                        share.setdefault("art_sources", {}).setdefault(scope, {})[safe_key] = normalize_art_source(path)
                        set_cache_entry(sid, share=share)
            except Exception as exc:
                logger.debug("fanart share cache update skipped: %s", exc)
            logger.debug("Downloaded deferred fanart %s to %s", safe_key, local_path)
            return filename
        except Exception as exc:
            logger.debug("Deferred fanart download failed for %s: %s", safe_key, exc)
            return None



def download_cast_thumbnail(thumbnail_path: str, server_id=None):
    """Download one cast thumbnail on demand. Returns local filename or None.

    Does not block now-playing page builds — call from a lazy API after first paint.
    """
    if not thumbnail_path or not isinstance(thumbnail_path, str):
        return None
    # Skip Kodi default placeholders
    lowered = thumbnail_path.lower()
    if "defaultactor" in lowered or "defaultimage" in lowered:
        return None

    server = get_active_server() if server_id is None else _c.KODI_SERVERS.get(server_id)
    if not server:
        return None

    digest = hashlib.md5(normalize_art_source(thumbnail_path).encode("utf-8")).hexdigest()
    filename = f"cast_{digest}_actor.jpg"
    local_path = _c.ART_TMP_PATH / filename
    if local_path.exists() and local_path.stat().st_size > 0:
        return filename

    image_url = _kodi_image_download_url(thumbnail_path, server)
    if not image_url:
        return None
    try:
        if server.get("auth"):
            response = requests.get(image_url, auth=server["auth"], timeout=8)
        else:
            response = requests.get(image_url, timeout=8)
        response.raise_for_status()
        if not response.content:
            return None
        with open(local_path, "wb") as handle:
            handle.write(response.content)
        logger.debug("Downloaded cast thumb to %s", local_path)
        return filename
    except Exception as exc:
        logger.debug("Cast thumb download failed: %s", exc)
        return None

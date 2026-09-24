"""Kodi artwork path parsing, download URLs, and filesystem path safety."""
from __future__ import annotations

import logging
import os
import urllib.parse
from pathlib import Path


from kodi_np import config as _c
from kodi_np.rpc import kodi_rpc

logger = logging.getLogger("kodi.nowplaying")



def normalize_art_source(path):
    if not path:
        return ""
    cleaned = str(path)
    if cleaned.startswith("image://"):
        cleaned = urllib.parse.unquote(cleaned[len("image://"):])
    return cleaned.rstrip("/")



def _art_path_basename(path: str) -> str:
    """Filename from image://, nfs://, or plain paths (trailing slash safe)."""
    cleaned = normalize_art_source(path).replace("\\", "/")
    return os.path.basename(cleaned) if cleaned else ""



def is_kodi_host_url(url: str, server: dict) -> bool:
    """True when a direct http(s) URL targets the configured Kodi host itself.

    Deferred artwork paths always originate from Kodi (``image://`` / ``nfs://``),
    so a raw URL is only legitimate when it is an already-resolved VFS link.
    Accepting anything else would turn the lazy-artwork API into an SSRF primitive.
    """
    host = (server or {}).get("host") or ""
    if not host:
        return False
    try:
        target = urllib.parse.urlsplit(url)
        allowed = urllib.parse.urlsplit(host)
    except ValueError:
        return False
    if target.scheme not in ("http", "https") or not target.hostname:
        return False
    if target.scheme != (allowed.scheme or "http").lower():
        return False
    default_ports = {"http": 80, "https": 443}
    target_port = target.port or default_ports.get(target.scheme)
    allowed_port = allowed.port or default_ports.get(allowed.scheme or "http")
    return (
        target.hostname.lower() == (allowed.hostname or "").lower()
        and target_port == allowed_port
    )



def _kodi_image_download_url(file_path: str, server: dict):
    """Prepare a downloadable URL; prefer image:// (works for NFS) then bare path."""
    if not file_path or not server:
        return None
    cleaned = normalize_art_source(file_path)
    if not cleaned:
        return None
    if cleaned.startswith("http://") or cleaned.startswith("https://"):
        return cleaned

    candidates = []
    if file_path.startswith("image://"):
        candidates.append(file_path if file_path.endswith("/") else file_path + "/")
    candidates.append(f"image://{urllib.parse.quote(cleaned, safe='')}/")
    candidates.append(cleaned)

    seen = set()
    for path_arg in candidates:
        if path_arg in seen:
            continue
        seen.add(path_arg)
        try:
            response = kodi_rpc("Files.PrepareDownload", {"path": path_arg})
        except Exception as e:
            logger.debug("PrepareDownload failed for %s: %s", path_arg, e)
            continue
        if not response or response.get("error") or not response.get("result"):
            continue
        details = response.get("result", {}).get("details") or {}
        token = details.get("token")
        path = details.get("path")
        if token:
            basename = _art_path_basename(cleaned)
            return f"{server['host']}/vfs/{token}/{urllib.parse.quote(basename)}"
        if path:
            return f"{server['host']}/{path}"
    return None



def is_artwork_filename(filename):
    """True for session (32hex_*) or share (share_32hex_*) artwork files."""
    if not filename:
        return False
    return bool(_c.ARTWORK_FILENAME_RE.fullmatch(filename))



def resolve_safe_child(base_dir: Path, filename: str):
    if not filename or "/" in filename or "\\" in filename:
        return None
    try:
        path = (base_dir / filename).resolve()
        if not path.is_relative_to(base_dir):
            return None
        return path
    except Exception:
        return None

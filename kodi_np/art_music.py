"""Artist-folder artwork discovery for music playback."""
from __future__ import annotations

import logging
import os
import re
import urllib.parse


from kodi_np.rpc import kodi_rpc
from kodi_np.art_paths import _art_path_basename, normalize_art_source

logger = logging.getLogger("kodi.nowplaying")



def _is_remote_song_path(path: str) -> bool:
    if not path:
        return False
    lowered = path.lower()
    return (
        lowered.startswith("nfs://")
        or lowered.startswith("smb://")
        or lowered.startswith("ftp://")
        or lowered.startswith("sftp://")
    )



def _music_artist_directory(song_file: str) -> str:
    """Best-effort artist folder for Music/<Artist>/<Album>/track layouts."""
    if not song_file:
        return ""
    normalized = song_file.replace("\\", "/").rstrip("/")
    parts = normalized.split("/")
    for i, part in enumerate(parts):
        if part.lower() == "music" and i + 1 < len(parts):
            # Keep protocol + host segments through Music/<Artist>
            return "/".join(parts[: i + 2])
    album_dir = os.path.dirname(normalized)
    artist_dir = os.path.dirname(album_dir)
    return artist_dir if artist_dir != album_dir else album_dir



def _needs_artist_media_remap(art_path: str) -> bool:
    """True when Kodi art points at ArtistInformation or a local Windows path."""
    if not art_path:
        return False
    cleaned = normalize_art_source(art_path)
    if "ArtistInformation" in art_path or "ArtistInformation" in cleaned:
        return True
    # e.g. U:\Kodi\ArtistInformation\AURORA\clearlogo.png
    if re.match(r"^[A-Za-z]:[\\/]", cleaned):
        return True
    return False



def _remap_artist_art_to_song_tree(art_path: str, song_file: str) -> str:
    """Map ArtistInformation/Windows art paths onto Music/<Artist>/<filename>."""
    filename = _art_path_basename(art_path)
    if not filename or not _is_remote_song_path(song_file):
        return ""
    artist_dir = _music_artist_directory(song_file)
    if not artist_dir:
        return ""
    return f"{artist_dir.rstrip('/')}/{filename}"



# Stem -> preferred filenames when scanning the artist folder
# clearlogo also accepts clearart: many libraries only ship clearart.png as the logo
_ARTIST_FOLDER_ART_STEMS = {
    "clearlogo": ("clearlogo", "logo", "clearlogo1", "clearart"),
    "clearart": ("clearart",),
    "banner": ("banner",),
}



def _scan_directory_for_art_stems(directory: str, stems: tuple) -> str:
    """Return first matching image path in directory for the given name stems."""
    if not directory or not stems:
        return ""
    try:
        dir_response = kodi_rpc("Files.GetDirectory", {
            "directory": directory,
            "properties": ["file"],
        })
    except Exception as scan_err:
        logger.debug(f"Artist art scan failed for {directory}: {scan_err}")
        return ""
    if not dir_response or not dir_response.get("result") or dir_response.get("error"):
        return ""
    stem_set = {s.lower() for s in stems}
    for file_info in dir_response.get("result", {}).get("files", []) or []:
        if not isinstance(file_info, dict):
            continue
        if file_info.get("filetype") != "file":
            continue
        file_path = file_info.get("file") or ""
        lower = file_path.lower()
        if not lower.endswith((".png", ".jpg", ".jpeg", ".webp")):
            continue
        name = os.path.splitext(os.path.basename(lower.replace("\\", "/")))[0]
        if name in stem_set:
            return file_path
    return ""



def _probe_artist_folder_art(artist_dir: str, stems: tuple) -> str:
    """Find art in Music/<Artist>/ via directory listing, then PrepareDownload probes."""
    if not artist_dir or not stems:
        return ""
    found = _scan_directory_for_art_stems(artist_dir, stems)
    if found:
        return found

    # GetDirectory can fail on some shares; probe common filenames the way fanart fallback does
    for stem in stems:
        for ext in (".png", ".jpg", ".jpeg", ".webp"):
            bare = f"{artist_dir.rstrip('/')}/{stem}{ext}"
            image_path = f"image://{urllib.parse.quote(bare, safe='')}/"
            for path_arg in (image_path, bare):
                try:
                    response = kodi_rpc("Files.PrepareDownload", {"path": path_arg})
                except Exception:
                    continue
                if not response or response.get("error") or not response.get("result"):
                    continue
                details = response.get("result", {}).get("details") or {}
                if details.get("token") or details.get("path"):
                    return bare
    return ""



def prefer_music_artist_folder_art(song_file: str, art_map: dict, buckets: dict | None = None, key_scope: dict | None = None):
    """
    Prefer Music/<Artist>/<artfile> (one folder up from the album) for logos/clearart.
    Runs before share reuse so a local artist-folder path invalidates stale shared art.
    """
    if not song_file or not isinstance(art_map, dict):
        return
    album_dir = os.path.dirname(song_file.replace("\\", "/").rstrip("/"))
    artist_dir = _music_artist_directory(song_file) or os.path.dirname(album_dir)
    if not artist_dir or artist_dir == album_dir:
        return

    for art_key, stems in _ARTIST_FOLDER_ART_STEMS.items():
        found = _probe_artist_folder_art(artist_dir, stems)
        if not found:
            continue
        prior = art_map.get(art_key)
        art_map[art_key] = found
        if buckets is not None:
            buckets.setdefault("artist", {})[art_key] = found
        if key_scope is not None:
            key_scope[art_key] = "artist"
        if prior != found:
            logger.info("Using artist-folder %s: %s", art_key, found)

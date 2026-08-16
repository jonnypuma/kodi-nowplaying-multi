"""Artwork orchestration.

Path handling, share reuse, selection, music folder probing, and the
download plumbing live in the ``art_*`` sibling modules; this module wires
them together and re-exports the whole surface for existing importers.
"""
from __future__ import annotations

import logging
import os
import re
import urllib.parse

import requests

from kodi_np import config as _c
from kodi_np.preferences import load_preferences
from kodi_np.rpc import kodi_rpc
from kodi_np.servers import get_active_server
from kodi_np.art_paths import (
    _art_path_basename,
    _kodi_image_download_url,
    is_artwork_filename,
    is_kodi_host_url,
    normalize_art_source,
    resolve_safe_child,
)
from kodi_np.art_share import (
    apply_share_reuse,
    build_key_scope_map,
    classify_art_buckets,
    empty_share,
    ensure_share_file,
    primary_artist_id,
    scope_identity,
    season_share_identity,
    share_art_filename,
    share_identity_hash,
    share_scope_matches,
)
from kodi_np.art_select import (
    cached_art_filenames,
    collect_extrafanart_variants,
    pick_fanart_filename,
    pick_thumb_art,
    pick_thumb_filename,
    select_primary_fanart_key,
)
from kodi_np.art_music import (
    _ARTIST_FOLDER_ART_STEMS,
    _is_remote_song_path,
    _music_artist_directory,
    _needs_artist_media_remap,
    _probe_artist_folder_art,
    _remap_artist_art_to_song_tree,
    _scan_directory_for_art_stems,
    prefer_music_artist_folder_art,
)
from kodi_np.art_download import (
    _art_download_workers,
    _art_lock_for,
    _download_urls_parallel,
    _http_get_to_file,
    cleanup_old_artwork_files,
    download_cast_thumbnail,
    download_fanart_variant,
)

logger = logging.getLogger("kodi.nowplaying")

__all__ = [
    "apply_share_reuse",
    "build_key_scope_map",
    "cached_art_filenames",
    "classify_art_buckets",
    "cleanup_old_artwork_files",
    "collect_extrafanart_variants",
    "download_cast_thumbnail",
    "download_fanart_variant",
    "empty_share",
    "ensure_share_file",
    "is_artwork_filename",
    "is_kodi_host_url",
    "normalize_art_source",
    "pick_fanart_filename",
    "pick_thumb_art",
    "pick_thumb_filename",
    "prefer_music_artist_folder_art",
    "prepare_and_download_art",
    "primary_artist_id",
    "resolve_safe_child",
    "scope_identity",
    "season_share_identity",
    "select_primary_fanart_key",
    "share_art_filename",
    "share_identity_hash",
    "share_scope_matches",
]



def prepare_and_download_art(item, session_id, progress_cb=None, share_context=None):
    downloaded = {}
    share_context = share_context or {}
    
    # Get active server for this request
    server = get_active_server()
    if not server:
        logger.error("No active server available for artwork download")
        return downloaded, empty_share()

    # Serialize art RPC/download traffic per Kodi — concurrent PrepareDownload floods hang weak devices
    with _art_lock_for(server.get("id")):
        return _prepare_and_download_art_locked(
            item, session_id, server, progress_cb=progress_cb, share_context=share_context
        )



def _prepare_and_download_art_locked(item, session_id, server, progress_cb=None, share_context=None):
    downloaded = {}
    share_context = share_context or {}
    media_type = item.get("type") or share_context.get("media_type")
    server_id = server.get("id")
    prior_share = share_context.get("prior_share") or empty_share()
    tvshow_id = share_context.get("tvshow_id")
    season = share_context.get("season")
    album_id = share_context.get("album_id")
    artist_id = share_context.get("artist_id")
    enable_share = media_type in ("episode", "song") and server_id is not None

    share_out = empty_share()
    if enable_share:
        share_out["tvshow_id"] = tvshow_id
        share_out["season"] = season
        share_out["album_id"] = album_id
        share_out["artist_id"] = artist_id
        if share_scope_matches(prior_share, "tvshow", tvshow_id):
            share_out["tvshow_meta"] = prior_share.get("tvshow_meta")
        if share_scope_matches(prior_share, "album", album_id):
            share_out["album_details"] = prior_share.get("album_details")
        if share_scope_matches(prior_share, "artist", artist_id):
            share_out["artist_details"] = prior_share.get("artist_details")

    art_map = dict(item.get("art", {}) or {})
    if item.get("thumbnail") and not art_map.get("poster"):
        art_map["poster"] = item["thumbnail"]

    buckets = classify_art_buckets(art_map)
    key_scope = build_key_scope_map(buckets, media_type) if enable_share else {}

    # Handle TV show artwork with tvshow. prefix
    tvshow_art_map = dict(buckets.get("tvshow") or {})

    # Handle music artwork with album., artist., and albumartist. prefixes
    music_art_map = {}
    for key, value in (buckets.get("album") or {}).items():
        music_art_map[key] = value
    for key, value in (buckets.get("artist") or {}).items():
        music_art_map[key] = value

    # Merge all artwork (music takes precedence, then TV show, then regular)
    art_map = {**art_map, **tvshow_art_map, **music_art_map}

    # Music: resolve clearlogo/clearart from Music/<Artist>/ BEFORE share reuse
    # so local files win over stale ArtistInformation share cache.
    if media_type == "song" and item.get("file"):
        prefer_music_artist_folder_art(
            item.get("file"),
            art_map,
            buckets=buckets if enable_share else None,
            key_scope=key_scope if enable_share else None,
        )
        # Keep music_art_map / art_map in sync after preference
        for key in _ARTIST_FOLDER_ART_STEMS:
            if art_map.get(key):
                music_art_map[key] = art_map[key]

    if enable_share:
        if media_type == "episode":
            apply_share_reuse(server_id, "tvshow", tvshow_id, buckets.get("tvshow"), prior_share, downloaded)
            apply_share_reuse(
                server_id,
                "season",
                season_share_identity(tvshow_id, season),
                buckets.get("season"),
                prior_share,
                downloaded,
            )
        elif media_type == "song":
            apply_share_reuse(server_id, "album", album_id, buckets.get("album"), prior_share, downloaded)
            apply_share_reuse(server_id, "artist", artist_id, buckets.get("artist"), prior_share, downloaded)
        for art_key, filename in list(downloaded.items()):
            scope = key_scope.get(art_key)
            if not scope:
                if art_key == "season.poster" or str(art_key).startswith("season."):
                    scope = "season"
                elif media_type == "episode":
                    scope = "tvshow"
                elif media_type == "song" and art_key in _c.MUSIC_COVER_KEYS:
                    scope = "album"
                else:
                    scope = "artist" if media_type == "song" else None
            if not scope:
                continue
            share_out["art_files"].setdefault(scope, {})[art_key] = filename
            src = (buckets.get(scope) or {}).get(art_key)
            if src:
                share_out["art_sources"].setdefault(scope, {})[art_key] = normalize_art_source(src)
            elif (prior_share.get("art_sources") or {}).get(scope, {}).get(art_key):
                share_out["art_sources"].setdefault(scope, {})[art_key] = prior_share["art_sources"][scope][art_key]

    def _target_filename(art_key):
        scope = key_scope.get(art_key)
        if enable_share and scope:
            identity = scope_identity(
                scope, tvshow_id=tvshow_id, season=season, album_id=album_id, artist_id=artist_id
            )
            if identity is not None:
                return share_art_filename(server_id, scope, identity, art_key)
        return f"{session_id}_{art_key}.jpg"

    def _commit_art(art_key, filename, source_path=None):
        downloaded[art_key] = filename
        scope = key_scope.get(art_key)
        if not (enable_share and scope):
            return
        identity = scope_identity(
            scope, tvshow_id=tvshow_id, season=season, album_id=album_id, artist_id=artist_id
        )
        if identity is None:
            return
        share_name = ensure_share_file(
            server_id, scope, identity, art_key, source_path, session_filename=filename
        )
        if share_name:
            downloaded[art_key] = share_name
            share_out["art_files"].setdefault(scope, {})[art_key] = share_name
            if source_path:
                share_out["art_sources"].setdefault(scope, {})[art_key] = normalize_art_source(source_path)
    
    # Debug logging for artwork
    logger.debug(f"Original art_map keys: {list(item.get('art', {}).keys())}")
    logger.debug(f"Final art_map keys: {list(art_map.keys())}")

    # Special handling for fanart - collect all variants for slideshow
    fanart_variants = {}
    for key, value in art_map.items():
        # Collect both regular fanart variants and extrafanart variants
        if (key.startswith("fanart") and (key == "fanart" or key.startswith("fanart"))) or key.startswith("extrafanart"):
            fanart_variants[key] = value
    
    logger.debug(f"Found fanart variants: {list(fanart_variants.keys())}")
    logger.debug(f"Total fanart variants found: {len(fanart_variants)}")

    prefs = load_preferences()
    try:
        min_fanart_kb = int(prefs.get("fanartMinSizeKB", 200))
    except (TypeError, ValueError):
        min_fanart_kb = 200
    min_fanart_kb = max(0, min_fanart_kb)
    min_fanart_bytes = min_fanart_kb * 1024

    def _is_fanart_key(key: str) -> bool:
        return key.startswith("fanart") or key.startswith("extrafanart")

    def _fanart_size_ok(local_path: str, art_key: str) -> bool:
        if not _is_fanart_key(art_key) or min_fanart_bytes <= 0:
            return True
        try:
            size = os.path.getsize(local_path)
            if size >= min_fanart_bytes:
                return True
            os.remove(local_path)
            logger.info(f"Skipping {art_key} - size {size} bytes below {min_fanart_bytes}")
            return False
        except Exception as size_e:
            logger.debug(f"Failed size check for {art_key}: {size_e}")
            return True
    
    # For music, try to find common front cover files if Kodi provided audio file instead of image
    def _is_image_path(path: str) -> bool:
        if not path:
            return False
        lowered = path.lower()
        return lowered.endswith((".jpg", ".jpeg", ".png", ".webp"))

    def _clean_image_protocol(path: str) -> str:
        if not path:
            return ""
        cleaned = path
        if cleaned.startswith("image://"):
            cleaned = urllib.parse.unquote(cleaned[len("image://"):])
        return cleaned.rstrip("/")

    if item.get("type") == "song" and item.get("file"):
        current_file = item.get("file", "")
        album_dir = os.path.dirname(current_file.rstrip("/"))

        # Determine if Kodi gave us a proper image thumbnail
        kodi_thumbnail = art_map.get("thumbnail") or art_map.get("thumb") or art_map.get("album.thumb")
        cleaned_thumbnail = _clean_image_protocol(kodi_thumbnail)
        has_valid_cover = _is_image_path(cleaned_thumbnail)

        if not has_valid_cover and "thumbnail" not in downloaded:
            front_cover_candidates = {
                "folder", "cover", "thumb", "front", "album", "artist",
                "frontcover", "albumcover", "cd", "cdcover"
            }

            def find_cover(start_dir: str, max_depth: int = 3) -> str:
                checked = set()
                current_dir = start_dir

                for depth in range(max_depth + 1):
                    if not current_dir or current_dir in checked:
                        break
                    checked.add(current_dir)
                    try:
                        dir_response = kodi_rpc("Files.GetDirectory", {
                            "directory": current_dir,
                            "properties": ["file"]
                        })

                        if dir_response and dir_response.get("result") and not dir_response.get("error"):
                            files = dir_response.get("result", {}).get("files", [])
                            logger.debug(f"Music cover scan (depth {depth}) found {len(files)} files in {current_dir}")

                            for file_info in files:
                                if not isinstance(file_info, dict):
                                    continue
                                file_path = file_info.get("file", "")
                                file_type = file_info.get("filetype", "")
                                if file_type != "file" or not file_path:
                                    continue

                                lower_path = file_path.lower()
                                if not lower_path.endswith((".jpg", ".jpeg", ".png", ".webp")):
                                    continue

                                base_name = os.path.basename(lower_path)
                                name_without_ext, _ = os.path.splitext(base_name)

                                if (name_without_ext in front_cover_candidates or
                                        any(candidate in name_without_ext for candidate in front_cover_candidates)):
                                    logger.debug(f"Found fallback album cover at depth {depth}: {file_path}")
                                    return file_path
                        else:
                            logger.debug(f"Music cover directory scan failed for {current_dir}: {dir_response}")
                    except Exception as scan_error:
                        logger.debug(f"Error scanning directory {current_dir} for cover art: {scan_error}")

                    # Move one level up
                    parent_dir = os.path.dirname(current_dir.rstrip("/"))
                    if parent_dir == current_dir:
                        break
                    current_dir = parent_dir

                return ""

            potential_cover = find_cover(album_dir)
            if potential_cover:
                art_map["thumbnail"] = potential_cover
                art_map["thumb"] = potential_cover
                if enable_share:
                    key_scope["thumbnail"] = "album"
                    key_scope["thumb"] = "album"
                    buckets.setdefault("album", {})["thumbnail"] = potential_cover
                logger.debug(f"Using fallback music thumbnail: {potential_cover}")
            else:
                logger.debug(f"No fallback album cover found for {album_dir}")

        # Remap ArtistInformation / Windows clearlogo (etc.) onto Music/<Artist>/…
        # Same idea as fanart1–N ArtistInformation fallback that already works.
        artist_dir = _music_artist_directory(current_file)
        for art_key, stems in _ARTIST_FOLDER_ART_STEMS.items():
            if art_key in downloaded:
                continue
            current = art_map.get(art_key)
            remapped = ""
            if current and _needs_artist_media_remap(current):
                remapped = _remap_artist_art_to_song_tree(current, current_file)
                if remapped:
                    art_map[art_key] = remapped
                    if enable_share:
                        key_scope[art_key] = "artist"
                        buckets.setdefault("artist", {})[art_key] = remapped
                    logger.debug(
                        "Remapped music %s from ArtistInformation/Windows path to %s",
                        art_key,
                        remapped,
                    )
                    continue
            if (not current or _needs_artist_media_remap(current)) and artist_dir:
                found = _scan_directory_for_art_stems(artist_dir, stems)
                if found:
                    art_map[art_key] = found
                    if enable_share:
                        key_scope[art_key] = "artist"
                        buckets.setdefault("artist", {})[art_key] = found
                    logger.debug("Resolved music %s via artist folder scan: %s", art_key, found)

    def _extract_art_dir(path: str) -> str:
        if not path:
            return ""
        cleaned = path
        if cleaned.startswith("image://"):
            cleaned = urllib.parse.unquote(cleaned[len("image://"):])
        cleaned = cleaned.rstrip("/")
        return os.path.dirname(cleaned)

    def _resolve_episode_media_dir(art_map: dict, current_file: str) -> str:
        for key in [
            "tvshow.clearlogo",
            "tvshow.logo",
            "tvshow.banner",
            "tvshow.poster",
            "tvshow.fanart",
            "tvshow.landscape",
            "tvshow.thumb"
        ]:
            candidate = _extract_art_dir(art_map.get(key))
            if candidate:
                return candidate
        episode_dir = os.path.dirname(current_file.rstrip("/"))
        dir_name = os.path.basename(episode_dir).lower()
        if dir_name.startswith("season") or re.match(r"^season\s*\d+", dir_name):
            return os.path.dirname(episode_dir)
        return episode_dir

    # For movies and episodes, try to find additional fanart files in the media folder
    if item.get("type") in ["movie", "episode"] and item.get("file"):
        current_file = item.get("file", "")
        if current_file.startswith("nfs://"):
            try:
                # For TV episodes, we need to look in the TV show's root directory, not the episode's directory
                if item.get("type") == "episode":
                    # Use tvshow art paths when available to avoid scanning the TV root
                    media_dir = _resolve_episode_media_dir(art_map, current_file)
                    logger.debug(f"TV Episode detected - looking for fanart in show root directory: {media_dir}")
                else:
                    # For movies, use the movie's directory
                    media_dir = os.path.dirname(current_file)
                    logger.debug(f"Looking for additional fanart in directory: {media_dir}")
                
                # Try to list the directory contents using Kodi's Files.GetDirectory API
                try:
                    dir_response = kodi_rpc("Files.GetDirectory", {
                        "directory": media_dir,
                        "properties": ["file"]
                    })
                    
                    if dir_response and dir_response.get("result") and not dir_response.get("error"):
                        files = dir_response.get("result", {}).get("files", [])
                        logger.debug(f"Found {len(files)} files in directory")
                        
                        # Look for fanart files in the directory listing
                        for file_info in files:
                            if isinstance(file_info, dict):
                                file_path = file_info.get("file", "")
                                file_type = file_info.get("filetype", "")

                                if file_type == "file" and file_path:
                                    base_name = os.path.basename(file_path).lower()
                                    stem_map = {
                                        "clearlogo": ("clearlogo.png", "clearlogo.jpg", "clearlogo.jpeg", "clearlogo.webp"),
                                        "banner": ("banner.png", "banner.jpg", "banner.jpeg", "banner.webp"),
                                        "landscape": ("landscape.png", "landscape.jpg", "landscape.jpeg", "landscape.webp"),
                                        "clearart": ("clearart.png", "clearart.jpg", "clearart.jpeg", "clearart.webp"),
                                    }
                                    for art_key, names in stem_map.items():
                                        if base_name in names and not art_map.get(art_key):
                                            art_map[art_key] = file_path
                                            logger.debug("Added %s from media dir: %s", art_key, file_path)
                                
                                # Check if this is the extrafanart directory
                                if file_path and file_type == "directory" and "extrafanart" in file_path.lower():
                                    logger.debug(f"Found extrafanart directory: {file_path}")
                                    
                                    # Scan the extrafanart directory
                                    try:
                                        extrafanart_response = kodi_rpc("Files.GetDirectory", {
                                            "directory": file_path,
                                            "properties": ["file"]
                                        })
                                        
                                        if extrafanart_response and extrafanart_response.get("result") and not extrafanart_response.get("error"):
                                            extrafanart_files = extrafanart_response.get("result", {}).get("files", [])
                                            logger.debug(f"Found {len(extrafanart_files)} files in extrafanart directory")

                                            for key_name, extra_path in collect_extrafanart_variants(extrafanart_files).items():
                                                fanart_variants[key_name] = extra_path
                                                if enable_share and media_type == "episode":
                                                    key_scope[key_name] = "tvshow"
                                                logger.debug("Added extrafanart: %s -> %s", key_name, extra_path)
                                        else:
                                            logger.debug(f"Failed to scan extrafanart directory: {extrafanart_response}")
                                            
                                    except Exception as extrafanart_e:
                                        logger.debug(f"Error scanning extrafanart directory: {extrafanart_e}")
                                
                                # Also check for fanart files directly in the main directory
                                elif file_path and "fanart" in file_path.lower() and file_type == "file":
                                    logger.debug(f"Found potential fanart file: {file_path}")
                                    
                                    # Try to determine the fanart variant name
                                    filename = os.path.basename(file_path)
                                    if filename.lower() == "fanart.jpg":
                                        # This is the main fanart, skip it
                                        continue
                                    elif filename.lower().startswith("fanart") and filename.lower().endswith((".jpg", ".jpeg", ".png")):
                                        # Extract the variant number
                                        variant_name = filename.lower().replace("fanart", "").replace(".jpg", "").replace(".jpeg", "").replace(".png", "")
                                        if variant_name.isdigit():
                                            fanart_variants[f"fanart{variant_name}"] = file_path
                                            if enable_share and media_type == "episode":
                                                key_scope[f"fanart{variant_name}"] = "tvshow"
                                            logger.debug(f"Added fanart variant: fanart{variant_name} -> {file_path}")
                                        elif variant_name == "":
                                            # This is fanart.jpg, skip it
                                            continue
                                        else:
                                            # Custom fanart name
                                            fanart_variants[f"fanart_{variant_name}"] = file_path
                                            if enable_share and media_type == "episode":
                                                key_scope[f"fanart_{variant_name}"] = "tvshow"
                                            logger.debug(f"Added custom fanart: fanart_{variant_name} -> {file_path}")
                    else:
                        logger.debug(f"Failed to get directory listing: {dir_response}")
                        
                except Exception as dir_e:
                    logger.debug(f"Directory listing failed: {dir_e}")
                    
                    # Fallback: try to find fanart1, fanart2, etc. by testing individual files
                    logger.debug("Falling back to individual file testing")
                    for i in range(1, 10):  # fanart1 through fanart9
                        fanart_filename = f"fanart{i}.jpg"
                        fanart_path = f"{media_dir}/{fanart_filename}"
                        
                        logger.debug(f"Testing fanart{i}: {fanart_path}")
                        
                        # Try to access the file directly through Kodi's HTTP interface
                        try:
                            response = kodi_rpc("Files.PrepareDownload", {"path": fanart_path})
                            if response and response.get("result") and not response.get("error"):
                                details = response.get("result", {}).get("details", {})
                                token = details.get("token")
                                path = details.get("path")
                                
                                if token:
                                    basename = os.path.basename(fanart_path)
                                    image_url = f"{server['host']}/vfs/{token}/{urllib.parse.quote(basename)}"
                                    # Test if the image actually exists
                                    try:
                                        test_response = requests.head(image_url, auth=server['auth'], timeout=3)
                                        if test_response.status_code == 200:
                                            fanart_variants[f"fanart{i}"] = fanart_path
                                            if enable_share and media_type == "episode":
                                                key_scope[f"fanart{i}"] = "tvshow"
                                            logger.debug(f"Found additional fanart: fanart{i} at {fanart_path}")
                                    except Exception as test_e:
                                        logger.debug(f"Test request failed for fanart{i}: {test_e}")
                                elif path:
                                    # Test if the image actually exists
                                    try:
                                        test_response = requests.head(f"{server['host']}/{path}", auth=server['auth'], timeout=3)
                                        if test_response.status_code == 200:
                                            fanart_variants[f"fanart{i}"] = fanart_path
                                            if enable_share and media_type == "episode":
                                                key_scope[f"fanart{i}"] = "tvshow"
                                            logger.debug(f"Found additional fanart: fanart{i} at {fanart_path}")
                                    except Exception as test_e:
                                        logger.debug(f"Test request failed for fanart{i}: {test_e}")
                        except Exception as e:
                            logger.debug(f"Failed to check fanart{i}: {e}")
                            pass
                        
            except Exception as e:
                logger.debug(f"Failed to scan for additional fanart: {e}")
    
    logger.debug(f"Total fanart variants found: {list(fanart_variants.keys())}")

    # Reuse shared show fanart variants discovered via directory scan
    if enable_share and media_type == "episode" and tvshow_id is not None:
        variant_sources = {k: v for k, v in fanart_variants.items() if k != "fanart"}
        apply_share_reuse(server_id, "tvshow", tvshow_id, variant_sources, prior_share, downloaded)
        for art_key, filename in list(downloaded.items()):
            if art_key in variant_sources or (
                art_key.startswith(("fanart", "extrafanart")) and art_key != "fanart"
            ):
                share_out["art_files"].setdefault("tvshow", {})[art_key] = filename
                if art_key in variant_sources:
                    share_out["art_sources"].setdefault("tvshow", {})[art_key] = normalize_art_source(
                        variant_sources[art_key]
                    )

    def art_label(art_key: str) -> str:
        if art_key in ["poster", "front", "back", "thumbnail", "season.poster"]:
            return "Loading posters"
        if art_key.startswith("fanart") or art_key.startswith("extrafanart"):
            return "Loading fanart"
        return "Loading artwork"

    art_tasks = []
    early_primary = select_primary_fanart_key(media_type, fanart_variants, downloaded)
    for art_type in _c.ART_TYPES:
        if art_map.get(art_type) and art_type not in downloaded:
            # Music may prefer extrafanart as first slide — skip main fanart on critical path.
            if (
                art_type == "fanart"
                and early_primary
                and early_primary != "fanart"
                and str(early_primary).startswith("extrafanart")
            ):
                continue
            art_tasks.append(("art", art_type))
    # Extra fanart variants are deferred after first paint — do not count them here.

    total_tasks = len(art_tasks)
    task_index = 0

    def update_art_progress(label: str):
        nonlocal task_index
        task_index += 1
        if progress_cb and total_tasks:
            progress_cb(task_index, total_tasks, label)

    if progress_cb and total_tasks == 0:
        progress_cb(1, 1, "Loading artwork")

    http_jobs = []
    use_parallel = _art_download_workers() > 1

    for art_type in _c.ART_TYPES:
        if art_type in downloaded:
            continue
        if (
            art_type == "fanart"
            and early_primary
            and early_primary != "fanart"
            and str(early_primary).startswith("extrafanart")
        ):
            continue
        raw_path = art_map.get(art_type)
        logger.debug(f"Processing art_type: {art_type}, raw_path: {raw_path}")
        if not raw_path:
            continue
        label = art_label(art_type)

        if raw_path and raw_path.startswith("image://"):
            raw_path = urllib.parse.unquote(raw_path[len("image://"):])
        if raw_path and raw_path.endswith("/"):
            raw_path = raw_path[:-1]

        # Handle external URLs directly (like fanart.tv, theaudiodb.com)
        if raw_path and (raw_path.startswith("https://") or raw_path.startswith("http://")):
            image_url = raw_path
        else:
            # Prefer image:// PrepareDownload (required for many NFS art paths)
            image_url = _kodi_image_download_url(raw_path, server)
            if not image_url:
                logger.error(f"No valid download path for {art_type}")
            
            # If primary path failed, try fallback paths for artist artwork
            if not image_url and art_type in ["fanart", "clearlogo", "clearart", "banner", "front", "back", "discart"]:
                logger.debug(f"Primary path failed, trying fallback paths for {art_type}")
                # Fast path: one folder up from the song (Music/<Artist>/)
                current_file = item.get("file", "")
                if item.get("type") == "song" and _is_remote_song_path(current_file):
                    artist_dir = _music_artist_directory(current_file)
                    stems = _ARTIST_FOLDER_ART_STEMS.get(art_type) or (art_type,)
                    probed = _probe_artist_folder_art(artist_dir, stems) if artist_dir else ""
                    if probed:
                        image_url = _kodi_image_download_url(probed, server)
                        if image_url:
                            raw_path = probed
                            logger.info("Resolved %s via artist folder fallback: %s", art_type, probed)
                if _is_remote_song_path(current_file) and not image_url:
                    try:
                        # Traverse upwards to find directories that contain fanart files
                        # This is the most reliable way since fanart is typically only in artist directories
                        current_path = current_file
                        fallback_paths = []
                        
                        logger.debug(f"Traversing upwards from: {current_path}")
                        
                        # Traverse upwards to find directories with fanart files
                        for level in range(8):  # Limit to 8 levels up to avoid infinite loops
                            parent_path = os.path.dirname(current_path)
                            if parent_path == current_path:  # Reached root
                                break
                            
                            dir_name = os.path.basename(parent_path)
                            
                            # Skip system directories
                            if any(x in dir_name.upper() for x in ['MEDIA', 'MUSIC', 'VIDEO', 'TV', 'MOVIES']):
                                current_path = parent_path
                                pass
                            
                            # Try to find fanart files in this directory
                            # This works for both artist directories (which have fanart) and album directories (which might have other artwork)
                            fanart_png = f"{parent_path}/fanart.png"
                            fanart_jpg = f"{parent_path}/fanart.jpg"
                            clearlogo_png = f"{parent_path}/clearlogo.png"
                            clearlogo_jpg = f"{parent_path}/clearlogo.jpg"
                            clearlogo_jpeg = f"{parent_path}/clearlogo.jpeg"
                            clearlogo_webp = f"{parent_path}/clearlogo.webp"
                            logo_png = f"{parent_path}/logo.png"
                            logo_jpg = f"{parent_path}/logo.jpg"
                            clearart_png = f"{parent_path}/clearart.png"
                            clearart_jpg = f"{parent_path}/clearart.jpg"
                            banner_png = f"{parent_path}/banner.png"
                            banner_jpg = f"{parent_path}/banner.jpg"
                            Front_jpg = f"{parent_path}/Front.jpg"
                            Front_png = f"{parent_path}/Front.png"
                            Front_jpeg = f"{parent_path}/Front.jpeg"
                            front_jpg = f"{parent_path}/front.jpg"
                            front_png = f"{parent_path}/front.png"
                            front_jpeg = f"{parent_path}/front.jpeg"
                            Back_jpg = f"{parent_path}/Back.jpg"
                            Back_png = f"{parent_path}/Back.png"
                            Back_jpeg = f"{parent_path}/Back.jpeg"
                            back_jpg = f"{parent_path}/back.jpg"
                            back_png = f"{parent_path}/back.png"
                            back_jpeg = f"{parent_path}/back.jpeg"
                            discart_png = f"{parent_path}/discart.png"
                            discart_jpg = f"{parent_path}/discart.jpg"
                            discart_jpeg = f"{parent_path}/discart.jpeg"
                            Discart_png = f"{parent_path}/Discart.png"
                            Discart_jpg = f"{parent_path}/Discart.jpg"
                            Discart_jpeg = f"{parent_path}/Discart.jpeg"
                            
                            # Add paths for the specific art type we're looking for
                            if art_type == "fanart":
                                fallback_paths.append(f"image://{urllib.parse.quote(fanart_png, safe='')}/")
                                fallback_paths.append(f"image://{urllib.parse.quote(fanart_jpg, safe='')}/")
                                # First, try extrafanart folder (fanart.jpg, fanart2.jpg, etc.)
                                for i in range(1, 10):  # fanart1 through fanart9 in extrafanart folder
                                    extrafanart_png = f"{parent_path}/extrafanart/fanart{i}.png"
                                    extrafanart_jpg = f"{parent_path}/extrafanart/fanart{i}.jpg"
                                    extrafanart_jpeg = f"{parent_path}/extrafanart/fanart{i}.jpeg"
                                    fallback_paths.extend([
                                        f"image://{urllib.parse.quote(extrafanart_png, safe='')}/",
                                        f"image://{urllib.parse.quote(extrafanart_jpg, safe='')}/",
                                        f"image://{urllib.parse.quote(extrafanart_jpeg, safe='')}/"
                                    ])
                                
                                # Also try the main fanart.jpg in extrafanart folder
                                extrafanart_main_png = f"{parent_path}/extrafanart/fanart.png"
                                extrafanart_main_jpg = f"{parent_path}/extrafanart/fanart.jpg"
                                extrafanart_main_jpeg = f"{parent_path}/extrafanart/fanart.jpeg"
                                fallback_paths.extend([
                                    f"image://{urllib.parse.quote(extrafanart_main_png, safe='')}/",
                                    f"image://{urllib.parse.quote(extrafanart_main_jpg, safe='')}/",
                                    f"image://{urllib.parse.quote(extrafanart_main_jpeg, safe='')}/"
                                ])
                                
                                # Also try fanart variants (fanart1, fanart2, etc.)
                                for i in range(1, 10):  # fanart1 through fanart9
                                    fanart_var_png = f"{parent_path}/fanart{i}.png"
                                    fanart_var_jpg = f"{parent_path}/fanart{i}.jpg"
                                    fanart_var_jpeg = f"{parent_path}/fanart{i}.jpeg"
                                    fallback_paths.extend([
                                        f"image://{urllib.parse.quote(fanart_var_png, safe='')}/",
                                        f"image://{urllib.parse.quote(fanart_var_jpg, safe='')}/",
                                        f"image://{urllib.parse.quote(fanart_var_jpeg, safe='')}/"
                                    ])
                            elif art_type == "clearlogo":
                                for candidate in (
                                    clearlogo_png, clearlogo_jpg, clearlogo_jpeg, clearlogo_webp,
                                    logo_png, logo_jpg, clearart_png, clearart_jpg,
                                ):
                                    fallback_paths.append(f"image://{urllib.parse.quote(candidate, safe='')}/")
                            elif art_type == "clearart":
                                fallback_paths.append(f"image://{urllib.parse.quote(clearart_png, safe='')}/")
                                fallback_paths.append(f"image://{urllib.parse.quote(clearart_jpg, safe='')}/")
                            elif art_type == "banner":
                                fallback_paths.append(f"image://{urllib.parse.quote(banner_png, safe='')}/")
                                fallback_paths.append(f"image://{urllib.parse.quote(banner_jpg, safe='')}/")
                            elif art_type == "front":
                                fallback_paths.append(f"image://{urllib.parse.quote(Front_jpg, safe='')}/")
                                fallback_paths.append(f"image://{urllib.parse.quote(Front_png, safe='')}/")
                                fallback_paths.append(f"image://{urllib.parse.quote(Front_jpeg, safe='')}/")
                                fallback_paths.append(f"image://{urllib.parse.quote(front_jpg, safe='')}/")
                                fallback_paths.append(f"image://{urllib.parse.quote(front_png, safe='')}/")
                                fallback_paths.append(f"image://{urllib.parse.quote(front_jpeg, safe='')}/")
                            elif art_type == "back":
                                fallback_paths.append(f"image://{urllib.parse.quote(Back_jpg, safe='')}/")
                                fallback_paths.append(f"image://{urllib.parse.quote(Back_png, safe='')}/")
                                fallback_paths.append(f"image://{urllib.parse.quote(Back_jpeg, safe='')}/")
                                fallback_paths.append(f"image://{urllib.parse.quote(back_jpg, safe='')}/")
                                fallback_paths.append(f"image://{urllib.parse.quote(back_png, safe='')}/")
                                fallback_paths.append(f"image://{urllib.parse.quote(back_jpeg, safe='')}/")
                            elif art_type == "discart":
                                fallback_paths.append(f"image://{urllib.parse.quote(discart_png, safe='')}/")
                                fallback_paths.append(f"image://{urllib.parse.quote(discart_jpg, safe='')}/")
                                fallback_paths.append(f"image://{urllib.parse.quote(discart_jpeg, safe='')}/")
                                fallback_paths.append(f"image://{urllib.parse.quote(Discart_png, safe='')}/")
                                fallback_paths.append(f"image://{urllib.parse.quote(Discart_jpg, safe='')}/")
                                fallback_paths.append(f"image://{urllib.parse.quote(Discart_jpeg, safe='')}/")
                            
                            logger.debug(f"Level {level}: Checking {parent_path} for {art_type}")
                            
                            current_path = parent_path
                        
                        # Try each fallback path
                        for fallback_path in fallback_paths:
                            try:
                                logger.debug(f"Trying fallback path: {fallback_path}")
                                image_url = _kodi_image_download_url(fallback_path, server)
                                if image_url:
                                    logger.debug(f"Found fallback path for {art_type}: {image_url}")
                                    break
                            except Exception as e:
                                logger.debug(f"Fallback path failed for {art_type}: {e}")
                                pass
                    except Exception as e:
                        logger.debug(f"Failed to construct fallback paths for {art_type}: {e}")
            
            if not image_url:
                logger.error(f"No valid download path found for {art_type}")
                continue

        filename = _target_filename(art_type)
        local_path = os.path.join(_c.ART_TMP_DIR, filename)

        if os.path.exists(local_path) and os.path.getsize(local_path) > 0:
            if _fanart_size_ok(local_path, art_type):
                _commit_art(art_type, filename, raw_path)
                logger.debug(f"Reusing cached artwork {local_path}")
                if progress_cb and total_tasks:
                    update_art_progress(label)
                continue
            try:
                os.remove(local_path)
            except Exception:
                pass

        if use_parallel:
            http_jobs.append({
                "art_key": art_type,
                "image_url": image_url,
                "local_path": local_path,
                "filename": filename,
                "raw_path": raw_path,
                "label": label,
            })
            continue

        try:
            # Use authentication only for Kodi internal URLs
            if image_url.startswith(server['host']):
                logger.debug(f"Downloading with auth: {image_url}")
                r = requests.get(image_url, auth=server['auth'], timeout=5)
            else:
                logger.debug(f"Downloading without auth: {image_url}")
                r = requests.get(image_url, timeout=5)
            r.raise_for_status()
            with open(local_path, "wb") as f:
                f.write(r.content)
            if _fanart_size_ok(local_path, art_type):
                _commit_art(art_type, filename, raw_path)
                logger.info(f"Downloaded {art_type} to {local_path}")
            else:
                logger.info(f"Fanart {art_type} filtered by size threshold")
        except Exception as e:
            logger.error(f"Failed to download {art_type}: {e}")
            
            # If download failed with 401, try fallback paths for artist artwork
            if "401" in str(e) and art_type in ["fanart", "clearlogo", "clearart", "banner", "front", "back", "discart"]:
                logger.debug(f"Download failed with 401, trying fallback paths for {art_type}")
                # Try to construct fallback paths based on album/artist folder structure
                current_file = item.get("file", "")
                if _is_remote_song_path(current_file):
                    try:
                        # Traverse upwards to find directories that contain fanart files
                        # This is the most reliable way since fanart is typically only in artist directories
                        current_path = current_file
                        fallback_paths = []
                        
                        logger.debug(f"Traversing upwards from: {current_path}")
                        
                        # Traverse upwards to find directories with fanart files
                        for level in range(8):  # Limit to 8 levels up to avoid infinite loops
                            parent_path = os.path.dirname(current_path)
                            if parent_path == current_path:  # Reached root
                                break
                            
                            dir_name = os.path.basename(parent_path)
                            
                            # Skip system directories
                            if any(x in dir_name.upper() for x in ['MEDIA', 'MUSIC', 'VIDEO', 'TV', 'MOVIES']):
                                current_path = parent_path
                                pass
                            
                            # Try to find fanart files in this directory
                            # This works for both artist directories (which have fanart) and album directories (which might have other artwork)
                            fanart_png = f"{parent_path}/fanart.png"
                            fanart_jpg = f"{parent_path}/fanart.jpg"
                            clearlogo_png = f"{parent_path}/clearlogo.png"
                            clearlogo_jpg = f"{parent_path}/clearlogo.jpg"
                            clearlogo_webp = f"{parent_path}/clearlogo.webp"
                            logo_png = f"{parent_path}/logo.png"
                            logo_jpg = f"{parent_path}/logo.jpg"
                            clearart_png = f"{parent_path}/clearart.png"
                            clearart_jpg = f"{parent_path}/clearart.jpg"
                            banner_png = f"{parent_path}/banner.png"
                            banner_jpg = f"{parent_path}/banner.jpg"
                            front_png = f"{parent_path}/front.png"
                            front_jpg = f"{parent_path}/front.jpg"
                            front_jpeg = f"{parent_path}/front.jpeg"
                            Front_png = f"{parent_path}/Front.png"
                            Front_jpg = f"{parent_path}/Front.jpg"
                            Front_jpeg = f"{parent_path}/Front.jpeg"
                            back_png = f"{parent_path}/back.png"
                            back_jpg = f"{parent_path}/back.jpg"
                            back_jpeg = f"{parent_path}/back.jpeg"
                            Back_png = f"{parent_path}/Back.png"
                            Back_jpg = f"{parent_path}/Back.jpg"
                            Back_jpeg = f"{parent_path}/Back.jpeg"
                            discart_png = f"{parent_path}/discart.png"
                            discart_jpg = f"{parent_path}/discart.jpg"
                            discart_jpeg = f"{parent_path}/discart.jpeg"
                            Discart_png = f"{parent_path}/Discart.png"
                            Discart_jpg = f"{parent_path}/Discart.jpg"
                            Discart_jpeg = f"{parent_path}/Discart.jpeg"
                            
                            # Add paths for the specific art type we're looking for
                            if art_type == "fanart":
                                fallback_paths.append(f"image://{urllib.parse.quote(fanart_png, safe='')}/")
                                fallback_paths.append(f"image://{urllib.parse.quote(fanart_jpg, safe='')}/")
                                # First, try extrafanart folder (fanart.jpg, fanart2.jpg, etc.)
                                for i in range(1, 10):  # fanart1 through fanart9 in extrafanart folder
                                    extrafanart_png = f"{parent_path}/extrafanart/fanart{i}.png"
                                    extrafanart_jpg = f"{parent_path}/extrafanart/fanart{i}.jpg"
                                    extrafanart_jpeg = f"{parent_path}/extrafanart/fanart{i}.jpeg"
                                    fallback_paths.extend([
                                        f"image://{urllib.parse.quote(extrafanart_png, safe='')}/",
                                        f"image://{urllib.parse.quote(extrafanart_jpg, safe='')}/",
                                        f"image://{urllib.parse.quote(extrafanart_jpeg, safe='')}/"
                                    ])
                                
                                # Also try the main fanart.jpg in extrafanart folder
                                extrafanart_main_png = f"{parent_path}/extrafanart/fanart.png"
                                extrafanart_main_jpg = f"{parent_path}/extrafanart/fanart.jpg"
                                extrafanart_main_jpeg = f"{parent_path}/extrafanart/fanart.jpeg"
                                fallback_paths.extend([
                                    f"image://{urllib.parse.quote(extrafanart_main_png, safe='')}/",
                                    f"image://{urllib.parse.quote(extrafanart_main_jpg, safe='')}/",
                                    f"image://{urllib.parse.quote(extrafanart_main_jpeg, safe='')}/"
                                ])
                                
                                # Also try fanart variants (fanart1, fanart2, etc.)
                                for i in range(1, 10):  # fanart1 through fanart9
                                    fanart_var_png = f"{parent_path}/fanart{i}.png"
                                    fanart_var_jpg = f"{parent_path}/fanart{i}.jpg"
                                    fanart_var_jpeg = f"{parent_path}/fanart{i}.jpeg"
                                    fallback_paths.extend([
                                        f"image://{urllib.parse.quote(fanart_var_png, safe='')}/",
                                        f"image://{urllib.parse.quote(fanart_var_jpg, safe='')}/",
                                        f"image://{urllib.parse.quote(fanart_var_jpeg, safe='')}/"
                                    ])
                            elif art_type == "clearlogo":
                                for candidate in (
                                    clearlogo_png, clearlogo_jpg, clearlogo_webp, logo_png, logo_jpg,
                                ):
                                    fallback_paths.append(f"image://{urllib.parse.quote(candidate, safe='')}/")
                            elif art_type == "clearart":
                                fallback_paths.append(f"image://{urllib.parse.quote(clearart_png, safe='')}/")
                                fallback_paths.append(f"image://{urllib.parse.quote(clearart_jpg, safe='')}/")
                            elif art_type == "banner":
                                fallback_paths.append(f"image://{urllib.parse.quote(banner_png, safe='')}/")
                                fallback_paths.append(f"image://{urllib.parse.quote(banner_jpg, safe='')}/")
                            elif art_type == "front":
                                fallback_paths.append(f"image://{urllib.parse.quote(Front_jpg, safe='')}/")
                                fallback_paths.append(f"image://{urllib.parse.quote(Front_png, safe='')}/")
                                fallback_paths.append(f"image://{urllib.parse.quote(Front_jpeg, safe='')}/")
                                fallback_paths.append(f"image://{urllib.parse.quote(front_jpg, safe='')}/")
                                fallback_paths.append(f"image://{urllib.parse.quote(front_png, safe='')}/")
                                fallback_paths.append(f"image://{urllib.parse.quote(front_jpeg, safe='')}/")
                            elif art_type == "back":
                                fallback_paths.append(f"image://{urllib.parse.quote(Back_jpg, safe='')}/")
                                fallback_paths.append(f"image://{urllib.parse.quote(Back_png, safe='')}/")
                                fallback_paths.append(f"image://{urllib.parse.quote(Back_jpeg, safe='')}/")
                                fallback_paths.append(f"image://{urllib.parse.quote(back_jpg, safe='')}/")
                                fallback_paths.append(f"image://{urllib.parse.quote(back_png, safe='')}/")
                                fallback_paths.append(f"image://{urllib.parse.quote(back_jpeg, safe='')}/")
                            elif art_type == "discart":
                                fallback_paths.append(f"image://{urllib.parse.quote(discart_png, safe='')}/")
                                fallback_paths.append(f"image://{urllib.parse.quote(discart_jpg, safe='')}/")
                                fallback_paths.append(f"image://{urllib.parse.quote(discart_jpeg, safe='')}/")
                                fallback_paths.append(f"image://{urllib.parse.quote(Discart_png, safe='')}/")
                                fallback_paths.append(f"image://{urllib.parse.quote(Discart_jpg, safe='')}/")
                                fallback_paths.append(f"image://{urllib.parse.quote(Discart_jpeg, safe='')}/")
                            
                            logger.debug(f"Level {level}: Checking {parent_path} for {art_type}")
                            
                            current_path = parent_path
                        
                        # Try each fallback path
                        for fallback_path in fallback_paths:
                            try:
                                logger.debug(f"Trying fallback path: {fallback_path}")
                                response = kodi_rpc("Files.PrepareDownload", {"path": fallback_path})
                                if not response:
                                    continue
                                details = response.get("result", {}).get("details", {})
                                token = details.get("token")
                                path = details.get("path")
                                
                                if token:
                                    basename = _art_path_basename(fallback_path)
                                    fallback_image_url = f"{server['host']}/vfs/{token}/{urllib.parse.quote(basename)}"
                                elif path:
                                    fallback_image_url = f"{server['host']}/{path}"
                                else:
                                    # No usable download target — never reuse the previous candidate's URL
                                    continue

                                # Try to download the fallback image
                                logger.debug(f"Trying to download fallback: {fallback_image_url}")
                                r = requests.get(fallback_image_url, auth=server['auth'], timeout=5)
                                r.raise_for_status()
                                with open(local_path, "wb") as f:
                                    f.write(r.content)
                                if _fanart_size_ok(local_path, art_type):
                                    _commit_art(art_type, filename, fallback_path)
                                    logger.info(f"Downloaded {art_type} from fallback path to {local_path}")
                                    break  # Success, stop trying other fallback paths
                                logger.info(f"Fanart {art_type} filtered by size threshold")
                            except Exception as fallback_e:
                                logger.debug(f"Fallback path failed for {art_type}: {fallback_e}")
                                pass
                    except Exception as fallback_construct_e:
                        logger.debug(f"Failed to construct fallback paths for {art_type}: {fallback_construct_e}")
        if progress_cb and total_tasks:
            update_art_progress(label)

    if http_jobs:
        for job, ok in _download_urls_parallel(http_jobs, server, _fanart_size_ok):
            if ok:
                _commit_art(job["art_key"], job["filename"], job.get("raw_path"))
                logger.info("Downloaded %s to %s", job["art_key"], job["local_path"])
            if progress_cb and total_tasks:
                update_art_progress(job.get("label") or "Loading artwork")

    # Progressive fanart: ensure one primary on critical path; defer the rest.
    primary_key = select_primary_fanart_key(media_type, fanart_variants, downloaded)

    def _try_reuse_or_download_one(variant_key, variant_path):
        """Reuse local/share file or download a single fanart for first paint."""
        if variant_key in downloaded:
            return True
        filename = _target_filename(variant_key)
        local_path = os.path.join(_c.ART_TMP_DIR, filename)
        if os.path.exists(local_path) and os.path.getsize(local_path) > 0:
            if _fanart_size_ok(local_path, variant_key):
                _commit_art(variant_key, filename, variant_path)
                return True
            try:
                os.remove(local_path)
            except Exception:
                pass
        image_url = None
        if variant_path and (str(variant_path).startswith("http://") or str(variant_path).startswith("https://")):
            image_url = variant_path
        else:
            image_url = _kodi_image_download_url(variant_path, server)
        if not image_url:
            logger.debug("No download URL for primary fanart %s", variant_key)
            return False
        try:
            _http_get_to_file(image_url, local_path, server)
            if _fanart_size_ok(local_path, variant_key):
                _commit_art(variant_key, filename, variant_path)
                logger.info("Downloaded primary fanart %s to %s", variant_key, local_path)
                return True
            logger.info("Primary fanart %s filtered by size threshold", variant_key)
        except Exception as exc:
            logger.error("Failed to download primary fanart %s: %s", variant_key, exc)
        return False

    if primary_key and primary_key not in downloaded and primary_key in fanart_variants:
        _try_reuse_or_download_one(primary_key, fanart_variants[primary_key])

    pending_fanarts = []
    for variant_key, variant_path in fanart_variants.items():
        if variant_key in downloaded:
            continue
        filename = _target_filename(variant_key)
        local_path = os.path.join(_c.ART_TMP_DIR, filename)
        if os.path.exists(local_path) and os.path.getsize(local_path) > 0:
            if _fanart_size_ok(local_path, variant_key):
                _commit_art(variant_key, filename, variant_path)
                continue
        pending_fanarts.append({"key": variant_key, "path": variant_path})

    share_out["pending_fanarts"] = pending_fanarts
    final_fanart_count = len([k for k in downloaded.keys() if k.startswith(("fanart", "extrafanart"))])
    logger.debug("Final downloaded fanart count: %s (pending=%s)", final_fanart_count, len(pending_fanarts))
    logger.debug("Downloaded fanart keys: %s", [k for k in downloaded.keys() if k.startswith(("fanart", "extrafanart"))])
    
    return downloaded, share_out

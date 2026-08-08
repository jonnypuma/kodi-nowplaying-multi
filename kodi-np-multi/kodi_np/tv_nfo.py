"""TV show / season metadata from Kodi library and local NFO files."""
from __future__ import annotations

import logging
import re
import urllib.parse
import xml.etree.ElementTree as ET

import requests

from kodi_np import config as _c
from kodi_np.rpc import kodi_rpc
from kodi_np.servers import get_active_server

logger = logging.getLogger("kodi.nowplaying")


def _normalize_path(path: str) -> str:
    if not path:
        return ""
    cleaned = path.replace("\\", "/").rstrip("/")
    if cleaned.startswith("image://"):
        cleaned = cleaned[len("image://") :]
    return cleaned.rstrip("/")


def _dirname(path: str) -> str:
    cleaned = _normalize_path(path)
    if "/" not in cleaned:
        return ""
    return cleaned.rsplit("/", 1)[0]


def _basename(path: str) -> str:
    cleaned = _normalize_path(path)
    if "/" not in cleaned:
        return cleaned
    return cleaned.rsplit("/", 1)[-1]


def show_root_from_episode_file(episode_file: str) -> str:
    """Best-effort TV show root directory from an episode media path."""
    cleaned = _normalize_path(episode_file)
    if not cleaned:
        return ""
    match = re.search(r"(?i)(.+)/(?:season\s*\d+|s\d+)/[^/]+$", cleaned)
    if match:
        return match.group(1)
    parent = _dirname(cleaned)
    grandparent = _dirname(parent)
    return grandparent if grandparent and grandparent != parent else parent


def season_folder_from_episode_file(episode_file: str) -> str:
    cleaned = _normalize_path(episode_file)
    if not cleaned:
        return ""
    match = re.search(r"(?i)(.+/(?:season\s*\d+|s\d+))/[^/]+$", cleaned)
    if match:
        return match.group(1)
    return ""


def season_nfo_candidate_paths(episode_file: str, season: int | None) -> list[str]:
    """Season folder season.nfo first, then show-root seasonNN.nfo."""
    candidates: list[str] = []
    season_folder = season_folder_from_episode_file(episode_file)
    if season_folder:
        candidates.append(f"{season_folder}/season.nfo")
    show_root = show_root_from_episode_file(episode_file)
    if show_root and season is not None:
        try:
            sn = int(season)
        except (TypeError, ValueError):
            sn = None
        if sn is not None:
            candidates.append(f"{show_root}/season{sn:02d}.nfo")
            candidates.append(f"{show_root}/season{sn}.nfo")
    # Preserve order, drop duplicates
    seen = set()
    out = []
    for path in candidates:
        key = path.lower()
        if key not in seen:
            seen.add(key)
            out.append(path)
    return out


def tvshow_nfo_candidate_paths(episode_file: str, showtitle: str = "") -> list[str]:
    show_root = show_root_from_episode_file(episode_file)
    if not show_root:
        return []
    candidates = [f"{show_root}/tvshow.nfo"]
    if showtitle:
        safe = showtitle.strip()
        if safe:
            candidates.append(f"{show_root}/{safe}.nfo")
    folder_name = _basename(show_root)
    if folder_name:
        candidates.append(f"{show_root}/{folder_name}.nfo")
    seen = set()
    out = []
    for path in candidates:
        key = path.lower()
        if key not in seen:
            seen.add(key)
            out.append(path)
    return out


def _parse_nfo_xml(text: str) -> ET.Element | None:
    if not text or not text.strip():
        return None
    try:
        return ET.fromstring(text)
    except ET.ParseError:
        # Some NFO files include an XML declaration with odd encoding — strip and retry.
        stripped = re.sub(r"^\s*<\?xml[^>]*\?>", "", text, count=1, flags=re.IGNORECASE)
        try:
            return ET.fromstring(stripped)
        except ET.ParseError as exc:
            logger.debug("NFO XML parse failed: %s", exc)
            return None


def plot_from_nfo_text(text: str) -> str:
    root = _parse_nfo_xml(text)
    if root is None:
        return ""
    node = root.find("plot")
    if node is not None and (node.text or "").strip():
        return (node.text or "").strip()
    return ""


def tagline_from_nfo_text(text: str) -> str:
    root = _parse_nfo_xml(text)
    if root is None:
        return ""
    node = root.find("tagline")
    if node is not None and (node.text or "").strip():
        return (node.text or "").strip()
    return ""


def named_seasons_from_nfo_text(text: str) -> dict[int, str]:
    root = _parse_nfo_xml(text)
    if root is None:
        return {}
    out: dict[int, str] = {}
    for node in root.findall("namedseason"):
        num_raw = node.get("number")
        label = (node.text or "").strip()
        if num_raw is None or not label:
            continue
        try:
            out[int(num_raw)] = label
        except (TypeError, ValueError):
            continue
    return out


def format_season_plot_heading(
    season: int | None,
    named_seasons: dict[int, str] | None,
    label_mode: str = "number_and_named",
) -> str:
    """Build heading like 'Season 2 season_2.0 Plot' per user preference."""
    if season is None:
        return "Season Plot"
    try:
        sn = int(season)
    except (TypeError, ValueError):
        return "Season Plot"
    named = (named_seasons or {}).get(sn, "").strip()
    if label_mode == "named_only" and named:
        return f"Season {named} Plot"
    if label_mode == "named_only":
        return f"Season {sn} Plot"
    if named:
        return f"Season {sn} {named} Plot"
    return f"Season {sn} Plot"


def _kodi_vfs_download_url(file_path: str, server: dict, server_id=None) -> str | None:
    """PrepareDownload URL for a plain library file (NFO, etc.) — not image://."""
    cleaned = _normalize_path(file_path)
    if not cleaned or not server:
        return None
    if cleaned.startswith("http://") or cleaned.startswith("https://"):
        return cleaned

    host = (server.get("host") or "").rstrip("/")
    candidates = [cleaned]
    if not cleaned.endswith("/"):
        candidates.append(f"{cleaned}/")

    seen = set()
    for path_arg in candidates:
        if path_arg in seen:
            continue
        seen.add(path_arg)
        try:
            response = kodi_rpc(
                "Files.PrepareDownload",
                {"path": path_arg},
                server_id=server_id,
            )
        except Exception as exc:
            logger.debug("PrepareDownload failed for %s: %s", path_arg, exc)
            continue
        if not response or response.get("error") or not response.get("result"):
            continue
        details = response.get("result", {}).get("details") or {}
        token = details.get("token")
        path = details.get("path")
        if token:
            basename = _basename(cleaned) or "file"
            return f"{host}/vfs/{token}/{urllib.parse.quote(basename)}"
        if path:
            return f"{host}/{path.lstrip('/')}"
    return None


def _season_id_for(tvshow_id: int, season: int, server_id=None) -> int | None:
    try:
        response = kodi_rpc(
            "VideoLibrary.GetSeasons",
            {
                "tvshowid": int(tvshow_id),
                "properties": ["season"],
            },
            server_id=server_id,
        )
        if not response or not response.get("result"):
            return None
        for entry in response.get("result", {}).get("seasons") or []:
            if entry.get("season") == int(season):
                season_id = entry.get("seasonid")
                return int(season_id) if season_id is not None else None
    except Exception as exc:
        logger.debug("GetSeasons failed: %s", exc)
    return None


def read_text_file_via_kodi(file_path: str, server_id=None, max_bytes: int = 512_000) -> str:
    """Read a remote/local media library text file through Kodi VFS."""
    server = get_active_server() if server_id is None else _c.KODI_SERVERS.get(server_id)
    if not server or not file_path:
        return ""
    url = _kodi_vfs_download_url(file_path, server, server_id=server_id)
    if not url:
        return ""
    try:
        if url.startswith(server.get("host") or ""):
            response = requests.get(url, auth=server.get("auth"), timeout=8)
        else:
            response = requests.get(url, timeout=8)
        response.raise_for_status()
        content = response.content[:max_bytes]
        for encoding in ("utf-8", "utf-8-sig", "latin-1"):
            try:
                return content.decode(encoding)
            except UnicodeDecodeError:
                continue
        return content.decode("utf-8", errors="replace")
    except Exception as exc:
        logger.debug("Failed to read text file %s: %s", file_path, exc)
        return ""


def _first_nfo_plot(candidates: list[str], server_id=None) -> str:
    for path in candidates:
        text = read_text_file_via_kodi(path, server_id=server_id)
        plot = plot_from_nfo_text(text)
        if plot:
            return plot
    return ""


def resolve_season_plot(
    episode_file: str,
    season: int | None,
    tvshow_id: int | None,
    server_id=None,
    cached_plot: str | None = None,
) -> str:
    if cached_plot and cached_plot.strip():
        return cached_plot.strip()
    if tvshow_id is not None and season is not None:
        try:
            season_id = _season_id_for(int(tvshow_id), int(season), server_id=server_id)
            if season_id is not None:
                response = kodi_rpc(
                    "VideoLibrary.GetSeasonDetails",
                    {
                        "seasonid": season_id,
                        "properties": ["plot"],
                    },
                    server_id=server_id,
                )
                if response and response.get("result"):
                    plot = (response["result"].get("seasondetails") or {}).get("plot") or ""
                    if isinstance(plot, str) and plot.strip():
                        return plot.strip()
        except Exception as exc:
            logger.debug("GetSeasonDetails plot failed: %s", exc)
    return _first_nfo_plot(season_nfo_candidate_paths(episode_file, season), server_id=server_id)


def resolve_tvshow_extras(
    episode_file: str,
    showtitle: str,
    season: int | None,
    tvshow_id: int | None,
    server_id=None,
    prior_meta: dict | None = None,
) -> dict:
    """Tagline, named seasons, and season plot for episode pages."""
    prior_meta = prior_meta or {}
    named_seasons = dict(prior_meta.get("named_seasons") or {})
    tagline = (prior_meta.get("tagline") or "").strip()
    season_plots = dict(prior_meta.get("season_plots") or {})

    if episode_file and (not tagline or not named_seasons):
        for nfo_path in tvshow_nfo_candidate_paths(episode_file, showtitle):
            text = read_text_file_via_kodi(nfo_path, server_id=server_id)
            if not text:
                continue
            if not tagline:
                tagline = tagline_from_nfo_text(text)
            if not named_seasons:
                named_seasons = named_seasons_from_nfo_text(text)
            if tagline and named_seasons:
                break

    season_key = str(season) if season is not None else ""
    cached_season_plot = season_plots.get(season_key, "")
    season_plot = resolve_season_plot(
        episode_file,
        season,
        tvshow_id,
        server_id=server_id,
        cached_plot=cached_season_plot,
    )
    if season_key and season_plot:
        season_plots[season_key] = season_plot

    return {
        "tagline": tagline,
        "named_seasons": named_seasons,
        "season_plot": season_plot,
        "season_plots": season_plots,
    }

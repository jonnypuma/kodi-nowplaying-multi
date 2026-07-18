from flask import Flask, render_template_string, request, jsonify, send_file, session, has_request_context
import requests
import os
import urllib.parse
import uuid
import re
import json
import logging
import threading
import time
import hashlib
from html import escape
from pathlib import Path
from logging_config import configure_logging
from parser import route_media_display

configure_logging()
logger = logging.getLogger("kodi.nowplaying")

APP_DIR = Path(__file__).resolve().parent
app = Flask(__name__, template_folder=str(APP_DIR / "templates"))
app.secret_key = os.getenv("FLASK_SECRET_KEY", uuid.uuid4().hex)  # For session management
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024

load_jobs = {}
load_lock = threading.Lock()
active_server_override = threading.local()
LOAD_JOB_TTL_SECONDS = int(os.getenv("LOAD_JOB_TTL_SECONDS", "600"))  # drop finished jobs after 10m
LOAD_JOB_STALE_SECONDS = int(os.getenv("LOAD_JOB_STALE_SECONDS", "1800"))  # drop any job after 30m
LOAD_JOB_MAX = int(os.getenv("LOAD_JOB_MAX", "50"))

# Per-server now-playing cache (HTML + art + metadata)
nowplaying_cache = {}
cache_lock = threading.Lock()
cache_building = set()
CACHE_POLLER_ENABLED = os.getenv("CACHE_POLLER_ENABLED", "1") != "0"
CACHE_POLLER_INTERVAL = float(os.getenv("CACHE_POLLER_INTERVAL", "12"))
THUMB_ART_PRIORITY = ("poster", "front", "season.poster", "thumbnail", "fanart", "banner")
CACHE_PROBE_FAIL_CLEAR_AFTER = int(os.getenv("CACHE_PROBE_FAIL_CLEAR_AFTER", "3"))
SERVER_FAIL_BACKOFF_AFTER = int(os.getenv("SERVER_FAIL_BACKOFF_AFTER", "3"))
SERVER_FAIL_BACKOFF_SECONDS = int(os.getenv("SERVER_FAIL_BACKOFF_SECONDS", "300"))  # 5 minutes
KODI_RPC_TIMEOUT = float(os.getenv("KODI_RPC_TIMEOUT", "5"))

# Per-server unreachable backoff: stop hammering offline hosts
server_backoff = {}  # server_id -> {"fail_count", "backoff_until", "last_error"}
server_backoff_lock = threading.Lock()

HEADERS = {"Content-Type": "application/json"}


def prune_load_jobs(force_id=None):
    """Remove finished/stale load jobs and optionally drop a specific job id."""
    now = time.time()
    with load_lock:
        if force_id is not None:
            load_jobs.pop(force_id, None)

        expired = []
        for job_id, job in load_jobs.items():
            updated = job.get("updated_at") or job.get("created_at") or 0
            status = job.get("status")
            age = now - updated
            if status in ("done", "error", "consumed") and age >= LOAD_JOB_TTL_SECONDS:
                expired.append(job_id)
            elif age >= LOAD_JOB_STALE_SECONDS:
                expired.append(job_id)
        for job_id in expired:
            load_jobs.pop(job_id, None)

        # Hard cap: drop oldest finished jobs first, then oldest overall
        if len(load_jobs) > LOAD_JOB_MAX:
            ordered = sorted(
                load_jobs.items(),
                key=lambda item: (
                    0 if item[1].get("status") in ("done", "error", "consumed") else 1,
                    item[1].get("updated_at") or item[1].get("created_at") or 0,
                ),
            )
            overflow = len(load_jobs) - LOAD_JOB_MAX
            for job_id, _ in ordered[:overflow]:
                load_jobs.pop(job_id, None)

def html_escape(value):
    return escape(str(value), quote=True) if value is not None else ""

# Parse multiple Kodi servers from environment variables
def parse_kodi_servers():
    """Parse Kodi servers from environment variables (KODI_HOST_1, KODI_HOST_2, etc.)"""
    servers = {}
    i = 1
    while True:
        host_key = f"KODI_HOST_{i}"
        user_key = f"KODI_USERNAME_{i}"
        pass_key = f"KODI_PASSWORD_{i}"
        label_key = f"KODI_HOST_LABEL_{i}"
        
        host = os.getenv(host_key)
        if not host:
            break
        
        username = os.getenv(user_key, "")
        password = os.getenv(pass_key, "")
        label = (os.getenv(label_key) or "").strip()
        
        # Extract IP from host for sorting
        ip_match = re.search(r'(\d+\.\d+\.\d+\.\d+)', host)
        ip = ip_match.group(1) if ip_match else host
        
        servers[i] = {
            "id": i,
            "host": host,
            "username": username,
            "password": password,
            "auth": (username, password) if username else None,
            "ip": ip,
            "label": label,
        }
        i += 1
    
    # If no numbered servers found, try legacy single server format
    if not servers:
        legacy_host = os.getenv("KODI_HOST")
        if legacy_host:
            legacy_user = os.getenv("KODI_USER", os.getenv("KODI_USERNAME", ""))
            legacy_pass = os.getenv("KODI_PASS", os.getenv("KODI_PASSWORD", ""))
            legacy_label = (os.getenv("KODI_HOST_LABEL") or "").strip()
            ip_match = re.search(r'(\d+\.\d+\.\d+\.\d+)', legacy_host)
            ip = ip_match.group(1) if ip_match else legacy_host
            
            servers[1] = {
                "id": 1,
                "host": legacy_host,
                "username": legacy_user,
                "password": legacy_pass,
                "auth": (legacy_user, legacy_pass) if legacy_user else None,
                "ip": ip,
                "label": legacy_label,
            }
    
    return servers

def server_display_name(server):
    """Human-friendly server name: label (ip) if labeled, otherwise IP/host."""
    if not server:
        return ""
    label = (server.get("label") or "").strip()
    ip = (server.get("ip") or "").strip()
    if label and ip:
        return f"{label} ({ip})"
    if label:
        return label
    return ip or server.get("host") or f"Server {server.get('id', '')}"


def make_playback_fingerprint(item):
    """Stable id for the currently playing item (changes when media changes)."""
    if not item:
        return None
    media_type = item.get("type") or "unknown"
    item_id = item.get("id") or item.get("songid") or item.get("movieid") or item.get("episodeid") or ""
    file_path = item.get("file") or ""
    title = item.get("title") or ""
    show = item.get("showtitle") or ""
    season = item.get("season")
    episode = item.get("episode")
    return f"{media_type}:{item_id}:{file_path}:{title}:{show}:{season}:{episode}"


def cache_session_id_for(server_id, fingerprint):
    return hashlib.md5(f"{server_id}:{fingerprint}".encode("utf-8")).hexdigest()


def pick_thumb_filename(downloaded_art):
    if not isinstance(downloaded_art, dict):
        return None
    for key in THUMB_ART_PRIORITY:
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
    with cache_lock:
        for entry in nowplaying_cache.values():
            for name in entry.get("art_files") or []:
                protected.add(name)
            thumb = entry.get("thumb_file")
            if thumb:
                protected.add(thumb)
    return protected


def get_cache_entry(server_id):
    with cache_lock:
        entry = nowplaying_cache.get(server_id)
        return dict(entry) if entry else None


def set_cache_entry(server_id, **fields):
    with cache_lock:
        entry = nowplaying_cache.get(server_id) or {}
        entry.update(fields)
        entry["updated_at"] = time.time()
        nowplaying_cache[server_id] = entry
        return dict(entry)


def clear_cache_playback(server_id, status=None):
    """Drop HTML/art for a server that is idle/offline; keep lightweight status fields."""
    server = KODI_SERVERS.get(server_id) or {}
    base = {
        "id": server_id,
        "host": server.get("host"),
        "ip": server.get("ip"),
        "label": server.get("label") or "",
        "name": server_display_name(server) if server else f"Server {server_id}",
        "connected": bool(status and status.get("connected")),
        "playing": False,
        "paused": False,
        "title": None,
        "media_type": None,
        "error": (status or {}).get("error"),
        "fingerprint": None,
        "html": None,
        "session_id": None,
        "art_files": [],
        "thumb_file": None,
        "thumb": None,
        "cache_ready": False,
    }
    if status:
        base["connected"] = bool(status.get("connected"))
        base["error"] = status.get("error")
    set_cache_entry(server_id, **base)


def store_playing_cache(server_id, payload, status=None):
    """Persist a successful now-playing build for instant serve + overview tiles."""
    server = KODI_SERVERS.get(server_id) or {}
    downloaded_art = payload.get("downloaded_art") or {}
    art_files = [name for name in downloaded_art.values() if name]
    thumb_file = pick_thumb_filename(downloaded_art)
    title = payload.get("title")
    media_type = payload.get("media_type")
    if status and status.get("title"):
        title = status.get("title")
    if status and status.get("media_type"):
        media_type = status.get("media_type")
    set_cache_entry(
        server_id,
        id=server_id,
        host=server.get("host"),
        ip=server.get("ip"),
        label=server.get("label") or "",
        name=server_display_name(server) if server else f"Server {server_id}",
        connected=True,
        playing=True,
        paused=bool(payload.get("paused")),
        title=title,
        media_type=media_type,
        error=None,
        fingerprint=payload.get("fingerprint"),
        html=payload.get("html"),
        session_id=payload.get("session_id"),
        art_files=art_files,
        thumb_file=thumb_file,
        thumb=f"/media/{thumb_file}" if thumb_file else None,
        cache_ready=bool(payload.get("html")),
    )


def overview_from_cache(server_id):
    entry = get_cache_entry(server_id)
    if not entry:
        return None
    remaining = int(server_backoff_remaining(server_id))
    return {
        "id": server_id,
        "host": entry.get("host"),
        "ip": entry.get("ip"),
        "label": entry.get("label") or "",
        "name": entry.get("name") or "",
        "connected": bool(entry.get("connected")),
        "playing": bool(entry.get("playing")),
        "paused": bool(entry.get("paused")),
        "title": entry.get("title"),
        "media_type": entry.get("media_type"),
        "error": entry.get("error"),
        "thumb": entry.get("thumb"),
        "cache_ready": bool(entry.get("cache_ready") and entry.get("html")),
        "backoff_remaining": remaining,
    }


def probe_playback_fingerprint(server_id):
    """Cheap RPC to detect what (if anything) is playing on a server."""
    players_response = kodi_rpc("Player.GetActivePlayers", {}, server_id=server_id)
    if players_response is None:
        return {"connected": False, "playing": False, "fingerprint": None, "error": "Connection failed"}
    players = players_response.get("result") or []
    if not players:
        return {"connected": True, "playing": False, "fingerprint": None, "error": None, "paused": False}

    player_id = players[0].get("playerid")
    item_response = kodi_rpc(
        "Player.GetItem",
        {
            "playerid": player_id,
            "properties": ["title", "album", "artist", "showtitle", "season", "episode", "file"],
        },
        server_id=server_id,
    )
    props_response = kodi_rpc(
        "Player.GetProperties",
        {"playerid": player_id, "properties": ["speed"]},
        server_id=server_id,
    )
    item = {}
    if item_response and item_response.get("result"):
        item = item_response["result"].get("item") or {}
    speed = 0
    if props_response and props_response.get("result"):
        speed = props_response["result"].get("speed", 0)
    display_title, media_type = _format_overview_title(item)
    return {
        "connected": True,
        "playing": True,
        "paused": speed == 0,
        "fingerprint": make_playback_fingerprint(item),
        "title": display_title,
        "media_type": media_type,
        "error": None,
        "item": item,
    }


def _art_lock_for(server_id):
    with art_download_locks_guard:
        lock = art_download_locks.get(server_id)
        if lock is None:
            lock = threading.Lock()
            art_download_locks[server_id] = lock
        return lock


def _poll_state_for(server_id):
    with playback_poll_lock:
        state = playback_poll_state.get(server_id)
        if state is None:
            state = {
                "item_id": None,
                "last_check": 0.0,
                "idle_streak": 0,
                "error_streak": 0,
            }
            playback_poll_state[server_id] = state
        return state


def server_backoff_remaining(server_id):
    """Seconds left in unreachable backoff, or 0 if server may be contacted."""
    with server_backoff_lock:
        entry = server_backoff.get(server_id)
        if not entry:
            return 0
        remaining = float(entry.get("backoff_until") or 0) - time.time()
        return max(0, remaining)


def note_server_rpc_success(server_id):
    if server_id is None:
        return
    with server_backoff_lock:
        server_backoff.pop(server_id, None)


def note_server_rpc_failure(server_id, error):
    """Track consecutive connection failures; enter backoff after N in a row."""
    if server_id is None:
        return False
    err_text = str(error)
    # Only back off on transport / reachability problems, not JSON/RPC logic errors
    unreachable_markers = (
        "No route to host",
        "Connection refused",
        "ConnectTimeout",
        "Connection reset",
        "Connection aborted",
        "Failed to establish a new connection",
        "Max retries exceeded",
        "Name or service not known",
        "Network is unreachable",
        "timed out",
    )
    if not any(marker.lower() in err_text.lower() for marker in unreachable_markers):
        return False

    with server_backoff_lock:
        entry = server_backoff.get(server_id) or {"fail_count": 0, "backoff_until": 0, "last_error": ""}
        # Already in backoff — keep quiet
        if float(entry.get("backoff_until") or 0) > time.time():
            entry["last_error"] = err_text
            server_backoff[server_id] = entry
            return True

        entry["fail_count"] = int(entry.get("fail_count") or 0) + 1
        entry["last_error"] = err_text
        if entry["fail_count"] >= SERVER_FAIL_BACKOFF_AFTER:
            entry["backoff_until"] = time.time() + SERVER_FAIL_BACKOFF_SECONDS
            server_backoff[server_id] = entry
            logger.warning(
                "Server %s unreachable %s times — pausing polls for %ss (%s)",
                server_id,
                entry["fail_count"],
                SERVER_FAIL_BACKOFF_SECONDS,
                err_text.split("(Caused by")[0].strip()[:120],
            )
            return True
        server_backoff[server_id] = entry
        return False


def refresh_server_cache(server_id):
    """Update cache for one server: status always; full HTML rebuild when media changes."""
    if server_id not in KODI_SERVERS:
        return
    remaining = server_backoff_remaining(server_id)
    if remaining > 0:
        logger.debug("Skipping cache refresh for server %s (backoff %.0fs left)", server_id, remaining)
        return

    existing = get_cache_entry(server_id)
    try:
        probe = probe_playback_fingerprint(server_id)
    except Exception as e:
        logger.warning(f"Cache probe failed for server {server_id}: {e}")
        note_server_rpc_failure(server_id, e)
        fail_count = int((existing or {}).get("probe_fail_streak", 0)) + 1
        if existing and existing.get("html") and fail_count < CACHE_PROBE_FAIL_CLEAR_AFTER:
            set_cache_entry(server_id, probe_fail_streak=fail_count, error=str(e))
        else:
            clear_cache_playback(server_id, {"connected": False, "error": str(e)})
        return

    if not probe.get("connected"):
        note_server_rpc_failure(server_id, probe.get("error") or "Connection failed")
        fail_count = int((existing or {}).get("probe_fail_streak", 0)) + 1
        if existing and existing.get("html") and fail_count < CACHE_PROBE_FAIL_CLEAR_AFTER:
            set_cache_entry(
                server_id,
                connected=False,
                probe_fail_streak=fail_count,
                error=probe.get("error") or "Connection failed",
            )
        else:
            clear_cache_playback(server_id, probe)
        return

    note_server_rpc_success(server_id)

    if not probe.get("playing"):
        # Require a confirmed idle probe before wiping a warm cache (avoids blips while Kodi is busy)
        idle_streak = int((existing or {}).get("idle_streak", 0)) + 1
        if existing and existing.get("html") and idle_streak < CACHE_PROBE_FAIL_CLEAR_AFTER:
            set_cache_entry(server_id, idle_streak=idle_streak, probe_fail_streak=0)
            return
        clear_cache_playback(server_id, probe)
        return

    fingerprint = probe.get("fingerprint")
    existing = get_cache_entry(server_id)
    if (
        existing
        and existing.get("fingerprint") == fingerprint
        and existing.get("html")
        and existing.get("cache_ready")
    ):
        set_cache_entry(
            server_id,
            connected=True,
            playing=True,
            paused=bool(probe.get("paused")),
            title=probe.get("title") or existing.get("title"),
            media_type=probe.get("media_type") or existing.get("media_type"),
            error=None,
            cache_ready=True,
            probe_fail_streak=0,
            idle_streak=0,
        )
        return

    with cache_lock:
        if server_id in cache_building:
            return
        cache_building.add(server_id)

    # Only one full rebuild across all servers — art downloads hammer Kodi hard
    if not cache_rebuild_lock.acquire(blocking=False):
        with cache_lock:
            cache_building.discard(server_id)
        return

    try:
        session_id = cache_session_id_for(server_id, fingerprint) if fingerprint else uuid.uuid4().hex
        active_server_override.server_id = server_id
        try:
            with app.app_context():
                payload = build_nowplaying_html(session_id=session_id, as_payload=True)
        finally:
            if hasattr(active_server_override, "server_id"):
                del active_server_override.server_id

        if not payload or payload.get("idle") or not payload.get("html"):
            # Don't wipe a previous good cache on a flaky rebuild
            if existing and existing.get("html") and existing.get("fingerprint") == fingerprint:
                set_cache_entry(server_id, probe_fail_streak=0, idle_streak=0)
            else:
                clear_cache_playback(server_id, {"connected": True, "error": None})
            return

        if probe.get("title"):
            payload["title"] = probe["title"]
        if probe.get("media_type"):
            payload["media_type"] = probe["media_type"]
        if fingerprint and not payload.get("fingerprint"):
            payload["fingerprint"] = fingerprint
        payload["paused"] = bool(probe.get("paused"))
        store_playing_cache(server_id, payload, status=probe)
        set_cache_entry(server_id, probe_fail_streak=0, idle_streak=0)
        logger.info(f"Cached now-playing for server {server_id}: {payload.get('title')}")
    except Exception as e:
        logger.warning(f"Cache rebuild failed for server {server_id}: {e}")
        # Keep prior HTML if we have it for this fingerprint
        if existing and existing.get("html") and existing.get("fingerprint") == fingerprint:
            set_cache_entry(server_id, error=f"Cache build failed: {e}", probe_fail_streak=0)
        else:
            set_cache_entry(
                server_id,
                connected=True,
                playing=True,
                paused=bool(probe.get("paused")),
                title=probe.get("title"),
                media_type=probe.get("media_type"),
                error=f"Cache build failed: {e}",
                cache_ready=False,
                html=None,
            )
    finally:
        cache_rebuild_lock.release()
        with cache_lock:
            cache_building.discard(server_id)


def _cache_poller_loop():
    # Stagger first run slightly so Flask finishes starting
    time.sleep(2)
    while True:
        try:
            for server_id in list(KODI_SERVERS.keys()):
                try:
                    refresh_server_cache(server_id)
                except Exception as e:
                    logger.warning(f"Cache poller error for server {server_id}: {e}")
        except Exception as e:
            logger.warning(f"Cache poller loop error: {e}")
        time.sleep(CACHE_POLLER_INTERVAL)


# Parse all available servers
KODI_SERVERS = parse_kodi_servers()

def get_active_server():
    """Get the currently active server from session, or default to first server"""
    if has_request_context():
        server_id = session.get('active_server_id', 1)
        if server_id in KODI_SERVERS:
            return KODI_SERVERS[server_id]
    else:
        server_id = getattr(active_server_override, "server_id", None)
        if server_id in KODI_SERVERS:
            return KODI_SERVERS[server_id]
    # Fallback to first server
    if KODI_SERVERS:
        return list(KODI_SERVERS.values())[0]
    return None

ART_TYPES = ["poster", "front", "back", "fanart", "clearlogo", "clearart", "discart", "cdart", "banner", "season.poster", "thumbnail"]
ART_TMP_DIR = os.getenv("ART_TMP_DIR", "/app/tmp")
ART_TMP_PATH = Path(ART_TMP_DIR).resolve()
ART_FILE_PREFIX_LEN = 33  # 32 hex chars + underscore
ART_CLEANUP_AGE_SECONDS = 6 * 60 * 60
ARTWORK_FILENAME_RE = re.compile(r"^[0-9a-f]{32}_[A-Za-z0-9_.-]+\.jpg$")
STATIC_FILENAME_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
ART_TMP_PATH.mkdir(parents=True, exist_ok=True)

# Per-server playback poll state (avoids cross-server false "item changed" / idle flips)
playback_poll_state = {}
playback_poll_lock = threading.Lock()
EPISODE_CHECK_INTERVAL = 10  # Check for episode changes every 10 seconds
POLL_IDLE_CONFIRMATIONS = int(os.getenv("POLL_IDLE_CONFIRMATIONS", "3"))

# Serialize heavy artwork RPC traffic per Kodi host
art_download_locks = {}
art_download_locks_guard = threading.Lock()
cache_rebuild_lock = threading.Lock()  # only one full HTML/art rebuild at a time

# API endpoints for server management
@app.route("/api/servers")
def get_servers():
    """Get list of available Kodi servers, sorted by IP"""
    servers_list = []
    for server_id, server in KODI_SERVERS.items():
        servers_list.append({
            "id": server_id,
            "host": server["host"],
            "ip": server["ip"],
            "label": server.get("label") or "",
            "name": server_display_name(server),
        })
    
    # Sort by IP address
    servers_list.sort(key=lambda x: [int(part) for part in x["ip"].split(".") if part.isdigit()])
    
    return jsonify({"servers": servers_list})

@app.route("/api/test-connection/<int:server_id>")
def test_connection(server_id):
    """Test connection to a specific Kodi server"""
    if server_id not in KODI_SERVERS:
        return jsonify({"connected": False, "error": "Server not found"}), 404
    
    server = KODI_SERVERS[server_id]
    
    try:
        # Try a simple RPC call to test connection
        payload = {
            "jsonrpc": "2.0",
            "method": "JSONRPC.Version",
            "params": {},
            "id": 1
        }
        r = requests.post(f"{server['host']}/jsonrpc", headers=HEADERS, json=payload, auth=server['auth'], timeout=5)
        r.raise_for_status()
        response = r.json()
        
        if response.get("result"):
            return jsonify({"connected": True})
        else:
            return jsonify({"connected": False, "error": "Invalid response"})
    except requests.exceptions.Timeout:
        return jsonify({"connected": False, "error": "Connection timeout"})
    except requests.exceptions.ConnectionError:
        return jsonify({"connected": False, "error": "Connection failed"})
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 401:
            return jsonify({"connected": False, "error": "Authentication failed"})
        return jsonify({"connected": False, "error": f"HTTP {e.response.status_code}"})
    except Exception as e:
        return jsonify({"connected": False, "error": str(e)})

@app.route("/api/switch-server/<int:server_id>", methods=["POST"])
def switch_server(server_id):
    """Switch the active Kodi server"""
    if server_id not in KODI_SERVERS:
        return jsonify({"success": False, "error": "Server not found"}), 404
    
    session['active_server_id'] = server_id
    set_persisted_server_id(server_id)
    return jsonify({"success": True, "server_id": server_id})

@app.route("/api/current-server")
def get_current_server():
    """Get the currently active server ID"""
    server_id = session.get('active_server_id', 1)
    if server_id not in KODI_SERVERS:
        persisted = get_persisted_server_id()
        if persisted:
            server_id = persisted
            session['active_server_id'] = persisted
        else:
            server_id = 1 if KODI_SERVERS else None
    return jsonify({"server_id": server_id})

# Preferences storage
PREFERENCES_DIR = Path("/app/preferences")
PREFERENCES_FILE = PREFERENCES_DIR / "preferences.json"
PREFERENCES_LOCK = threading.Lock()
PREFERENCE_ENUMS = {
    "blurPreference": {"blurred", "non-blurred"},
    "overlayPreference": {"enabled", "disabled"},
}
PREFERENCE_RANGES = {
    "blurAmount": (0, 100),
    "overlayOpacity": (0, 100),
    "marqueeInterval": (5, 60),
    "fanartInterval": (5, 120),
    "fanartMinSizeKB": (0, 1000),
}

def ensure_preferences_dir():
    """Ensure the preferences directory exists"""
    try:
        PREFERENCES_DIR.mkdir(parents=True, exist_ok=True)
        logger.debug(f"Preferences directory ensured: {PREFERENCES_DIR}, exists: {PREFERENCES_DIR.exists()}")
    except Exception as e:
        logger.error(f"Failed to create preferences directory: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")

def load_preferences():
    """Load preferences from JSON file"""
    ensure_preferences_dir()
    if PREFERENCES_FILE.exists():
        try:
            with open(PREFERENCES_FILE, 'r') as f:
                prefs = json.load(f)
                logger.debug(f"Loaded preference keys from file: {list(prefs.keys()) if isinstance(prefs, dict) else type(prefs)}")
                # Ensure it's a dict
                if not isinstance(prefs, dict):
                    logger.warning(f"Preferences file contains non-dict data, returning empty dict")
                    return {}
                return prefs
        except (json.JSONDecodeError, IOError) as e:
            logger.error(f"Failed to load preferences: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return {}
    else:
        logger.debug(f"Preferences file does not exist yet: {PREFERENCES_FILE}")
    return {}

def save_preferences(prefs):
    """Save preferences to JSON file"""
    ensure_preferences_dir()
    try:
        logger.debug(f"Saving preferences to {PREFERENCES_FILE}")
        logger.debug(f"Preference keys to save: {list(prefs.keys()) if isinstance(prefs, dict) else type(prefs)}")
        logger.debug(f"Preferences type: {type(prefs)}, Is dict: {isinstance(prefs, dict)}")
        
        # Ensure prefs is a dict
        if not isinstance(prefs, dict):
            logger.error(f"Cannot save preferences - not a dict: {type(prefs)}")
            return False
        
        with PREFERENCES_LOCK:
            # Write atomically using a unique temporary file first
            temp_file = PREFERENCES_DIR / f"preferences.{uuid.uuid4().hex}.tmp"
            with open(temp_file, 'w') as f:
                json.dump(prefs, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            
            # Replace the original file atomically
            temp_file.replace(PREFERENCES_FILE)
        
        logger.debug(f"Successfully saved preferences to {PREFERENCES_FILE}")
        # Verify file was created
        if PREFERENCES_FILE.exists():
            file_size = PREFERENCES_FILE.stat().st_size
            logger.debug(f"Preferences file exists: {PREFERENCES_FILE.exists()}, size: {file_size} bytes")
            # Read back to verify
            with open(PREFERENCES_FILE, 'r') as f:
                verify_prefs = json.load(f)
                logger.debug(f"Verified saved preference keys: {list(verify_prefs.keys()) if isinstance(verify_prefs, dict) else type(verify_prefs)}")
        else:
            logger.error(f"Preferences file was not created at {PREFERENCES_FILE}")
            return False
        return True
    except IOError as e:
        logger.error(f"Failed to save preferences: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        return False

def validate_preferences_update(data):
    """Return sanitized preference values or an error message."""
    if not isinstance(data, dict):
        return None, "Preferences must be a JSON object"

    sanitized = {}
    allowed_keys = set(PREFERENCE_ENUMS) | set(PREFERENCE_RANGES)
    unknown_keys = sorted(set(data) - allowed_keys)
    if unknown_keys:
        return None, f"Unsupported preference key(s): {', '.join(unknown_keys)}"

    for key, allowed_values in PREFERENCE_ENUMS.items():
        if key not in data:
            continue
        value = str(data[key])
        if value not in allowed_values:
            return None, f"Invalid value for {key}"
        sanitized[key] = value

    for key, (min_value, max_value) in PREFERENCE_RANGES.items():
        if key not in data:
            continue
        try:
            value = int(data[key])
        except (TypeError, ValueError):
            return None, f"Invalid value for {key}"
        if value < min_value or value > max_value:
            return None, f"{key} must be between {min_value} and {max_value}"
        sanitized[key] = str(value)

    return sanitized, None

def get_persisted_server_id():
    prefs = load_preferences()
    server_id = prefs.get("active_server_id")
    try:
        server_id = int(server_id)
    except (TypeError, ValueError):
        return None
    return server_id if server_id in KODI_SERVERS else None

def set_persisted_server_id(server_id: int):
    prefs = load_preferences()
    prefs["active_server_id"] = server_id
    return save_preferences(prefs)

@app.before_request
def hydrate_server_session():
    try:
        server_id = session.get('active_server_id')
        if server_id not in KODI_SERVERS:
            persisted = get_persisted_server_id()
            if persisted and persisted in KODI_SERVERS:
                session['active_server_id'] = persisted
    except Exception as e:
        logger.warning(f"Failed to hydrate active server: {e}")

@app.route("/api/preferences", methods=["GET"])
def get_preferences():
    """Get user preferences"""
    prefs = load_preferences()
    logger.debug(f"GET preferences request, returning keys: {list(prefs.keys())}")
    return jsonify(prefs)

@app.route("/api/preferences/test", methods=["GET"])
def test_preferences():
    """Test if preferences directory is writable"""
    try:
        ensure_preferences_dir()
        test_file = PREFERENCES_DIR / "test.txt"
        test_file.write_text("test")
        test_file.unlink()
        return jsonify({
            "success": True,
            "directory": str(PREFERENCES_DIR),
            "directory_exists": PREFERENCES_DIR.exists(),
            "writable": True
        })
    except Exception as e:
        return jsonify({
            "success": False,
            "directory": str(PREFERENCES_DIR),
            "directory_exists": PREFERENCES_DIR.exists() if PREFERENCES_DIR else False,
            "writable": False,
            "error": str(e)
        }), 500

@app.route("/api/preferences", methods=["POST"])
def set_preferences():
    """Save user preferences"""
    try:
        data = request.get_json()
        logger.debug(f"Received preferences POST request with keys: {list(data.keys()) if isinstance(data, dict) else type(data)}")
        if not data:
            logger.error("No data provided in preferences POST request")
            return jsonify({"success": False, "error": "No data provided"}), 400
        sanitized, validation_error = validate_preferences_update(data)
        if validation_error:
            logger.warning(f"Invalid preferences POST request: {validation_error}")
            return jsonify({"success": False, "error": validation_error}), 400
        
        # Load existing preferences and merge with new ones
        prefs = load_preferences()
        logger.debug(f"Existing preference keys before merge: {list(prefs.keys())}")
        logger.debug(f"Preference keys to merge: {list(sanitized.keys())}")
        
        # Merge new data into existing preferences (update will overwrite existing keys)
        prefs.update(sanitized)
        
        logger.debug(f"Merged preference keys after update: {list(prefs.keys())}")
        logger.debug(f"Type of prefs: {type(prefs)}, Is dict: {isinstance(prefs, dict)}")
        
        # Verify we have a proper dict before saving
        if not isinstance(prefs, dict):
            logger.error(f"Preferences is not a dict after merge: {type(prefs)}")
            return jsonify({"success": False, "error": "Invalid preferences format"}), 500
        
        if save_preferences(prefs):
            logger.debug("Preferences saved successfully")
            return jsonify({"success": True})
        else:
            logger.error("save_preferences returned False")
            return jsonify({"success": False, "error": "Failed to save preferences"}), 500
    except Exception as e:
        logger.error(f"Failed to set preferences: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/health")
def health():
    """Liveness endpoint for Docker healthchecks and uptime monitors."""
    return jsonify({
        "status": "ok",
        "servers_configured": len(KODI_SERVERS),
    }), 200

def _format_overview_title(item):
    """Build a short display title for overview tiles."""
    media_type = item.get("type") or "unknown"
    title = item.get("title") or "Unknown"
    if media_type == "episode":
        show = item.get("showtitle") or title
        season = item.get("season")
        episode = item.get("episode")
        if season is not None and episode is not None:
            ep_label = f"S{int(season):02d}E{int(episode):02d}"
            if title and title != show:
                return f"{show} · {ep_label} · {title}", "episode"
            return f"{show} · {ep_label}", "episode"
        return show, "episode"
    if media_type == "song":
        artist = item.get("artist")
        if isinstance(artist, list):
            artist = ", ".join(artist) if artist else ""
        artist = artist or "Unknown artist"
        return f"{artist} · {title}", "song"
    if media_type == "movie":
        return title, "movie"
    return title, media_type if media_type != "unknown" else "other"

def get_server_overview_status(server_id):
    """Return lightweight playback status for one configured Kodi server."""
    server = KODI_SERVERS.get(server_id)
    if not server:
        return {
            "id": server_id,
            "connected": False,
            "playing": False,
            "error": "Server not found",
        }

    status = {
        "id": server_id,
        "host": server["host"],
        "ip": server["ip"],
        "label": server.get("label") or "",
        "name": server_display_name(server),
        "connected": False,
        "playing": False,
        "paused": False,
        "title": None,
        "media_type": None,
        "error": None,
    }

    try:
        players_response = kodi_rpc("Player.GetActivePlayers", {}, server_id=server_id)
        if players_response is None:
            status["error"] = "Connection failed"
            return status

        status["connected"] = True
        players = players_response.get("result") or []
        if not players:
            return status

        player_id = players[0].get("playerid")
        item_response = kodi_rpc(
            "Player.GetItem",
            {
                "playerid": player_id,
                "properties": ["title", "album", "artist", "showtitle", "season", "episode"],
            },
            server_id=server_id,
        )
        props_response = kodi_rpc(
            "Player.GetProperties",
            {"playerid": player_id, "properties": ["speed"]},
            server_id=server_id,
        )

        item = {}
        if item_response and item_response.get("result"):
            item = item_response["result"].get("item") or {}

        speed = 0
        if props_response and props_response.get("result"):
            speed = props_response["result"].get("speed", 0)

        display_title, media_type = _format_overview_title(item)
        status["playing"] = True
        status["paused"] = speed == 0
        status["title"] = display_title
        status["media_type"] = media_type
        return status
    except Exception as e:
        status["error"] = str(e)
        return status

@app.route("/api/overview")
def api_overview():
    """Status snapshot for every configured Kodi server (prefers warm cache)."""
    servers = []
    if not KODI_SERVERS:
        return jsonify({"servers": servers})

    for server_id in sorted(KODI_SERVERS.keys()):
        cached = overview_from_cache(server_id)
        if cached is not None:
            servers.append(cached)
            continue
        status = get_server_overview_status(server_id)
        status["thumb"] = None
        status["cache_ready"] = False
        status["backoff_remaining"] = int(server_backoff_remaining(server_id))
        servers.append(status)

    return jsonify({"servers": servers})


@app.route("/api/retry-server/<int:server_id>", methods=["POST"])
def retry_server(server_id):
    """Clear unreachable backoff and immediately re-probe one Kodi server."""
    if server_id not in KODI_SERVERS:
        return jsonify({"success": False, "error": "Server not found"}), 404

    note_server_rpc_success(server_id)
    try:
        refresh_server_cache(server_id)
    except Exception as e:
        logger.warning(f"Retry refresh failed for server {server_id}: {e}")

    status = overview_from_cache(server_id)
    if status is None:
        status = get_server_overview_status(server_id)
        status["thumb"] = None
        status["cache_ready"] = False
        status["backoff_remaining"] = int(server_backoff_remaining(server_id))

    return jsonify({"success": True, "server": status})

@app.route("/overview")
def overview_page():
    """Multi-Kodi wall: idle / playing / offline tiles for all configured servers."""
    return """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <title>Kodi Overview</title>
        <style>
            :root {
                --bg0: #141414;
                --bg1: #222;
                --card: rgba(0, 0, 0, 0.55);
                --green: #4caf50;
                --amber: #ffb300;
                --red: #e53935;
                --muted: rgba(255, 255, 255, 0.65);
            }
            * { box-sizing: border-box; }
            body {
                margin: 0;
                min-height: 100vh;
                font-family: "Century Gothic", CenturyGothic, AppleGothic, sans-serif;
                color: #fff;
                background: linear-gradient(145deg, var(--bg0), var(--bg1) 55%, #2a2a2a);
            }
            header {
                display: flex;
                align-items: center;
                justify-content: space-between;
                gap: 16px;
                padding: 28px 32px 8px;
            }
            h1 {
                margin: 0;
                font-size: clamp(1.4rem, 2.5vw, 2rem);
                letter-spacing: 0.06em;
                text-transform: uppercase;
                color: var(--green);
                text-shadow: 2px 2px 0 rgba(0,0,0,0.35);
            }
            .nav-links a {
                color: var(--muted);
                text-decoration: none;
                margin-left: 16px;
                font-size: 0.95rem;
            }
            .nav-links a:hover { color: #fff; }
            #grid {
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
                gap: 18px;
                padding: 24px 32px 40px;
            }
            .tile {
                background: var(--card);
                border: 1px solid rgba(255,255,255,0.08);
                border-left: 4px solid rgba(255,255,255,0.2);
                border-radius: 12px;
                padding: 20px 18px;
                min-height: 160px;
                display: flex;
                flex-direction: column;
                gap: 10px;
                transition: transform 0.2s ease, border-color 0.2s ease, background 0.2s ease;
                overflow: hidden;
            }
            .tile.playing { border-left-color: var(--green); cursor: pointer; }
            .tile.paused { border-left-color: var(--amber); cursor: pointer; }
            .tile.offline { border-left-color: var(--red); opacity: 0.85; }
            .tile.idle { border-left-color: rgba(255,255,255,0.25); }
            .tile.playing:hover, .tile.paused:hover {
                transform: translateY(-2px);
                background: rgba(0,0,0,0.7);
            }
            .tile-art {
                margin: -20px -18px 4px;
                height: 140px;
                background: rgba(0,0,0,0.35);
                overflow: hidden;
            }
            .tile-art img {
                width: 100%;
                height: 100%;
                object-fit: cover;
                display: block;
            }
            .tile-ip { font-size: 1.15rem; font-weight: 600; letter-spacing: 0.03em; }
            .tile-host { color: var(--muted); font-size: 0.85rem; word-break: break-all; }
            .badge {
                align-self: flex-start;
                padding: 4px 10px;
                border-radius: 999px;
                font-size: 0.75rem;
                text-transform: uppercase;
                letter-spacing: 0.08em;
                background: rgba(255,255,255,0.1);
            }
            .badge.playing { background: rgba(76,175,80,0.25); color: #a5d6a7; }
            .badge.paused { background: rgba(255,179,0,0.22); color: #ffe082; }
            .badge.idle { background: rgba(255,255,255,0.08); color: var(--muted); }
            .badge.offline { background: rgba(229,57,53,0.22); color: #ef9a9a; }
            .tile-meta { color: var(--muted); font-size: 0.85rem; text-transform: capitalize; }
            .tile-ready { color: #a5d6a7; font-size: 0.75rem; }
            .tile-status-row {
                display: flex;
                align-items: center;
                justify-content: space-between;
                gap: 10px;
                margin-top: auto;
            }
            .tile-title {
                font-size: 1.05rem;
                line-height: 1.35;
                flex: 1;
                min-width: 0;
            }
            .tile-retry {
                flex-shrink: 0;
                border: 1px solid rgba(255,255,255,0.25);
                background: rgba(255,255,255,0.08);
                color: #fff;
                border-radius: 8px;
                padding: 6px 10px;
                font-size: 0.8rem;
                cursor: pointer;
            }
            .tile-retry:hover { background: rgba(76,175,80,0.28); border-color: rgba(76,175,80,0.55); }
            .tile-retry:disabled {
                opacity: 0.55;
                cursor: wait;
            }
            .tile-backoff { color: #ef9a9a; font-size: 0.75rem; }
            .empty, .error-note {
                grid-column: 1 / -1;
                color: var(--muted);
                font-style: italic;
            }
            footer {
                padding: 0 32px 28px;
                color: var(--muted);
                font-size: 0.85rem;
            }
        </style>
    </head>
    <body>
        <header>
            <h1>Kodi Overview</h1>
            <div class="nav-links">
                <a href="/">Idle page</a>
                <a href="/nowplaying">Now playing</a>
            </div>
        </header>
        <div id="grid"><div class="empty">Loading servers…</div></div>
        <footer id="updated">Refreshing every 5 seconds</footer>
        <script>
            const grid = document.getElementById('grid');
            const updated = document.getElementById('updated');

            function badgeClass(server) {
                if (!server.connected) return 'offline';
                if (server.playing && server.paused) return 'paused';
                if (server.playing) return 'playing';
                return 'idle';
            }

            function badgeLabel(server) {
                if (!server.connected) return 'Offline';
                if (server.playing && server.paused) return 'Paused';
                if (server.playing) return 'Playing';
                return 'Idle';
            }

            function tileClass(server) {
                return 'tile ' + badgeClass(server);
            }

            function formatBackoff(seconds) {
                const s = Math.max(0, Math.floor(seconds || 0));
                if (s <= 0) return '';
                const m = Math.floor(s / 60);
                const r = s % 60;
                if (m <= 0) return r + 's';
                return m + 'm ' + r + 's';
            }

            function statusTitle(server) {
                if (server.playing) return server.title || 'Playing';
                if (server.connected) return 'Nothing playing';
                const backoff = formatBackoff(server.backoff_remaining);
                if (backoff) return (server.error || 'Connection failed') + ' · retry in ' + backoff;
                return server.error || 'Unreachable';
            }

            async function openServer(serverId, playing) {
                try {
                    await fetch('/api/switch-server/' + serverId, { method: 'POST' });
                } catch (e) {}
                window.location.href = playing ? '/loading' : '/';
            }

            async function retryServer(serverId, button) {
                if (button) {
                    button.disabled = true;
                    button.textContent = 'Retrying…';
                }
                try {
                    const res = await fetch('/api/retry-server/' + serverId, { method: 'POST' });
                    const data = await res.json();
                    if (data && data.server) {
                        await refresh();
                        return;
                    }
                } catch (e) {}
                if (button) {
                    button.disabled = false;
                    button.textContent = 'Retry';
                }
                await refresh();
            }

            function serverDisplayName(server) {
                if (!server) return '';
                if (server.name) return server.name;
                const label = (server.label || '').trim();
                const ip = server.ip || '';
                if (label && ip) return label + ' (' + ip + ')';
                if (label) return label;
                return ip || server.host || ('Server ' + server.id);
            }

            function render(servers) {
                if (!servers.length) {
                    grid.innerHTML = '<div class="empty">No Kodi servers configured. Set KODI_HOST_1…N in .env</div>';
                    return;
                }
                grid.innerHTML = '';
                servers.forEach(server => {
                    const tile = document.createElement('div');
                    tile.className = tileClass(server);
                    const name = serverDisplayName(server);
                    const subtitle = server.host || '';
                    const title = statusTitle(server);
                    const needsRetry = !server.connected || !!server.error || (server.backoff_remaining > 0);
                    const artHtml = server.thumb
                        ? '<div class="tile-art"><img src="' + server.thumb + '" alt=""></div>'
                        : '';
                    const readyHtml = server.cache_ready
                        ? '<div class="tile-ready">Ready · instant open</div>'
                        : '';
                    const retryHtml = needsRetry
                        ? '<button type="button" class="tile-retry" data-server-id="' + server.id + '">Retry</button>'
                        : '';
                    tile.innerHTML =
                        artHtml +
                        '<div class="tile-ip"></div>' +
                        '<div class="tile-host"></div>' +
                        '<span class="badge ' + badgeClass(server) + '">' + badgeLabel(server) + '</span>' +
                        '<div class="tile-status-row"><div class="tile-title"></div>' + retryHtml + '</div>' +
                        (server.media_type ? '<div class="tile-meta"></div>' : '') +
                        readyHtml;
                    tile.querySelector('.tile-ip').textContent = name;
                    tile.querySelector('.tile-host').textContent = subtitle;
                    tile.querySelector('.tile-title').textContent = title;
                    const meta = tile.querySelector('.tile-meta');
                    if (meta) meta.textContent = server.media_type;
                    const retryBtn = tile.querySelector('.tile-retry');
                    if (retryBtn) {
                        retryBtn.addEventListener('click', (e) => {
                            e.preventDefault();
                            e.stopPropagation();
                            retryServer(server.id, retryBtn);
                        });
                    }
                    if (server.connected) {
                        tile.addEventListener('click', () => openServer(server.id, !!server.playing));
                        tile.title = server.playing
                            ? (server.cache_ready ? 'Open cached now playing' : 'Open now playing for this server')
                            : 'Select this server';
                    }
                    grid.appendChild(tile);
                });
                updated.textContent = 'Updated ' + new Date().toLocaleTimeString();
            }

            async function refresh() {
                try {
                    const res = await fetch('/api/overview');
                    const data = await res.json();
                    render(data.servers || []);
                } catch (e) {
                    grid.innerHTML = '<div class="error-note">Failed to load overview</div>';
                }
            }

            refresh();
            setInterval(refresh, 5000);
        </script>
    </body>
    </html>
    """

@app.route("/")
def index():
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Kodi Now Playing</title>
        <style>
            body {
                font-family: Arial, sans-serif;
                background: linear-gradient(to bottom right, #222, #444);
                color: white;
                margin: 0;
                padding: 0;
                display: flex;
                justify-content: center;
                align-items: center;
                height: 100vh;
                opacity: 1;
                transition: opacity 1.5s ease;
                animation: fadeIn 1.5s ease;
            }
            body.fade-out {
                opacity: 0;
            }
            @keyframes fadeIn {
                from { opacity: 0; }
                to { opacity: 1; }
            }
            .message-box {
                background: rgba(0,0,0,0.6);
                padding: 40px;
                border-radius: 12px;
                box-shadow: 0 4px 20px rgba(0,0,0,0.8);
                font-size: 1.5em;
                font-style: italic;
                text-align: center;
            }
            
            /* Side Panel Styles */
            .side-panel {
                position: fixed;
                top: 0;
                right: -530px;
                width: 530px;
                max-width: calc(100vw - 40px);
                height: 100vh;
                background: rgba(0, 0, 0, 0.85);
                backdrop-filter: blur(10px);
                z-index: 1500;
                transition: right 0.5s ease-in-out;
                overflow: visible;
                padding: 20px;
                box-shadow: -5px 0 20px rgba(0, 0, 0, 0.5);
                box-sizing: border-box;
            }
            
            .side-panel.open {
                right: 0;
            }
            
            .side-panel-toggle {
                position: absolute;
                left: -20px;
                top: 50%;
                transform: translateY(-50%);
                width: 20px;
                height: 40px;
                background: rgba(0, 0, 0, 0.85);
                backdrop-filter: blur(10px);
                border-radius: 20px 0 0 20px;
                display: flex;
                align-items: center;
                justify-content: center;
                cursor: pointer;
                z-index: 1501;
                transition: all 0.3s ease;
                box-shadow: -2px 0 10px rgba(0, 0, 0, 0.3);
            }
            
            .side-panel-toggle-arrow {
                color: rgba(255, 255, 255, 0.8);
                font-size: 14px;
                font-weight: bold;
                transition: transform 0.3s ease;
                margin-left: 2px;
            }
            
            .side-panel-toggle:hover {
                background: rgba(0, 0, 0, 0.95);
            }
            
            
            h1 {
                font-family: "Avant Garde", Avantgarde, "Century Gothic", CenturyGothic, "AppleGothic", sans-serif;
                font-size: 35px;
                padding: 15px 15px;
                text-align: center;
                text-transform: uppercase;
                text-rendering: optimizeLegibility;
            }
            h1.retroshadow {
                color: #4caf50;
                letter-spacing: .05em;
                text-shadow: 
                    3px 3px 3px #d5d5d5, 
                    6px 6px 0px rgba(0, 0, 0, 0.2);
            }
            
            .side-panel-section {
                margin-bottom: 25px;
                padding-bottom: 20px;
                border-bottom: 1px solid rgba(255, 255, 255, 0.1);
            }
            
            .side-panel-section:last-child {
                border-bottom: none;
            }
            
            /* New Dropdown Menu Styles */
            .sec-center {
                position: relative;
                max-width: 100%;
                text-align: center;
                z-index: 200;
            }
            [type="checkbox"]:checked,
            [type="checkbox"]:not(:checked){
                position: absolute;
                left: -9999px;
                opacity: 0;
                pointer-events: none;
            }
            .dropdown:checked + label,
            .dropdown:not(:checked) + label{
                position: relative;
                font-weight: 500;
                font-size: 24px;
                line-height: 2;
                height: 50px;
                transition: all 200ms linear;
                border-radius: 4px;
                width: 100%;
                letter-spacing: 1px;
                display: -webkit-inline-flex;
                display: -ms-inline-flexbox;
                display: inline-flex;
                -webkit-align-items: center;
                -moz-align-items: center;
                -ms-align-items: center;
                align-items: center;
                -webkit-justify-content: center;
                -moz-justify-content: center;
                -ms-justify-content: center;
                justify-content: center;
                -ms-flex-pack: center;
                text-align: center;
                border: none;
                background-color: #4caf50;
                cursor: pointer;
                color: #fff;
                box-shadow: 0 12px 35px 0 rgba(76,175,80,.15);
            }
            .dropdown:checked + label span,
            .dropdown:not(:checked) + label span {
                color: #fff;
            }
            .dropdown:checked + label:before,
            .dropdown:not(:checked) + label:before{
                position: fixed;
                top: 0;
                left: 0;
                content: '';
                width: 100%;
                height: 100%;
                z-index: -1;
                cursor: auto;
                pointer-events: none;
            }
            .dropdown:checked + label:before{
                pointer-events: auto;
            }
            .dropdown:not(:checked) + label span {
                font-size: 24px;
                margin-left: 10px;
                transition: transform 200ms linear;
            }
            .dropdown:checked + label span {
                transform: rotate(180deg);
                font-size: 24px;
                margin-left: 10px;
                transition: transform 200ms linear;
            }
            .section-dropdown {
                position: absolute;
                padding: 5px;
                background-color: rgba(0, 0, 0, 0.95);
                top: 70px;
                left: 0;
                width: 100%;
                border-radius: 4px;
                display: block;
                box-shadow: 0 14px 35px 0 rgba(0,0,0,0.8);
                z-index: 2;
                opacity: 0;
                pointer-events: none;
                transform: translateY(20px);
                transition: all 200ms linear;
            }
            .dropdown:checked ~ .section-dropdown{
                opacity: 1;
                pointer-events: auto;
                transform: translateY(0);
            }
            .section-dropdown:before {
                position: absolute;
                top: -20px;
                left: 0;
                width: 100%;
                height: 20px;
                content: '';
                display: block;
                z-index: 1;
            }
            .section-dropdown:after {
                position: absolute;
                top: -7px;
                left: 30px;
                width: 0; 
                height: 0; 
                border-left: 8px solid transparent;
                border-right: 8px solid transparent; 
                border-bottom: 8px solid rgba(0, 0, 0, 0.95);
                content: '';
                display: block;
                z-index: 2;
                transition: all 200ms linear;
            }
            .section-dropdown a {
                position: relative;
                color: #fff;
                transition: all 200ms linear;
                font-weight: 500;
                font-size: 24px;
                border-radius: 2px;
                padding: 5px 0;
                padding-left: 20px;
                padding-right: 15px;
                margin: 2px 0;
                text-align: left;
                text-decoration: none;
                display: -ms-flexbox;
                display: flex;
                -webkit-align-items: center;
                -moz-align-items: center;
                -ms-align-items: center;
                align-items: center;
                justify-content: space-between;
                -ms-flex-pack: distribute;
            }
            .section-dropdown a:hover {
                color: #fff;
                background-color: #4caf50;
            }
            .section-dropdown a.current-server {
                color: #4caf50;
                font-weight: bold;
            }
            .section-dropdown a.current-server:hover {
                color: #fff;
                background-color: #4caf50;
            }
            
            /* Toggle Component Styles */
            .toggle {
                align-items: center;
                border-radius: 100px;
                display: flex;
                font-weight: 700;
                margin-bottom: 0;
            }
            
            .toggle__input {
                clip: rect(0 0 0 0);
                clip-path: inset(50%);
                height: 1px;
                overflow: hidden;
                position: absolute;
                white-space: nowrap;
                width: 1px;
            }
            
            .toggle__input:disabled + .toggle-track {
                cursor: not-allowed;
                opacity: 0.7;
            }
            
            .toggle-track {
                background: rgba(255, 255, 255, 0.2);
                border: 1px solid rgba(255, 255, 255, 0.3);
                border-radius: 100px;
                cursor: pointer;
                display: flex;
                height: 30px;
                margin-right: 12px;
                position: relative;
                width: 60px;
                transition: all 0.3s ease;
            }
            
            .toggle-indicator {
                align-items: center;
                background: rgba(255, 255, 255, 0.3);
                border-radius: 24px;
                top: 3px;
                display: flex;
                height: 24px;
                justify-content: center;
                left: 2px;
                outline: solid 2px transparent;
                position: absolute;
                transition: transform 0.3s ease, background 0.3s ease;
                width: 24px;
            }
            
            .checkMark {
                fill: #fff;
                height: 20px;
                width: 20px;
                opacity: 0;
                transition: opacity 0.3s ease-in-out;
            }
            
            .toggle__input:checked + .toggle-track .toggle-indicator {
                background: #4caf50;
                transform: translateX(30px);
                top: 3px;
            }
            
            .toggle__input:checked + .toggle-track .checkMark {
                opacity: 1;
                transition: opacity 0.3s ease-in-out;
            }
        </style>
    </head>
    <body>
        <div class="message-box">
            <div id="serverMessage">🎬 No Media Currently Playing<br>Awaiting Media Playback</div>
            <div style="margin-top: 18px; font-size: 0.65em; font-style: normal;">
                <a href="/overview" style="color: #4caf50; text-decoration: none;">Multi-server overview →</a>
            </div>
        </div>
        
        <!-- Side Panel -->
        <div class="side-panel" id="sidePanel">
            <!-- Side Panel Toggle Button -->
            <div class="side-panel-toggle" onclick="toggleSidePanel()">
                <div class="side-panel-toggle-arrow">◄</div>
            </div>
            
            <div style="overflow-y: auto; height: 100%; padding-left: 15px; padding-right: 10px; padding-top: 20px;">
                <h1 class="retroshadow">Now Playing On</h1>
                
                <div class="side-panel-section">
                    <div class="sec-center">
                        <input class="dropdown" type="checkbox" id="serverDropdown" name="serverDropdown">
                        <label class="for-dropdown" for="serverDropdown" id="serverDropdownLabel">Select Server <span style="font-size: 24px; margin-left: 10px; transition: transform 200ms linear; color: #fff;">▼</span></label>
                        <div class="section-dropdown">
                            <div id="serverDropdownList"></div>
                        </div>
                    </div>
                </div>

                <div class="side-panel-section">
                    <a href="/overview" style="color: #4caf50; text-decoration: none; font-size: 0.95em;">Multi-server overview →</a>
                </div>
            </div>
        </div>
        
        <script>
            let lastPlaybackState = false; // Initialize to false
            let currentServerId = null;
            let playbackPollInFlight = false;
            let playbackPollTimer = null;
            const PLAYBACK_POLL_MS = 4000;

            function toggleSidePanel() {
                const panel = document.getElementById('sidePanel');
                const arrow = document.querySelector('.side-panel-toggle-arrow');
                panel.classList.toggle('open');
                if (panel.classList.contains('open')) {
                    arrow.style.transform = 'rotate(180deg)';
                } else {
                    arrow.style.transform = 'rotate(0deg)';
                }
            }
            
            function serverDisplayName(server) {
                if (!server) return '';
                if (server.name) return server.name;
                const label = (server.label || '').trim();
                const ip = server.ip || '';
                if (label && ip) return `${label} (${ip})`;
                if (label) return label;
                return ip || server.host || ('Server ' + server.id);
            }

            function updateServerMessage(server) {
                const messageDiv = document.getElementById('serverMessage');
                if (server) {
                    const name = serverDisplayName(server);
                    messageDiv.innerHTML = `🎬 No media playing on selected server: ${name}`;
                } else {
                    messageDiv.innerHTML = '🎬 No Media Currently Playing<br>Awaiting Media Playback';
                }
            }
            
            async function loadServers() {
                try {
                    const response = await fetch('/api/servers');
                    const data = await response.json();
                    
                    if (data.servers && data.servers.length > 0) {
                        // Get current server
                        const currentResponse = await fetch('/api/current-server');
                        const currentData = await currentResponse.json();
                        
                        if (currentData.server_id) {
                            currentServerId = currentData.server_id;
                        } else {
                            // Default to first server
                            currentServerId = data.servers[0].id;
                            // Switch to first server if none selected
                            await switchServerFromDropdown(data.servers[0].id);
                            return;
                        }
                        
                        // Populate new dropdown menu
                        populateServerDropdown(data.servers, currentData.server_id || data.servers[0].id);
                        
                        // Update the message with server label/IP
                        const selectedServer = data.servers.find(s => s.id === currentServerId);
                        if (selectedServer) {
                            updateServerMessage(selectedServer);
                        }
                    }
                } catch (error) {
                    console.error('Failed to load servers:', error);
                }
            }
            
            function populateServerDropdown(servers, currentServerId) {
                const dropdownList = document.getElementById('serverDropdownList');
                const dropdownLabel = document.getElementById('serverDropdownLabel');
                
                if (!dropdownList || !dropdownLabel) return;
                
                dropdownList.innerHTML = '';
                
                if (servers && servers.length > 0) {
                    servers.forEach(server => {
                        const displayName = serverDisplayName(server);
                        const isCurrent = server.id === currentServerId;
                        
                        const link = document.createElement('a');
                        link.href = '#';
                        link.textContent = displayName;
                        link.dataset.serverId = server.id;
                        link.onclick = function(e) {
                            e.preventDefault();
                            const serverId = parseInt(this.dataset.serverId);
                            if (serverId && serverId !== currentServerId) {
                                switchServerFromDropdown(serverId);
                            }
                            // Close dropdown
                            document.getElementById('serverDropdown').checked = false;
                        };
                        
                        if (isCurrent) {
                            link.classList.add('current-server');
                            dropdownLabel.innerHTML = `${displayName} <span style="font-size: 24px; margin-left: 10px; transition: transform 200ms linear; color: #fff;">▼</span>`;
                        }
                        
                        dropdownList.appendChild(link);
                    });
                }
            }
            
            async function switchServerFromDropdown(serverId) {
                if (!serverId) return;
                
                try {
                    const response = await fetch(`/api/switch-server/${serverId}`, {
                        method: 'POST'
                    });
                    const data = await response.json();
                    
                    if (data.success) {
                        currentServerId = serverId;
                        
                        // Update message with new server label/IP
                        const serversResponse = await fetch('/api/servers');
                        const serversData = await serversResponse.json();
                        const selectedServer = serversData.servers.find(s => s.id === serverId);
                        if (selectedServer) {
                            updateServerMessage(selectedServer);
                        }
                        
                        // Show loading screen then reload
                        document.body.classList.add('fade-out');
                        setTimeout(() => {
                            window.location.href = '/loading';
                        }, 500);
                    }
                } catch (error) {
                    console.error('Failed to switch server:', error);
                }
            }
            

            function checkPlaybackChange() {
                if (playbackPollInFlight) return;
                playbackPollInFlight = true;
                fetch('/poll_playback')
                    .then(res => {
                        if (!res.ok) {
                            throw new Error(`HTTP ${res.status}`);
                        }
                        return res.json();
                    })
                    .then(data => {
                        const currentState = data.playing;
                        const isError = data.error === true;
                        if (isError) {
                            console.log('[DEBUG] Poll playback error flagged, skipping redirect');
                            return;
                        }
                        // Only fade out and redirect if media starts playing (transitions from false to true)
                        // Don't fade if transitioning from true to false (that would make screen dim)
                        if (currentState === true && lastPlaybackState === false) {
                            document.body.classList.add('fade-out');
                            setTimeout(() => {
                                window.location.href = '/loading';
                            }, 1500);
                        }
                        lastPlaybackState = currentState;
                    })
                    .catch(error => {
                        console.error('Polling error:', error);
                    })
                    .finally(() => {
                        playbackPollInFlight = false;
                    });
            }
            
            // Initialize on page load
            document.addEventListener('DOMContentLoaded', () => {
                loadServers();
                // Check initial state of side panel and set arrow accordingly
                const panel = document.getElementById('sidePanel');
                const arrow = document.querySelector('.side-panel-toggle-arrow');
                if (panel && arrow) {
                    if (panel.classList.contains('open')) {
                        arrow.style.transform = 'rotate(180deg)';
                    }
                }
            });
            
            if (playbackPollTimer) clearInterval(playbackPollTimer);
            playbackPollTimer = setInterval(checkPlaybackChange, PLAYBACK_POLL_MS);
        </script>
    </body>
    </html>
    """

@app.route("/poll_playback")
def poll_playback():
    """Poll active server playback. Transient RPC failures must not look like idle."""
    active = get_active_server()
    server_id = active.get("id") if active else None
    if server_id is None:
        return jsonify({"playing": False, "error": True})

    state = _poll_state_for(server_id)
    remaining = server_backoff_remaining(server_id)
    if remaining > 0:
        return jsonify({
            "playing": True if state.get("item_id") else None,
            "error": True,
            "backoff": True,
            "backoff_remaining": int(remaining),
            "item_id": state.get("item_id"),
        })

    try:
        players = kodi_rpc("Player.GetActivePlayers")
        if players is None:
            with playback_poll_lock:
                state["error_streak"] = int(state.get("error_streak", 0)) + 1
            # Do not flip to idle — frontend treats error as "hold current page"
            return jsonify({
                "playing": True if state.get("item_id") else None,
                "error": True,
                "item_id": state.get("item_id"),
            })

        if players.get("result"):
            with playback_poll_lock:
                state["idle_streak"] = 0
                state["error_streak"] = 0

            current_time = time.time()
            current_item_id = state.get("item_id")

            if current_time - float(state.get("last_check") or 0) >= EPISODE_CHECK_INTERVAL or not state.get("item_id"):
                with playback_poll_lock:
                    state["last_check"] = current_time
                try:
                    active_players = players.get("result") or []
                    if active_players:
                        player_id = active_players[0].get("playerid")
                        item = kodi_rpc(
                            "Player.GetItem",
                            {
                                "playerid": player_id,
                                "properties": ["title", "album", "artist", "showtitle", "season", "episode", "file"],
                            },
                        )
                        if item and item.get("result") and item.get("result", {}).get("item"):
                            current_item = item.get("result", {}).get("item", {})
                            item_id = current_item.get("id")
                            if current_item.get("type") == "song" and item_id:
                                current_item_id = f"song_{item_id}"
                            elif current_item.get("type") == "episode" and item_id:
                                current_item_id = f"episode_{item_id}"
                            elif current_item.get("type") == "movie" and item_id:
                                current_item_id = f"movie_{item_id}"
                            else:
                                current_item_id = f"other_{current_item.get('title', 'unknown')}"

                            with playback_poll_lock:
                                # First observation or same item: just store. Never emit ephemeral change ids.
                                state["item_id"] = current_item_id
                        elif item is None:
                            return jsonify({
                                "playing": True if state.get("item_id") else None,
                                "error": True,
                                "item_id": state.get("item_id"),
                            })
                except Exception as e:
                    logger.debug(f"Failed to check episode: {e}")
                    return jsonify({
                        "playing": True if state.get("item_id") else None,
                        "error": True,
                        "item_id": state.get("item_id"),
                    })

            active_players = players.get("result", [])
            is_paused = False
            current_audio_lang = ""
            current_subtitle_lang = ""
            if active_players:
                player_id = active_players[0].get("playerid")
                progress_response = kodi_rpc("Player.GetProperties", {
                    "playerid": player_id,
                    "properties": ["speed"]
                })
                if progress_response is None:
                    return jsonify({
                        "playing": True,
                        "error": True,
                        "item_id": state.get("item_id") or current_item_id or "episode_unknown",
                    })
                speed = 0
                if progress_response.get("result"):
                    speed = progress_response.get("result", {}).get("speed", 0)
                is_paused = speed == 0

                try:
                    language_response = kodi_rpc("XBMC.GetInfoLabels", {
                        "labels": ["VideoPlayer.AudioLanguage", "VideoPlayer.SubtitlesLanguage"]
                    })
                    if language_response and language_response.get("result"):
                        result = language_response.get("result", {})
                        current_audio_lang = result.get("VideoPlayer.AudioLanguage", "")[:3].upper()
                        current_subtitle_lang = result.get("VideoPlayer.SubtitlesLanguage", "")[:3].upper()
                        language_normalization = {
                            'GER': 'DEU', 'ENG': 'ENG', 'FRE': 'FRA', 'SPA': 'SPA',
                            'ITA': 'ITA', 'POR': 'POR', 'RUS': 'RUS', 'JPN': 'JPN',
                            'KOR': 'KOR', 'CHI': 'CHI',
                        }
                        current_audio_lang = language_normalization.get(current_audio_lang, current_audio_lang)
                        current_subtitle_lang = language_normalization.get(current_subtitle_lang, current_subtitle_lang)
                except Exception as e:
                    logger.debug(f"Failed to get current languages: {e}")

            item_id = state.get("item_id") or current_item_id or "episode_unknown"
            return jsonify({
                "playing": True,
                "paused": is_paused,
                "item_id": item_id,
                "item_type": "episode",
                "current_audio_lang": current_audio_lang,
                "current_subtitle_lang": current_subtitle_lang,
            })

        # Empty player list — confirm idle across several polls before reporting stopped
        with playback_poll_lock:
            state["idle_streak"] = int(state.get("idle_streak", 0)) + 1
            state["error_streak"] = 0
            idle_streak = state["idle_streak"]
            known_item = state.get("item_id")

        if idle_streak < POLL_IDLE_CONFIRMATIONS and known_item:
            logger.debug(
                "Poll playback - empty players (streak %s/%s), holding playing state for server %s",
                idle_streak,
                POLL_IDLE_CONFIRMATIONS,
                server_id,
            )
            return jsonify({
                "playing": True,
                "paused": False,
                "item_id": known_item,
                "item_type": "episode",
                "transient_idle": True,
            })

        with playback_poll_lock:
            state["item_id"] = None
            state["last_check"] = 0.0
            state["idle_streak"] = 0
        logger.debug(f"Poll playback - Confirmed idle for server {server_id}")
        return jsonify({"playing": False})
    except Exception as e:
        logger.error(f"Poll playback failed: {e}")
        return jsonify({
            "playing": True if state.get("item_id") else None,
            "error": True,
            "item_id": state.get("item_id"),
        })

def kodi_rpc(method, params=None, server_id=None):
    """
    Make RPC call to Kodi server.
    
    Args:
        method: RPC method name
        params: RPC parameters
        server_id: Optional server ID to use (if None, uses active server from session)
    """
    # Get server to use
    if server_id and server_id in KODI_SERVERS:
        server = KODI_SERVERS[server_id]
    else:
        server = get_active_server()
    
    if not server:
        logger.error(f"No Kodi server available")
        return None

    sid = server.get("id")
    remaining = server_backoff_remaining(sid)
    if remaining > 0:
        logger.debug(
            "Skipping RPC %s for server %s (unreachable backoff, %.0fs left)",
            method,
            sid,
            remaining,
        )
        return None
    
    payload = {
        "jsonrpc": "2.0",
        "method": method,
        "params": params or {},
        "id": 1
    }
    try:
        r = requests.post(
            f"{server['host']}/jsonrpc",
            headers=HEADERS,
            json=payload,
            auth=server['auth'],
            timeout=KODI_RPC_TIMEOUT,
        )
        r.raise_for_status()
        response_json = r.json()
        note_server_rpc_success(sid)
        logger.debug("Kodi response for %s (server %s): %s", method, sid, response_json)
        return response_json
    except Exception as e:
        entered_backoff = note_server_rpc_failure(sid, e)
        # Artwork prepare calls are noisy when a device is overloaded; keep other RPC failures loud
        if method == "Files.PrepareDownload":
            if not entered_backoff:
                logger.warning(f"Kodi RPC failed for method {method} (server {sid}): {e}")
            time.sleep(0.15)
        elif not entered_backoff:
            logger.error(f"Kodi RPC failed for method {method} (server {sid}): {e}")
        elif remaining <= 0:
            # First entry into backoff already logged a warning in note_server_rpc_failure
            pass
        return None



def prepare_and_download_art(item, session_id, progress_cb=None):
    downloaded = {}
    
    # Get active server for this request
    server = get_active_server()
    if not server:
        logger.error(f"No active server available for artwork download")
        return downloaded

    # Serialize art RPC/download traffic per Kodi — concurrent PrepareDownload floods hang weak devices
    with _art_lock_for(server.get("id")):
        return _prepare_and_download_art_locked(item, session_id, server, progress_cb=progress_cb)


def _prepare_and_download_art_locked(item, session_id, server, progress_cb=None):
    downloaded = {}

    art_map = item.get("art", {})
    if item.get("thumbnail") and not art_map.get("poster"):
        art_map["poster"] = item["thumbnail"]

    # Handle TV show artwork with tvshow. prefix
    tvshow_art_map = {}
    for key, value in art_map.items():
        if key.startswith("tvshow."):
            # Map tvshow.poster to poster, tvshow.fanart to fanart, etc.
            clean_key = key.replace("tvshow.", "")
            tvshow_art_map[clean_key] = value

    # Handle music artwork with album., artist., and albumartist. prefixes
    music_art_map = {}
    for key, value in art_map.items():
        if key.startswith("album."):
            # Map album.thumb to thumbnail, album.poster to poster, etc.
            clean_key = key.replace("album.", "")
            if clean_key == "thumb":
                clean_key = "thumbnail"
            music_art_map[clean_key] = value
            # Also map album.front to front and album.back to back for cover art
            if clean_key == "front":
                music_art_map["front"] = value
            elif clean_key == "back":
                music_art_map["back"] = value
        elif key.startswith("artist."):
            # Map artist.fanart to fanart, artist.clearlogo to clearlogo, etc.
            clean_key = key.replace("artist.", "")
            music_art_map[clean_key] = value
        elif key.startswith("albumartist."):
            # Map albumartist.fanart to fanart, albumartist.clearlogo to clearlogo, etc.
            clean_key = key.replace("albumartist.", "")
            music_art_map[clean_key] = value

    # Merge all artwork (music takes precedence, then TV show, then regular)
    art_map = {**art_map, **tvshow_art_map, **music_art_map}
    
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

        if not has_valid_cover:
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
                logger.debug(f"Using fallback music thumbnail: {potential_cover}")
            else:
                logger.debug(f"No fallback album cover found for {album_dir}")

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
                                    if base_name in ("clearlogo.png", "clearlogo.jpg", "clearlogo.jpeg", "clearlogo.webp"):
                                        if not art_map.get("clearlogo"):
                                            art_map["clearlogo"] = file_path
                                            logger.debug(f"Added clearlogo from media dir: {file_path}")
                                
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
                                            
                                            # Process each fanart file in the extrafanart directory
                                            for extrafanart_file in extrafanart_files:
                                                if isinstance(extrafanart_file, dict):
                                                    extrafanart_path = extrafanart_file.get("file", "")
                                                    if extrafanart_path and extrafanart_path.lower().endswith((".jpg", ".jpeg", ".png")):
                                                        filename = os.path.basename(extrafanart_path)
                                                        logger.debug(f"Found extrafanart file: {extrafanart_path}")
                                                        
                                                        # Create a unique key for this extrafanart file
                                                        if filename.lower() == "fanart.jpg":
                                                            fanart_variants["extrafanart_main"] = extrafanart_path
                                                            logger.debug(f"Added extrafanart main: {extrafanart_path}")
                                                        else:
                                                            # Use filename as key (fanart2.jpg -> extrafanart2, etc.)
                                                            key_name = f"extrafanart_{filename.lower().replace('.jpg', '').replace('.jpeg', '').replace('.png', '')}"
                                                            fanart_variants[key_name] = extrafanart_path
                                                            logger.debug(f"Added extrafanart: {key_name} -> {extrafanart_path}")
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
                                            logger.debug(f"Added fanart variant: fanart{variant_name} -> {file_path}")
                                        elif variant_name == "":
                                            # This is fanart.jpg, skip it
                                            continue
                                        else:
                                            # Custom fanart name
                                            fanart_variants[f"fanart_{variant_name}"] = file_path
                                            logger.debug(f"Added custom fanart: fanart_{variant_name} -> {file_path}")
                    else:
                        logger.debug(f"Failed to get directory listing: {dir_response}")
                        
                except Exception as dir_e:
                    logger.debug(f"Directory listing failed: {dir_e}")
                    
                    # Fallback: try to find fanart1, fanart2, etc. by testing individual files
                    logger.debug(f"Falling back to individual file testing")
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
                                            logger.debug(f"Found additional fanart: fanart{i} at {fanart_path}")
                                    except Exception as test_e:
                                        logger.debug(f"Test request failed for fanart{i}: {test_e}")
                                elif path:
                                    # Test if the image actually exists
                                    try:
                                        test_response = requests.head(f"{server['host']}/{path}", auth=server['auth'], timeout=3)
                                        if test_response.status_code == 200:
                                            fanart_variants[f"fanart{i}"] = fanart_path
                                            logger.debug(f"Found additional fanart: fanart{i} at {fanart_path}")
                                    except Exception as test_e:
                                        logger.debug(f"Test request failed for fanart{i}: {test_e}")
                        except Exception as e:
                            logger.debug(f"Failed to check fanart{i}: {e}")
                            pass
                        
            except Exception as e:
                logger.debug(f"Failed to scan for additional fanart: {e}")
    
    logger.debug(f"Total fanart variants found: {list(fanart_variants.keys())}")

    def art_label(art_key: str) -> str:
        if art_key in ["poster", "front", "back", "thumbnail", "season.poster"]:
            return "Loading posters"
        if art_key.startswith("fanart") or art_key.startswith("extrafanart"):
            return "Loading fanart"
        return "Loading artwork"

    art_tasks = []
    for art_type in ART_TYPES:
        if art_map.get(art_type):
            art_tasks.append(("art", art_type))
    for variant_key in fanart_variants.keys():
        if variant_key != "fanart":
            art_tasks.append(("fanart", variant_key))

    total_tasks = len(art_tasks)
    task_index = 0

    def update_art_progress(label: str):
        nonlocal task_index
        task_index += 1
        if progress_cb and total_tasks:
            progress_cb(task_index, total_tasks, label)

    if progress_cb and total_tasks == 0:
        progress_cb(1, 1, "Loading artwork")

    for art_type in ART_TYPES:
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
            # Handle local Kodi paths
            image_url = None
            try:
                if raw_path:
                    response = kodi_rpc("Files.PrepareDownload", {"path": raw_path})
                else:
                    response = None
                details = response.get("result", {}).get("details", {}) if response else {}
                token = details.get("token")
                path = details.get("path")

                if token and raw_path:
                    basename = os.path.basename(raw_path)
                    image_url = f"{server['host']}/vfs/{token}/{urllib.parse.quote(basename)}"
                elif path:
                    image_url = f"{server['host']}/{path}"
                else:
                    logger.error(f"No valid download path for {art_type}")
            except Exception as e:
                logger.warning(f"Failed to prepare download for {art_type}: {e}")
            
            # If primary path failed, try fallback paths for artist artwork
            if not image_url and art_type in ["fanart", "clearlogo", "clearart", "banner", "front", "back", "discart"]:
                logger.debug(f"Primary path failed, trying fallback paths for {art_type}")
                # Try to construct fallback paths based on album/artist folder structure
                current_file = item.get("file", "")
                if current_file.startswith("nfs://"):
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
                                fallback_paths.append(f"image://{urllib.parse.quote(clearlogo_png, safe='')}/")
                                fallback_paths.append(f"image://{urllib.parse.quote(clearlogo_jpg, safe='')}/")
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
                                details = response.get("result", {}).get("details", {})
                                token = details.get("token")
                                path = details.get("path")
                                
                                if token:
                                    basename = os.path.basename(fallback_path)
                                    image_url = f"{server['host']}/vfs/{token}/{urllib.parse.quote(basename)}"
                                    logger.debug(f"Found fallback path for {art_type}: {image_url}")
                                    break
                                elif path:
                                    image_url = f"{server['host']}/{path}"
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

        filename = f"{session_id}_{art_type}.jpg"
        local_path = os.path.join(ART_TMP_DIR, filename)

        try:
            if os.path.exists(local_path) and os.path.getsize(local_path) > 0:
                if _fanart_size_ok(local_path, art_type):
                    downloaded[art_type] = filename
                    logger.debug(f"Reusing cached artwork {local_path}")
                    continue
                try:
                    os.remove(local_path)
                except Exception:
                    pass
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
                downloaded[art_type] = filename
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
                if current_file.startswith("nfs://"):
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
                                fallback_paths.append(f"image://{urllib.parse.quote(clearlogo_png, safe='')}/")
                                fallback_paths.append(f"image://{urllib.parse.quote(clearlogo_jpg, safe='')}/")
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
                                details = response.get("result", {}).get("details", {})
                                token = details.get("token")
                                path = details.get("path")
                                
                                if token:
                                    basename = os.path.basename(fallback_path)
                                    fallback_image_url = f"{server['host']}/vfs/{token}/{urllib.parse.quote(basename)}"
                                elif path:
                                    fallback_image_url = f"{server['host']}/{path}"
                                else:
                                    pass
                                
                                # Try to download the fallback image
                                logger.debug(f"Trying to download fallback: {fallback_image_url}")
                                r = requests.get(fallback_image_url, auth=server['auth'], timeout=5)
                                r.raise_for_status()
                                with open(local_path, "wb") as f:
                                    f.write(r.content)
                                if _fanart_size_ok(local_path, art_type):
                                    downloaded[art_type] = filename
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

    # Process fanart variants for slideshow
    if len(fanart_variants) > 1:
        logger.debug(f"Processing {len(fanart_variants)} fanart variants for slideshow")
        
        # Download additional fanart variants
        for variant_key, variant_path in fanart_variants.items():
            if variant_key == "fanart":
                continue  # Skip the main fanart as it's already processed
            label = "Loading fanart"
                
            try:
                # Prepare download for this fanart variant
                # Handle different path formats
                if variant_path.startswith("image://"):
                    logger.debug(f"Processing fanart variant {variant_key}: {variant_path}")
                    
                    # Handle artist information paths with fallback logic
                    if "ArtistInformation" in variant_path:
                        logger.debug(f"Processing artist information path for {variant_key}: {variant_path}")
                        
                        # Extract the artist name and filename from the path
                        original_path = urllib.parse.unquote(variant_path[len("image://"):])
                        if original_path.endswith("/"):
                            original_path = original_path[:-1]
                        
                        # Extract artist name from path like U:\Kodi\ArtistInformation\AURORA\fanart1.jpg
                        path_parts = original_path.split("\\")
                        if len(path_parts) >= 4:
                            artist_name = path_parts[3]  # AURORA
                            filename = path_parts[-1]    # fanart1.jpg
                            
                            # Get the artist folder path from the current file
                            current_file = item.get("file", "")
                            if current_file.startswith("nfs://"):
                                file_parts = current_file.split("/")
                                if "Music" in file_parts:
                                    music_index = file_parts.index("Music")
                                    if music_index + 1 < len(file_parts):
                                        artist_folder = file_parts[music_index + 1]
                                        
                                        # Try multiple fallback paths with different formats
                                        fallback_paths = []
                                        
                                        # Build base path from current file's path
                                        file_parts = current_file.split("/")
                                        if "Music" in file_parts:
                                            music_index = file_parts.index("Music")
                                            base_path = "/".join(file_parts[:music_index + 1])  # Everything up to and including "Music"
                                        
                                        # 1. Try direct artist folder path with original extension
                                        fallback_paths.append(f"{base_path}/{artist_folder}/{filename}")
                                        
                                        # 2. Try different file extensions (jpg, jpeg, png)
                                        base_filename = filename.rsplit('.', 1)[0] if '.' in filename else filename
                                        for ext in ['jpg', 'jpeg', 'png']:
                                            fallback_paths.append(f"{base_path}/{artist_folder}/{base_filename}.{ext}")
                                        
                                        # 3. Try extrafanart folder with original extension
                                        fallback_paths.append(f"{base_path}/{artist_folder}/extrafanart/{filename}")
                                        
                                        # 4. Try extrafanart folder with different extensions
                                        for ext in ['jpg', 'jpeg', 'png']:
                                            fallback_paths.append(f"{base_path}/{artist_folder}/extrafanart/{base_filename}.{ext}")
                                        
                                        # Try each fallback path
                                        for fallback_path in fallback_paths:
                                            image_protocol_path = f"image://{urllib.parse.quote(fallback_path, safe='')}/"
                                            logger.debug(f"Trying fallback path: {image_protocol_path}")
                                            
                                            response = kodi_rpc("Files.PrepareDownload", {"path": image_protocol_path})
                                            if response and response.get("result") and not response.get("error"):
                                                details = response.get("result", {}).get("details", {})
                                                token = details.get("token")
                                                path = details.get("path")
                                                
                                                if token:
                                                    basename = os.path.basename(fallback_path)
                                                    image_url = f"{server['host']}/vfs/{token}/{urllib.parse.quote(basename)}"
                                                elif path:
                                                    image_url = f"{server['host']}/{path}"
                                                else:
                                                    continue
                                                
                                                # Download the fanart variant
                                                filename_local = f"{session_id}_{variant_key}.jpg"
                                                local_path = os.path.join(ART_TMP_DIR, filename_local)
                                                
                                                try:
                                                    r = requests.get(image_url, auth=server['auth'], timeout=5)
                                                    r.raise_for_status()
                                                    with open(local_path, "wb") as f:
                                                        f.write(r.content)
                                                    if _fanart_size_ok(local_path, variant_key):
                                                        downloaded[variant_key] = filename_local
                                                        logger.info(f"Downloaded {variant_key} from fallback path to {local_path}")
                                                        break  # Success, exit fallback loop
                                                    logger.info(f"Fanart {variant_key} filtered by size threshold")
                                                except Exception as e:
                                                    logger.debug(f"Failed to download from fallback path: {e}")
                                                    continue
                                            else:
                                                logger.debug(f"Fallback path failed: {image_protocol_path}")
                                    else:
                                        logger.debug(f"Could not find artist folder in current file path")
                                else:
                                    logger.debug(f"Could not find Music in current file path")
                            else:
                                logger.debug(f"Current file is not an NFS path")
                        else:
                            logger.debug(f"Could not parse artist information path: {original_path}")
                    
                    # Standard image protocol path handling
                    response = kodi_rpc("Files.PrepareDownload", {"path": variant_path})
                    if response and response.get("result") and not response.get("error"):
                        details = response.get("result", {}).get("details", {})
                        token = details.get("token")
                        path = details.get("path")
                        
                        if token:
                            # Extract the original path from the image:// protocol
                            original_path = urllib.parse.unquote(variant_path[len("image://"):])
                            if original_path.endswith("/"):
                                original_path = original_path[:-1]
                            basename = os.path.basename(original_path)
                            image_url = f"{server['host']}/vfs/{token}/{urllib.parse.quote(basename)}"
                        elif path:
                            image_url = f"{server['host']}/{path}"
                        else:
                            continue
                        
                        # Download the fanart variant
                        filename = f"{session_id}_{variant_key}.jpg"
                        local_path = os.path.join(ART_TMP_DIR, filename)
                        
                        try:
                            r = requests.get(image_url, auth=server['auth'], timeout=5)
                            r.raise_for_status()
                            with open(local_path, "wb") as f:
                                f.write(r.content)
                            if _fanart_size_ok(local_path, variant_key):
                                downloaded[variant_key] = filename
                                logger.info(f"Downloaded {variant_key} to {local_path}")
                            else:
                                logger.info(f"Fanart {variant_key} filtered by size threshold")
                        except Exception as e:
                            logger.error(f"Failed to download {variant_key}: {e}")
                    else:
                        logger.debug(f"Failed to prepare download for {variant_key}: {response}")
                elif variant_path.startswith("nfs://"):
                    # Direct NFS path
                    response = kodi_rpc("Files.PrepareDownload", {"path": variant_path})
                    if response and response.get("result") and not response.get("error"):
                        details = response.get("result", {}).get("details", {})
                        token = details.get("token")
                        path = details.get("path")
                        
                        if token:
                            basename = os.path.basename(variant_path)
                            image_url = f"{server['host']}/vfs/{token}/{urllib.parse.quote(basename)}"
                        elif path:
                            image_url = f"{server['host']}/{path}"
                        else:
                            continue
                        
                        # Download the fanart variant
                        filename = f"{session_id}_{variant_key}.jpg"
                        local_path = os.path.join(ART_TMP_DIR, filename)
                        
                        try:
                            r = requests.get(image_url, auth=server['auth'], timeout=5)
                            r.raise_for_status()
                            with open(local_path, "wb") as f:
                                f.write(r.content)
                            if _fanart_size_ok(local_path, variant_key):
                                downloaded[variant_key] = filename
                                logger.info(f"Downloaded {variant_key} to {local_path}")
                            else:
                                logger.info(f"Fanart {variant_key} filtered by size threshold")
                        except Exception as e:
                            logger.error(f"Failed to download {variant_key}: {e}")
                            
            except Exception as e:
                logger.error(f"Failed to process fanart variant {variant_key}: {e}")
            if progress_cb and total_tasks:
                update_art_progress(label)
    
    # Final debug logging
    final_fanart_count = len([k for k in downloaded.keys() if k.startswith(("fanart", "extrafanart"))])
    logger.debug(f"Final downloaded fanart count: {final_fanart_count}")
    logger.debug(f"Downloaded fanart keys: {[k for k in downloaded.keys() if k.startswith(('fanart', 'extrafanart'))]}")
    
    return downloaded

def cleanup_old_artwork_files():
    try:
        now_ts = time.time()
        removed = 0
        protected = cached_art_filenames()
        for filename in os.listdir(ART_TMP_DIR):
            if len(filename) <= ART_FILE_PREFIX_LEN or "_" not in filename:
                continue
            prefix = filename.split("_", 1)[0]
            if len(prefix) != 32 or any(c not in "0123456789abcdef" for c in prefix):
                continue
            if filename in protected:
                continue
            path = os.path.join(ART_TMP_DIR, filename)
            try:
                stat = os.stat(path)
                if (now_ts - stat.st_mtime) >= ART_CLEANUP_AGE_SECONDS:
                    os.remove(path)
                    removed += 1
            except Exception as file_e:
                logger.debug(f"Artwork cleanup skipped {path}: {file_e}")
        if removed:
            logger.info(f"Artwork cleanup removed {removed} files")
    except Exception as e:
        logger.debug(f"Artwork cleanup failed: {e}")

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

@app.route("/media/<filename>")
def serve_image(filename):
    if not ARTWORK_FILENAME_RE.fullmatch(filename):
        return "Invalid image path", 400
    path = resolve_safe_child(ART_TMP_PATH, filename)
    if path and path.exists() and path.is_file():
        return send_file(path, mimetype="image/jpeg")
    return "Image not found", 404

@app.route("/play-button.png")
def play_button():
    try:
        button_path = os.path.join(os.path.dirname(__file__), "play-button.png")
        if os.path.exists(button_path):
            return send_file(button_path, mimetype="image/png")
        else:
            logger.error(f"Play button file not found at: {button_path}")
            return "Play button not found", 404
    except Exception as e:
        logger.error(f"Play button route error: {e}")
        return "Play button error", 500

@app.route("/pause-button.png")
def pause_button():
    try:
        button_path = os.path.join(os.path.dirname(__file__), "pause-button.png")
        if os.path.exists(button_path):
            return send_file(button_path, mimetype="image/png")
        else:
            logger.error(f"Pause button file not found at: {button_path}")
            return "Pause button not found", 404
    except Exception as e:
        logger.error(f"Pause button route error: {e}")
        return "Pause button error", 500

# New route to serve static files like the IMDb icon
@app.route("/static/<filename>")
def serve_static(filename):
    if not STATIC_FILENAME_RE.fullmatch(filename):
        return "Invalid static path", 400
    path = resolve_safe_child(APP_DIR, filename)
    if path and path.exists() and path.is_file():
        return send_file(path)
    return "Static file not found", 404

# Specific favicon route to ensure it works
@app.route("/favicon.ico")
def favicon():
    try:
        favicon_path = os.path.join(os.path.dirname(__file__), "favicon.ico")
        logger.debug(f"Favicon path: {favicon_path}")
        logger.debug(f"Favicon exists: {os.path.exists(favicon_path)}")
        if os.path.exists(favicon_path):
            return send_file(favicon_path, mimetype="image/x-icon")
        else:
            logger.error(f"Favicon file not found at: {favicon_path}")
            return "Favicon not found", 404
    except Exception as e:
        logger.error(f"Favicon route error: {e}")
        return "Favicon error", 500

def build_nowplaying_html(progress_cb=None, session_id=None, as_payload=False):
    def update(progress, message):
        if progress_cb:
            progress_cb(progress, message)

    def _payload(html, *, idle=False, downloaded_art=None, fingerprint=None, title=None, media_type=None, paused=False, used_session_id=None):
        result = {
            "html": html,
            "idle": idle,
            "downloaded_art": downloaded_art or {},
            "fingerprint": fingerprint,
            "title": title,
            "media_type": media_type,
            "paused": paused,
            "session_id": used_session_id,
        }
        return result if as_payload else html

    # Get active players - this is critical, so if it fails, show error
    try:
        update(5, "Checking player")
        active_response = kodi_rpc("Player.GetActivePlayers")
        active = active_response.get("result") if active_response else None
        if not active:
            update(100, "Idle")
            return _payload(render_template_string(index()), idle=True)

        player_id = active[0]["playerid"]
        active_server = get_active_server()
        active_server_id = active_server.get("id") if active_server else None
        
        # Get current item - this is critical, so if it fails, show error
        try:
            update(12, "Loading item")
            item_response = kodi_rpc("Player.GetItem", {
                "playerid": player_id,
                "properties": [
                    "title", "album", "artist", "season", "episode", "showtitle",
                        "tvshowid", "duration", "file", "director", "art", "plot", 
                        "cast", "resume", "genre", "rating", "streamdetails", "year"
                ]
            })
            result = item_response.get("result", {})
            item = result.get("item", {})
        except Exception as e:
            logger.error(f"Failed to get current item: {e}")
            raise e  # This is critical, so re-raise
        
        # Get item type to know which API call to make
        playback_type = item.get("type", "unknown")
        
        # Initialize details with basic fallback structure
        details = {
            "album": {"title": item.get("album", ""), "year": item.get("year", "")},
            "artist": {"label": ", ".join(item.get("artist", [])) if item.get("artist") else "Unknown Artist"}
        }
        if active_server_id is not None:
            details["active_server_id"] = active_server_id
        
        # Get enhanced details for episodes, movies, and songs
        update(20, "Loading metadata")
        logger.debug(f"Playback type detected: {playback_type}")
        logger.debug(f"Available IDs - songid: {item.get('songid')}, albumid: {item.get('albumid')}, artistid: {item.get('artistid')}")
        if playback_type == "episode":
            try:
                update(24, "Loading episode metadata")
                logger.debug(f"Getting enhanced details for episode")
                episode_response = kodi_rpc("VideoLibrary.GetEpisodeDetails", {
                    "episodeid": item.get("id"),
                "properties": ["streamdetails", "genre", "director", "cast", "uniqueid", "rating", "studio"]
            })
                if episode_response and episode_response.get("result"):
                    episode_details = episode_response["result"].get("episodedetails", {})
                    # Merge enhanced details with basic item data
                    details.update(episode_details)
                    # Ensure basic item data is preserved
                    details.update({
                        "title": item.get("title", ""),
                        "plot": item.get("plot", ""),
                        "season": item.get("season", 0),
                        "episode": item.get("episode", 0),
                        "showtitle": item.get("showtitle", ""),
                        "director": item.get("director", []),
                        "cast": item.get("cast", []),
                        "year": item.get("year", "")
                    })
                    logger.debug(f"Enhanced episode details loaded")
                tvshowid = item.get("tvshowid")
                if tvshowid:
                    try:
                        tvshow_response = kodi_rpc("VideoLibrary.GetTVShowDetails", {
                            "tvshowid": tvshowid,
                            "properties": ["studio", "art"]
                        }, server_id=active_server_id)
                        if tvshow_response and tvshow_response.get("result"):
                            tvshow_details = tvshow_response["result"].get("tvshowdetails", {})
                            tvshow_studio = tvshow_details.get("studio", [])
                            if isinstance(tvshow_studio, list) and tvshow_studio:
                                if not details.get("studio"):
                                    details["studio"] = tvshow_studio
                            tvshow_art = tvshow_details.get("art", {})
                            if isinstance(tvshow_art, dict) and tvshow_art:
                                if not isinstance(item.get("art"), dict):
                                    item["art"] = {}
                                for art_key, art_value in tvshow_art.items():
                                    if not art_value:
                                        continue
                                    namespaced_key = f"tvshow.{art_key}"
                                    if namespaced_key not in item["art"]:
                                        item["art"][namespaced_key] = art_value
                    except Exception as e:
                        logger.warning(f"Failed to get tvshow details for episode: {e}")
            except Exception as e:
                logger.warning(f"Failed to get enhanced episode details: {e}")
                logger.debug(f"Using basic item data for {playback_type}")
        elif playback_type == "movie":
            try:
                update(24, "Loading movie metadata")
                logger.debug(f"Getting enhanced details for movie")
                movie_response = kodi_rpc("VideoLibrary.GetMovieDetails", {
                    "movieid": item.get("id"),
                "properties": ["streamdetails", "genre", "director", "cast", "uniqueid", "rating", "studio", "tagline"]
            })
                if movie_response and movie_response.get("result"):
                    movie_details = movie_response["result"].get("moviedetails", {})
                    # Merge enhanced details with basic item data
                    details.update(movie_details)
                    # Ensure basic item data is preserved
                    details.update({
                        "title": item.get("title", ""),
                        "plot": item.get("plot", ""),
                        "director": item.get("director", []),
                        "cast": item.get("cast", []),
                        "year": item.get("year", "")
                    })
                    logger.debug(f"Enhanced movie details loaded")
            except Exception as e:
                logger.warning(f"Failed to get enhanced movie details: {e}")
                logger.debug(f"Using basic item data for {playback_type}")
        elif playback_type == "song":
            try:
                update(24, "Loading song metadata")
                logger.debug(f"Getting enhanced details for song")
                logger.debug(f"Basic item ID: {item.get('id')}")
                # Get song details using the basic item ID
                song_response = kodi_rpc("AudioLibrary.GetSongDetails", {
                    "songid": item.get("id"),
                    "properties": ["title", "album", "artist", "duration", "rating", "year", "genre", "fanart", "thumbnail", "albumid", "artistid", "bitrate", "channels", "samplerate", "bpm", "comment", "lyrics", "mood", "playcount", "track", "disc"]
                })
                if song_response and song_response.get("result"):
                    song_details = song_response["result"].get("songdetails", {})
                    details.update(song_details)
                    logger.debug(f"Enhanced song details loaded")
                
                # Get album details if we have albumid
                albumid = song_details.get("albumid")
                if albumid:
                    try:
                        update(30, "Loading album metadata")
                        album_response = kodi_rpc("AudioLibrary.GetAlbumDetails", {
                            "albumid": albumid,
                            "properties": ["title", "artist", "year", "rating", "fanart", "thumbnail", "description", "genre", "mood", "style", "theme", "albumduration", "playcount", "albumlabel", "compilation", "totaldiscs"]
                        })
                        if album_response and album_response.get("result"):
                            album_details = album_response["result"].get("albumdetails", {})
                            details["album"] = album_details
                            logger.debug(f"Enhanced album details loaded")
                    except Exception as e:
                        logger.warning(f"Failed to get album details: {e}")
                
                # Get artist details if we have artistid
                artistid = song_details.get("artistid")
                if artistid:
                    # Handle artistid as array (take first one) or single value
                    logger.debug(f"Original artistid: {artistid}, type: {type(artistid)}")
                    if isinstance(artistid, list) and len(artistid) > 0:
                        artistid = artistid[0]
                        logger.debug(f"Converted artistid to: {artistid}, type: {type(artistid)}")
                    try:
                        update(34, "Loading artist metadata")
                        artist_response = kodi_rpc("AudioLibrary.GetArtistDetails", {
                            "artistid": artistid,
                            "properties": ["fanart", "thumbnail", "description", "born", "formed", "died", "disbanded", "genre", "mood", "style", "yearsactive"]
                        })
                        if artist_response and artist_response.get("result"):
                            artist_details = artist_response["result"].get("artistdetails", {})
                            details["artist"] = artist_details
                            logger.debug(f"Enhanced artist details loaded")
                    except Exception as e:
                        logger.warning(f"Failed to get artist details: {e}")
                
                # Ensure basic item data is preserved (but don't overwrite detailed album/artist objects)
                details.update({
                    "title": item.get("title", ""),
                    "year": item.get("year", "")
                })
                
            except Exception as e:
                logger.warning(f"Failed to get enhanced song details: {e}")
                logger.debug(f"Using basic item data for {playback_type}")
        else:
            logger.debug(f"Using basic item data for {playback_type}")


        # Playback progress
        update(40, "Loading playback")
        progress_response = kodi_rpc("Player.GetProperties", {
            "playerid": player_id,
            "properties": ["time", "totaltime", "speed"]
        })
        progress = progress_response.get("result") if progress_response else {}
        t = progress.get("time", {})
        d = progress.get("totaltime", {})
        speed = progress.get("speed", 0)
        def to_secs(t): return t.get("hours", 0) * 3600 + t.get("minutes", 0) * 60 + t.get("seconds", 0)
        elapsed = to_secs(t)
        duration = to_secs(d)
        percent = int((elapsed / duration) * 100) if duration else 0
        paused = speed == 0

        cleanup_old_artwork_files()
        fingerprint = make_playback_fingerprint(item)
        active_server_id_for_cache = active_server_id
        if not session_id:
            if active_server_id_for_cache is not None and fingerprint:
                session_id = cache_session_id_for(active_server_id_for_cache, fingerprint)
            else:
                session_id = uuid.uuid4().hex
        
        # Try to download artwork, but don't fail if this breaks
        try:
            update(50, "Loading posters")
            def art_progress(current, total, label):
                if total <= 0:
                    return
                progress = 50 + int((current / total) * 32)
                update(progress, label)
            downloaded_art = prepare_and_download_art(item, session_id, progress_cb=art_progress)
        except Exception as e:
            logger.warning(f"Artwork download failed, continuing without artwork: {e}")
            downloaded_art = {}  # Empty artwork - page will still work

        # Prepare progress data
        update(85, "Rendering")
        progress_data = {
            "elapsed": elapsed,
            "duration": duration,
            "paused": paused
        }

        display_title, overview_media_type = _format_overview_title(item)

        # Check if media type is unknown - if so, show fallback message
        from parser import infer_playback_type
        playback_type_from_parser = infer_playback_type(item)
        if playback_type_from_parser == "unknown":
            logger.info(f"Unknown media type detected, showing fallback message")
            update(100, "Done")
            unknown_html = render_template_string("""
            <!DOCTYPE html>
            <html>
            <head>
                <title>Unknown Media Type</title>
                <style>
                    body {
                        font-family: Arial, sans-serif;
                        background: linear-gradient(to bottom right, #222, #444);
                        color: white;
                        margin: 0;
                        padding: 0;
                        display: flex;
                        justify-content: center;
                        align-items: center;
                        height: 100vh;
                    }
                    .message-box {
                        background: rgba(0,0,0,0.6);
                        padding: 40px;
                        border-radius: 12px;
                        box-shadow: 0 4px 20px rgba(0,0,0,0.8);
                        font-size: 1.5em;
                        text-align: center;
                        max-width: 600px;
                    }
                </style>
            </head>
            <body>
                <div class="message-box">
                    Unknown media type/Media not properly scraped to library.<br>
                    Please scrape and replay media again
                </div>
            </body>
            </html>
            """)
            return _payload(
                unknown_html,
                idle=False,
                downloaded_art=downloaded_art,
                fingerprint=fingerprint,
                title=display_title,
                media_type="other",
                paused=paused,
                used_session_id=session_id,
            )

        # Use the modular system to generate HTML
        html = route_media_display(item, session_id, downloaded_art, progress_data, details)
        update(100, "Done")
        return _payload(
            render_template_string(html),
            idle=False,
            downloaded_art=downloaded_art,
            fingerprint=fingerprint,
            title=display_title,
            media_type=overview_media_type,
            paused=paused,
            used_session_id=session_id,
        )
    except Exception as e:
        logger.error(f"Critical failure in now_playing route: {e}")
        update(100, "Error")
        return _payload(render_template_string(index()), idle=True)

def update_job(job_id: str, progress: int, message: str = None, status: str = "running"):
    with load_lock:
        job = load_jobs.get(job_id)
        if not job:
            return
        job["progress"] = min(100, max(0, int(progress)))
        if message is not None:
            job["message"] = message
        job["status"] = status
        job["updated_at"] = time.time()

def run_nowplaying_job(job_id: str):
    try:
        def progress_cb(progress, message):
            update_job(job_id, progress, message)
        with load_lock:
            job = load_jobs.get(job_id)
            server_id = job.get("server_id") if job else None
        if server_id is not None:
            active_server_override.server_id = server_id
        try:
            with app.app_context():
                payload = build_nowplaying_html(progress_cb, as_payload=True)
                html = payload.get("html") if isinstance(payload, dict) else payload
                with load_lock:
                    job = load_jobs.get(job_id)
                    if job is not None:
                        job["html"] = html
                if server_id is not None and isinstance(payload, dict):
                    if payload.get("idle") or not payload.get("html"):
                        clear_cache_playback(server_id, {"connected": True, "error": None})
                    else:
                        store_playing_cache(server_id, payload)
                update_job(job_id, 100, "Done", status="done")
        finally:
            if hasattr(active_server_override, "server_id"):
                del active_server_override.server_id
    except Exception as e:
        update_job(job_id, 100, f"Error: {str(e)}", status="error")

@app.route("/start-nowplaying-load")
def start_nowplaying_load():
    prune_load_jobs()
    job_id = uuid.uuid4().hex
    server_id = session.get('active_server_id', 1) if has_request_context() else 1
    cached = get_cache_entry(server_id)
    if cached and cached.get("html") and cached.get("playing") and cached.get("cache_ready"):
        with load_lock:
            load_jobs[job_id] = {
                "status": "done",
                "progress": 100,
                "message": "Cached",
                "created_at": time.time(),
                "updated_at": time.time(),
                "html": cached["html"],
                "server_id": server_id,
                "cache_hit": True,
            }
        return jsonify({"job_id": job_id, "cache_hit": True})

    with load_lock:
        load_jobs[job_id] = {
            "status": "pending",
            "progress": 0,
            "message": "Starting",
            "created_at": time.time(),
            "updated_at": time.time(),
            "html": None,
            "server_id": server_id
        }
    thread = threading.Thread(target=run_nowplaying_job, args=(job_id,), daemon=True)
    thread.start()
    return jsonify({"job_id": job_id, "cache_hit": False})

@app.route("/nowplaying-load-status/<job_id>")
def nowplaying_load_status(job_id):
    prune_load_jobs()
    with load_lock:
        job = load_jobs.get(job_id)
        if not job:
            return jsonify({"status": "missing", "progress": 0, "message": "Not found"}), 404
        return jsonify({
            "status": job["status"],
            "progress": job["progress"],
            "message": job.get("message", "")
        })

@app.route("/nowplaying-content/<job_id>")
def nowplaying_content(job_id):
    if job_id == "fallback":
        return "<h1>Loading failed. Please refresh.</h1>", 503
    with load_lock:
        job = load_jobs.get(job_id)
        if not job:
            return "<h1>Loading job not found.</h1>", 404
        if job["status"] != "done" or not job.get("html"):
            return "<h1>Still loading...</h1>", 202
        html_content = job["html"]
        # Free large HTML payload immediately after first successful fetch
        job["html"] = None
        job["status"] = "consumed"
        job["updated_at"] = time.time()
    prune_load_jobs()
    return html_content

@app.route("/loading")
def loading():
    """Return loading screen HTML with animated LOADING text"""
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Loading...</title>
        <link rel="icon" type="image/x-icon" href="/static/favicon.ico">
        <style>
            @import url("https://fonts.googleapis.com/css?family=Montserrat:900");
            
            body {
                background-color: #141414;
                padding: 0;
                margin: 0;
                height: 100vh;
                width: 100vw;
                display: flex;
                align-items: center;
                justify-content: center;
                font-family: "Montserrat", sans-serif;
                opacity: 0;
                animation: fadeIn 0.5s ease forwards;
            }
            
            @keyframes fadeIn {
                from { opacity: 0; }
                to { opacity: 1; }
            }
            
            .loader {
                -webkit-perspective: 700px;
                perspective: 700px;
            }
            
            .loader > span {
                font-size: 130px;
                display: inline-block;
                animation: flip 2.6s infinite linear;
                transform-origin: 0 70%;
                transform-style: preserve-3d;
                -webkit-transform-style: preserve-3d;
                color: #4caf50;
            }
            
            @keyframes flip {
                35% {
                    transform: rotateX(360deg);
                }
                100% {
                    transform: rotateX(360deg);
                }
            }
            
            .loader > span:nth-child(even) {
                color: white;
            }
            
            .loader > span:nth-child(2) {
                animation-delay: 0.3s;
            }
            
            .loader > span:nth-child(3) {
                animation-delay: 0.6s;
            }
            
            .loader > span:nth-child(4) {
                animation-delay: 0.9s;
            }
            
            .loader > span:nth-child(5) {
                animation-delay: 1.2s;
            }
            
            .loader > span:nth-child(6) {
                animation-delay: 1.5s;
            }
            
            .loader > span:nth-child(7) {
                animation-delay: 1.8s;
            }
            
            .loading-bar {
                width: 320px;
                height: 10px;
                background: rgba(255, 255, 255, 0.18);
                border-radius: 999px;
                overflow: hidden;
                margin: 33px auto 0;
            }
            
            .loading-progress {
                height: 100%;
                width: 0%;
                background: linear-gradient(90deg, #4caf50, #7dd3fc);
                transition: width 0.2s ease;
            }
            
            .loading-text {
                margin-top: 10px;
                font-size: 0.9em;
                color: rgba(255, 255, 255, 0.8);
                letter-spacing: 0.5px;
                text-align: center;
            }
        </style>
    </head>
    <body>
        <div class="loader">
            <span>L</span>
            <span>O</span>
            <span>A</span>
            <span>D</span>
            <span>I</span>
            <span>N</span>
            <span>G</span>
            <div class="loading-bar">
                <div id="loading-progress" class="loading-progress"></div>
            </div>
            <div id="loading-text" class="loading-text">Loading 0%</div>
        </div>
        <script>
            const bar = document.getElementById('loading-progress');
            const text = document.getElementById('loading-text');
            let jobId = null;
            let pollTimer = null;

            function setProgress(percent, label) {
                const clamped = Math.min(100, Math.max(0, Math.round(percent)));
                if (bar) {
                    bar.style.width = clamped + '%';
                }
                if (text) {
                    text.textContent = (label ? label + ' ' : 'Loading ') + clamped + '%';
                }
            }

            function pollStatus() {
                if (!jobId) return;
                fetch('/nowplaying-load-status/' + jobId)
                    .then(response => response.json())
                    .then(data => {
                        setProgress(data.progress || 0, data.message || 'Loading');
                        if (data.status === 'done') {
                            clearInterval(pollTimer);
                            fetch('/nowplaying-content/' + jobId)
                                .then(response => response.text())
                                .then(html => {
                                    document.body.style.opacity = '0';
                                    document.body.style.transition = 'opacity 0.5s ease';
                                    setTimeout(() => {
                                        document.open();
                                        document.write(html);
                                        document.close();
                                    }, 500);
                                });
                        } else if (data.status === 'error') {
                            clearInterval(pollTimer);
                            text.textContent = data.message || 'Error loading';
                        }
                    })
                    .catch(() => {
                        // keep polling in case of transient errors
                    });
            }

            function startLoad() {
                fetch('/start-nowplaying-load')
                    .then(response => {
                        if (!response.ok) {
                            throw new Error('HTTP ' + response.status);
                        }
                        return response.json();
                    })
                    .then(data => {
                        jobId = data.job_id;
                        pollTimer = setInterval(pollStatus, 400);
                        pollStatus();
                    })
                    .catch(() => {
                        window.location.href = '/nowplaying';
                    });
            }

            setTimeout(startLoad, 100);
        </script>
    </body>
    </html>
    """

@app.route("/nowplaying")
def now_playing():
    if request.args.get("json") == "1":
        active_response = kodi_rpc("Player.GetActivePlayers")
        active = active_response.get("result") if active_response else None
        if not active:
            return jsonify({"elapsed": 0, "duration": 0, "paused": True})
        player_id = active[0]["playerid"]
        progress_response = kodi_rpc("Player.GetProperties", {
            "playerid": player_id,
            "properties": ["time", "totaltime", "speed"]
        })
        progress = progress_response.get("result") if progress_response else {}
        t = progress.get("time", {})
        d = progress.get("totaltime", {})
        speed = progress.get("speed", 0)
        def to_secs(t): return t.get("hours", 0) * 3600 + t.get("minutes", 0) * 60 + t.get("seconds", 0)
        return jsonify({
            "elapsed": to_secs(t),
            "duration": to_secs(d),
            "paused": speed == 0
        })
    return build_nowplaying_html()

def generate_fallback_html(item, progress_data):
    """Generate basic HTML when the modular system fails"""
    title = html_escape(item.get("title", "Unknown Title"))
    artist = html_escape(", ".join(item.get("artist", [])) if item.get("artist") else "Unknown Artist")
    album = html_escape(item.get("album", ""))
    elapsed = progress_data.get("elapsed", 0)
    duration = progress_data.get("duration", 0)
    paused = progress_data.get("paused", False)
    
    # Format time
    def format_time(seconds):
        if seconds == 0:
            return "0:00"
        minutes = int(seconds // 60)
        secs = int(seconds % 60)
        return f"{minutes}:{secs:02d}"
    
    return f"""
    <html>
    <head>
        <title>Now Playing - {title}</title>
        <style>
            body {{
                margin: 0;
                padding: 0;
                background: linear-gradient(to bottom right, #222, #444);
                font-family: sans-serif;
                color: white;
                display: flex;
                justify-content: center;
                align-items: center;
                height: 100vh;
            }}
            .now-playing {{
                background: rgba(0,0,0,0.6);
                padding: 40px;
                border-radius: 12px;
                box-shadow: 0 4px 20px rgba(0,0,0,0.8);
                text-align: center;
                max-width: 600px;
            }}
            .title {{
                font-size: 2em;
                font-weight: bold;
                margin-bottom: 10px;
            }}
            .artist {{
                font-size: 1.5em;
                margin-bottom: 5px;
                color: #ccc;
            }}
            .album {{
                font-size: 1.2em;
                margin-bottom: 20px;
                color: #aaa;
            }}
            .progress {{
                font-size: 1em;
                color: #888;
            }}
            .status {{
                font-size: 1.2em;
                margin-top: 20px;
                color: {'#ff6b6b' if paused else '#4caf50'};
            }}
        </style>
    </head>
    <body>
        <div class="now-playing">
            <div class="title">{title}</div>
            <div class="artist">{artist}</div>
            <div class="album">{album}</div>
            <div class="progress">{format_time(elapsed)} / {format_time(duration)}</div>
            <div class="status">{'⏸️ Paused' if paused else '▶️ Playing'}</div>
        </div>
    </body>
    </html>
    """

_cache_poller_started = False
_cache_poller_start_lock = threading.Lock()

def start_cache_poller():
    global _cache_poller_started
    if not CACHE_POLLER_ENABLED:
        return
    with _cache_poller_start_lock:
        if _cache_poller_started:
            return
        # Avoid duplicate pollers when the reloader spawns a parent watcher process
        if os.environ.get("WERKZEUG_RUN_MAIN") == "false":
            return
        _cache_poller_started = True
        thread = threading.Thread(target=_cache_poller_loop, daemon=True, name="np-cache-poller")
        thread.start()
        logger.info(
            f"Started now-playing cache poller (interval={CACHE_POLLER_INTERVAL}s, servers={len(KODI_SERVERS)})"
        )


if __name__ == "__main__":
    start_cache_poller()
    app.run(host="0.0.0.0", port=6001)

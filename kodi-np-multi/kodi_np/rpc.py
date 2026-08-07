"""Kodi JSON-RPC client and unreachable-server backoff."""
from __future__ import annotations

import logging
import time

import requests

from kodi_np import config as _c
from kodi_np.servers import get_active_server

logger = logging.getLogger("kodi.nowplaying")

_UNREACHABLE_MARKERS = (
    "No route to host",
    "Connection refused",
    "ConnectTimeout",
    "Connection reset",
    "Connection aborted",
    "Failed to establish a new connection",
    "NewConnectionError",
    "Name or service not known",
    "Network is unreachable",
    "Max retries exceeded",
)


def is_unreachable_rpc_error(error) -> bool:
    """True when the host did not accept an RPC connection (offline / unroutable)."""
    err_text = str(error)
    return any(marker.lower() in err_text.lower() for marker in _UNREACHABLE_MARKERS)


def is_auth_rpc_error(error) -> bool:
    err_text = str(error)
    return "401" in err_text or "unauthorized" in err_text.lower()

def server_backoff_remaining(server_id):
    """Seconds left in unreachable backoff, or 0 if server may be contacted."""
    with _c.server_backoff_lock:
        entry = _c.server_backoff.get(server_id)
        if not entry:
            return 0
        remaining = float(entry.get("backoff_until") or 0) - time.time()
        return max(0, remaining)


def server_backoff_status(server_id):
    with _c.server_backoff_lock:
        entry = dict(_c.server_backoff.get(server_id) or {})
    return {
        "remaining": max(0, float(entry.get("backoff_until") or 0) - time.time()),
        "auth_failed": bool(entry.get("auth_failed")),
        "error": entry.get("last_error"),
    }


def note_server_rpc_success(server_id):
    if server_id is None:
        return
    with _c.server_backoff_lock:
        _c.server_backoff.pop(server_id, None)


def note_server_rpc_failure(server_id, error):
    """Track consecutive connection failures; enter backoff after N in a row."""
    if server_id is None:
        return False
    err_text = str(error)
    if is_auth_rpc_error(error):
        with _c.server_backoff_lock:
            _c.server_backoff[server_id] = {
                "fail_count": 1,
                "backoff_until": time.time() + _c.SERVER_AUTH_BACKOFF_SECONDS,
                "last_error": "Authentication failed",
                "auth_failed": True,
            }
        logger.warning(
            "Server %s authentication failed — pausing polls for %ss",
            server_id,
            _c.SERVER_AUTH_BACKOFF_SECONDS,
        )
        return True
    # Read timeouts are common while Kodi is busy/stopping — do not enter long backoff.
    if "read timed out" in err_text.lower():
        return False
    # Only back off on hard reachability problems (not JSON/RPC logic errors).
    if not is_unreachable_rpc_error(error):
        return False

    with _c.server_backoff_lock:
        entry = _c.server_backoff.get(server_id) or {"fail_count": 0, "backoff_until": 0, "last_error": ""}
        # Host unreachable — not an auth problem (wrong password requires a reachable HTTP 401).
        entry["auth_failed"] = False
        if entry.get("last_error") == "Authentication failed":
            entry["last_error"] = err_text
        # Already in backoff — keep quiet
        if float(entry.get("backoff_until") or 0) > time.time():
            entry["last_error"] = err_text
            _c.server_backoff[server_id] = entry
            return True

        entry["fail_count"] = int(entry.get("fail_count") or 0) + 1
        entry["last_error"] = err_text
        if entry["fail_count"] >= _c.SERVER_FAIL_BACKOFF_AFTER:
            entry["backoff_until"] = time.time() + _c.SERVER_FAIL_BACKOFF_SECONDS
            _c.server_backoff[server_id] = entry
            logger.warning(
                "Server %s unreachable %s times — pausing polls for %ss (%s)",
                server_id,
                entry["fail_count"],
                _c.SERVER_FAIL_BACKOFF_SECONDS,
                err_text.split("(Caused by")[0].strip()[:120],
            )
            return True
        _c.server_backoff[server_id] = entry
        return False


def kodi_rpc(method, params=None, server_id=None, bypass_backoff=False):
    """
    Make RPC call to Kodi server.
    
    Args:
        method: RPC method name
        params: RPC parameters
        server_id: Optional server ID to use (if None, uses active server from session)
        bypass_backoff: If True, attempt RPC even while server is in unreachable backoff
            (used by interactive /poll_playback so stop detection is not frozen).
    """
    # Get server to use
    if server_id and server_id in _c.KODI_SERVERS:
        server = _c.KODI_SERVERS[server_id]
    else:
        server = get_active_server()
    
    if not server:
        logger.error(f"No Kodi server available")
        return None

    sid = server.get("id")
    remaining = server_backoff_remaining(sid)
    if remaining > 0 and not bypass_backoff:
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
            headers=_c.HEADERS,
            json=payload,
            auth=server['auth'],
            timeout=_c.KODI_RPC_TIMEOUT,
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

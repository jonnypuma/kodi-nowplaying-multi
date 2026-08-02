"""Health and overview API."""
from __future__ import annotations

import logging

from flask import Blueprint, jsonify

from kodi_np import config as _c
from kodi_np.cache import cache_diagnostics, clear_cache_playback, overview_from_cache, refresh_server_cache
from kodi_np.overview import get_server_overview_status
from kodi_np.rpc import note_server_rpc_success, server_backoff_remaining

logger = logging.getLogger("kodi.nowplaying")

bp = Blueprint("overview_api", __name__)


@bp.route("/health")
def health():
    """Liveness endpoint for Docker healthchecks and uptime monitors."""
    return jsonify({
        "status": "ok",
        "version": _c.APP_VERSION,
        "servers_configured": len(_c.KODI_SERVERS),
    }), 200


@bp.route("/health/live")
def health_live():
    return jsonify({"status": "ok", "version": _c.APP_VERSION}), 200


@bp.route("/health/ready")
def health_ready():
    ready = bool(_c.KODI_SERVERS)
    return jsonify({
        "status": "ready" if ready else "not_ready",
        "version": _c.APP_VERSION,
        "servers_configured": len(_c.KODI_SERVERS),
    }), (200 if ready else 503)


@bp.route("/api/diagnostics")
def diagnostics():
    servers = []
    for server_id, server in sorted(_c.KODI_SERVERS.items()):
        entry = overview_from_cache(server_id) or {}
        servers.append({
            "id": server_id,
            "label": server.get("label") or "",
            "host": server.get("host"),
            "connected": entry.get("connected"),
            "playing": entry.get("playing"),
            "error": entry.get("error"),
            "backoff_remaining": entry.get("backoff_remaining", 0),
        })
    return jsonify({
        "version": _c.APP_VERSION,
        "cache": cache_diagnostics(),
        "servers": servers,
    })


@bp.route("/api/overview")
def api_overview():
    """Status snapshot for every configured Kodi server (prefers warm cache)."""
    servers = []
    if not _c.KODI_SERVERS:
        return jsonify({"servers": servers})

    for server_id in sorted(_c.KODI_SERVERS.keys()):
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


@bp.route("/api/retry-server/<int:server_id>", methods=["POST"])
def retry_server(server_id):
    """Clear unreachable backoff and immediately re-probe one Kodi server."""
    if server_id not in _c.KODI_SERVERS:
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

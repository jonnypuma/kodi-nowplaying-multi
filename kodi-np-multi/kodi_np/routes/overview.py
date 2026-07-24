"""Health and overview API."""
from __future__ import annotations

import logging

from flask import Blueprint, jsonify

from kodi_np import config as _c
from kodi_np.cache import clear_cache_playback, overview_from_cache, refresh_server_cache
from kodi_np.overview import get_server_overview_status
from kodi_np.rpc import note_server_rpc_success, server_backoff_remaining

logger = logging.getLogger("kodi.nowplaying")

bp = Blueprint("overview_api", __name__)


@bp.route("/health")
def health():
    """Liveness endpoint for Docker healthchecks and uptime monitors."""
    return jsonify({
        "status": "ok",
        "servers_configured": len(_c.KODI_SERVERS),
    }), 200


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

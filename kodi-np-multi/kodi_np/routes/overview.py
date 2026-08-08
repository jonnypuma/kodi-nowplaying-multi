"""Health and overview API."""
from __future__ import annotations

import logging

from flask import Blueprint, jsonify

from kodi_np import config as _c
from kodi_np.cache import cache_diagnostics, clear_cache_playback, overview_from_cache, refresh_server_cache
from kodi_np.overview import overview_fast_snapshot, overview_live_status
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
    """Fast status snapshot from cache/config only (no blocking Kodi RPC)."""
    servers = []
    if not _c.KODI_SERVERS:
        return jsonify({"servers": servers})

    for server_id in sorted(_c.KODI_SERVERS.keys()):
        snapshot = overview_fast_snapshot(server_id)
        if snapshot is not None:
            servers.append(snapshot)

    return jsonify({"servers": servers})


@bp.route("/api/overview-server/<int:server_id>")
def api_overview_server(server_id):
    """Live probe for one Kodi server (used for parallel overview tile updates)."""
    if server_id not in _c.KODI_SERVERS:
        return jsonify({"success": False, "error": "Server not found"}), 404
    return jsonify({"success": True, "server": overview_live_status(server_id)})


@bp.route("/api/overview/all", methods=["GET"])
def api_overview_all():
    """Legacy: sequential live probe for every server (slow; prefer /api/overview + parallel /api/overview-server)."""
    servers = []
    if not _c.KODI_SERVERS:
        return jsonify({"servers": servers})

    for server_id in sorted(_c.KODI_SERVERS.keys()):
        servers.append(overview_live_status(server_id))

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

    status = overview_live_status(server_id)

    return jsonify({"success": True, "server": status})

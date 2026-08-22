"""Server selection and preferences API."""
from __future__ import annotations

import logging

from flask import Blueprint, jsonify, request, session

import requests

from kodi_np import config as _c
from kodi_np.preferences import (
    ensure_preferences_dir,
    get_persisted_server_id,
    public_preferences,
    set_persisted_server_id,
    update_preferences,
    validate_preferences_update,
)
from kodi_np.servers import (
    add_custom_server,
    delete_custom_server,
    public_server_payload,
    update_custom_server,
)

logger = logging.getLogger("kodi.nowplaying")

bp = Blueprint("servers_prefs", __name__)


@bp.route("/api/servers")
def get_servers():
    """Get list of available Kodi servers, sorted by IP"""
    servers_list = [public_server_payload(server) for server in _c.KODI_SERVERS.values()]

    def _sort_key(item):
        parts = [int(part) for part in item["ip"].split(".") if part.isdigit()]
        return parts or [item["id"]]

    servers_list.sort(key=_sort_key)
    return jsonify({"servers": servers_list})


@bp.route("/api/servers", methods=["POST"])
def create_server():
    payload = request.get_json(silent=True) or {}
    server, error = add_custom_server(
        payload.get("host") or "",
        payload.get("username") or "",
        payload.get("password") or "",
        payload.get("label") or "",
    )
    if error:
        return jsonify({"success": False, "error": error}), 400
    return jsonify({"success": True, "server": public_server_payload(server)})


@bp.route("/api/servers/<int:server_id>", methods=["PUT", "PATCH"])
def edit_server(server_id):
    payload = request.get_json(silent=True) or {}
    server, error = update_custom_server(
        server_id,
        host=payload.get("host"),
        username=payload.get("username"),
        password=payload.get("password"),
        label=payload.get("label"),
    )
    if error:
        return jsonify({"success": False, "error": error}), 400
    return jsonify({"success": True, "server": public_server_payload(server)})


@bp.route("/api/servers/<int:server_id>", methods=["DELETE"])
def remove_server(server_id):
    ok, error = delete_custom_server(server_id)
    if not ok:
        return jsonify({"success": False, "error": error}), 400
    if session.get("active_server_id") == server_id:
        session.pop("active_server_id", None)
    return jsonify({"success": True})

@bp.route("/api/test-connection/<int:server_id>")
def test_connection(server_id):
    """Test connection to a specific Kodi server"""
    if server_id not in _c.KODI_SERVERS:
        return jsonify({"connected": False, "error": "Server not found"}), 404
    
    server = _c.KODI_SERVERS[server_id]
    
    try:
        # Try a simple RPC call to test connection
        payload = {
            "jsonrpc": "2.0",
            "method": "JSONRPC.Version",
            "params": {},
            "id": 1
        }
        r = requests.post(f"{server['host']}/jsonrpc", headers=_c.HEADERS, json=payload, auth=server['auth'], timeout=5)
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

@bp.route("/api/switch-server/<int:server_id>", methods=["POST"])
def switch_server(server_id):
    """Switch the active Kodi server"""
    if server_id not in _c.KODI_SERVERS:
        return jsonify({"success": False, "error": "Server not found"}), 404
    
    session['active_server_id'] = server_id
    set_persisted_server_id(server_id)
    return jsonify({"success": True, "server_id": server_id})

@bp.route("/api/current-server")
def get_current_server():
    """Get the currently active server ID"""
    server_id = session.get('active_server_id', 1)
    if server_id not in _c.KODI_SERVERS:
        persisted = get_persisted_server_id()
        if persisted:
            server_id = persisted
            session['active_server_id'] = persisted
        else:
            server_id = 1 if _c.KODI_SERVERS else None
    return jsonify({"server_id": server_id})

@bp.before_app_request
def hydrate_server_session():
    try:
        server_id = session.get('active_server_id')
        if server_id not in _c.KODI_SERVERS:
            persisted = get_persisted_server_id()
            if persisted and persisted in _c.KODI_SERVERS:
                session['active_server_id'] = persisted
    except Exception as e:
        logger.warning(f"Failed to hydrate active server: {e}")

@bp.route("/api/preferences", methods=["GET"])
def get_preferences():
    """Get user preferences"""
    prefs = public_preferences()
    logger.debug("GET preferences request, returning keys: %s", list(prefs.keys()))
    return jsonify(prefs)

@bp.route("/api/preferences/test", methods=["GET"])
def test_preferences():
    """Test if preferences directory is writable"""
    try:
        ensure_preferences_dir()
        test_file = _c.PREFERENCES_DIR / "test.txt"
        test_file.write_text("test")
        test_file.unlink()
        return jsonify({
            "success": True,
            "directory": str(_c.PREFERENCES_DIR),
            "directory_exists": _c.PREFERENCES_DIR.exists(),
            "writable": True
        })
    except Exception as e:
        return jsonify({
            "success": False,
            "directory": str(_c.PREFERENCES_DIR),
            "directory_exists": _c.PREFERENCES_DIR.exists() if _c.PREFERENCES_DIR else False,
            "writable": False,
            "error": str(e)
        }), 500

@bp.route("/api/preferences", methods=["POST"])
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

        if update_preferences(sanitized):
            logger.debug("Preferences saved successfully")
            return jsonify({"success": True})
        logger.error("update_preferences returned False")
        return jsonify({"success": False, "error": "Failed to save preferences"}), 500
    except Exception as e:
        logger.error(f"Failed to set preferences: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        return jsonify({"success": False, "error": str(e)}), 500

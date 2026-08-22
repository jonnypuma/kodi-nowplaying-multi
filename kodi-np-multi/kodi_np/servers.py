"""Kodi server registry and active-server selection."""
from __future__ import annotations

import os
import re
import urllib.parse

from flask import has_request_context, session

from kodi_np import config as _c
from kodi_np.secretbox import decrypt_secret, encrypt_secret

CUSTOM_SERVER_ID_START = 100
_HOST_RE = re.compile(r"^https?://.+$", re.IGNORECASE)


def _server_entry(server_id, host, username="", password="", label="", source="env"):
    host = (host or "").strip().rstrip("/")
    username = username or ""
    password = password or ""
    label = (label or "").strip()
    ip_match = re.search(r"(\d+\.\d+\.\d+\.\d+)", host)
    ip = ip_match.group(1) if ip_match else host
    return {
        "id": server_id,
        "host": host,
        "username": username,
        "password": password,
        "auth": (username, password) if username else None,
        "ip": ip,
        "label": label,
        "source": source,
    }


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

        servers[i] = _server_entry(
            i,
            host,
            os.getenv(user_key, ""),
            os.getenv(pass_key, ""),
            os.getenv(label_key) or "",
            source="env",
        )
        i += 1

    if not servers:
        legacy_host = os.getenv("KODI_HOST")
        if legacy_host:
            legacy_user = os.getenv("KODI_USER", os.getenv("KODI_USERNAME", ""))
            legacy_pass = os.getenv("KODI_PASS", os.getenv("KODI_PASSWORD", ""))
            legacy_label = (os.getenv("KODI_HOST_LABEL") or "").strip()
            servers[1] = _server_entry(
                1, legacy_host, legacy_user, legacy_pass, legacy_label, source="env"
            )

    return servers


def _custom_servers_from_prefs():
    from kodi_np.preferences import load_preferences

    prefs = load_preferences()
    raw = prefs.get("custom_servers") or []
    servers = {}
    stale_plaintext = False
    if not isinstance(raw, list):
        return servers, stale_plaintext
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        try:
            server_id = int(entry.get("id"))
        except (TypeError, ValueError):
            continue
        host = (entry.get("host") or "").strip()
        if not host or server_id < CUSTOM_SERVER_ID_START:
            continue
        encrypted = entry.get("password_enc") or ""
        legacy = entry.get("password") or ""
        if encrypted:
            password = decrypt_secret(encrypted)
        elif legacy:
            password = legacy
            stale_plaintext = True
        else:
            password = ""
        servers[server_id] = _server_entry(
            server_id,
            host,
            entry.get("username") or "",
            password,
            entry.get("label") or "",
            source="custom",
        )
    return servers, stale_plaintext


def _dump_custom_servers():
    dumped = []
    for server_id, server in sorted(_c.KODI_SERVERS.items()):
        if server.get("source") != "custom":
            continue
        row = {
            "id": server_id,
            "host": server.get("host") or "",
            "username": server.get("username") or "",
            "label": server.get("label") or "",
        }
        secret = server.get("password") or ""
        if secret:
            row["password_enc"] = encrypt_secret(secret)
        dumped.append(row)
    return dumped


def persist_custom_servers():
    from kodi_np.preferences import update_preferences

    return update_preferences({"custom_servers": _dump_custom_servers()})


def validate_server_host(host: str):
    host = (host or "").strip()
    if not _HOST_RE.match(host):
        return None, "Host must start with http:// or https://"
    host = host.rstrip("/")
    allowlist = getattr(_c, "KODI_HOST_ALLOWLIST", ())
    if allowlist:
        try:
            hostname = (urllib.parse.urlsplit(host).hostname or "").lower()
        except ValueError:
            hostname = ""
        if hostname not in allowlist:
            return None, "Host is not permitted by KODI_HOST_ALLOWLIST"
    return host, None


def next_custom_server_id():
    custom_ids = [sid for sid, srv in _c.KODI_SERVERS.items() if srv.get("source") == "custom"]
    if not custom_ids:
        return CUSTOM_SERVER_ID_START
    return max(custom_ids) + 1


def add_custom_server(host, username="", password="", label=""):
    host, error = validate_server_host(host)
    if error:
        return None, error
    server_id = next_custom_server_id()
    _c.KODI_SERVERS[server_id] = _server_entry(
        server_id, host, username, password, label, source="custom"
    )
    persist_custom_servers()
    return _c.KODI_SERVERS[server_id], None


def update_custom_server(server_id, host=None, username=None, password=None, label=None):
    server = _c.KODI_SERVERS.get(server_id)
    if not server or server.get("source") != "custom":
        return None, "Only custom servers can be edited"
    if host is not None:
        host, error = validate_server_host(host)
        if error:
            return None, error
        server["host"] = host
        ip_match = re.search(r"(\d+\.\d+\.\d+\.\d+)", host)
        server["ip"] = ip_match.group(1) if ip_match else host
    if username is not None:
        server["username"] = username
    if password is not None:
        server["password"] = password
    if label is not None:
        server["label"] = (label or "").strip()
    server["auth"] = (server["username"], server["password"]) if server.get("username") else None
    persist_custom_servers()
    return server, None


def delete_custom_server(server_id):
    server = _c.KODI_SERVERS.get(server_id)
    if not server or server.get("source") != "custom":
        return False, "Only custom servers can be removed"
    _c.KODI_SERVERS.pop(server_id, None)
    persist_custom_servers()
    return True, None


def public_server_payload(server):
    return {
        "id": server["id"],
        "host": server["host"],
        "ip": server.get("ip") or "",
        "label": server.get("label") or "",
        "name": server_display_name(server),
        "source": server.get("source") or "env",
        "editable": (server.get("source") == "custom"),
        "has_auth": bool(server.get("username")),
    }


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


def get_active_server():
    """Get the currently active server from session, or default to first server"""
    if has_request_context():
        server_id = session.get("active_server_id", 1)
        if server_id in _c.KODI_SERVERS:
            return _c.KODI_SERVERS[server_id]
    else:
        server_id = getattr(_c.active_server_override, "server_id", None)
        if server_id in _c.KODI_SERVERS:
            return _c.KODI_SERVERS[server_id]
    if _c.KODI_SERVERS:
        return list(_c.KODI_SERVERS.values())[0]
    return None


def init_servers():
    """Populate config.KODI_SERVERS from environment + persisted custom hosts."""
    servers = parse_kodi_servers()
    stale_plaintext = False
    try:
        custom, stale_plaintext = _custom_servers_from_prefs()
        servers.update(custom)
    except Exception:
        pass
    _c.KODI_SERVERS.clear()
    _c.KODI_SERVERS.update(servers)
    if stale_plaintext:
        persist_custom_servers()
    return _c.KODI_SERVERS

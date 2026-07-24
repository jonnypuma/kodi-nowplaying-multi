"""Kodi server registry and active-server selection."""
from __future__ import annotations

import os
import re

from flask import has_request_context, session

from kodi_np import config as _c

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


def get_active_server():
    """Get the currently active server from session, or default to first server"""
    if has_request_context():
        server_id = session.get('active_server_id', 1)
        if server_id in _c.KODI_SERVERS:
            return _c.KODI_SERVERS[server_id]
    else:
        server_id = getattr(_c.active_server_override, "server_id", None)
        if server_id in _c.KODI_SERVERS:
            return _c.KODI_SERVERS[server_id]
    # Fallback to first server
    if _c.KODI_SERVERS:
        return list(_c.KODI_SERVERS.values())[0]
    return None


def init_servers():
    """Populate config.KODI_SERVERS from environment (in-place so aliases stay valid)."""
    servers = parse_kodi_servers()
    _c.KODI_SERVERS.clear()
    _c.KODI_SERVERS.update(servers)
    return _c.KODI_SERVERS

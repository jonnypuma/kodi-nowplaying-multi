"""Persisted UI preferences and active-server id."""
from __future__ import annotations

import json
import logging
import os
import uuid

from kodi_np import config as _c

logger = logging.getLogger("kodi.nowplaying")

# load_preferences() sits on the artwork and polling hot paths, where it was
# reopening and reparsing preferences.json on every call. Cache the parsed dict
# and reuse it while the file's identity, size, and mtime are unchanged.
_prefs_cache_key = None
_prefs_cache_value: dict = {}


def _preferences_stat_key():
    """Cheap fingerprint of preferences.json, or None when it is missing."""
    try:
        stat = _c.PREFERENCES_FILE.stat()
    except OSError:
        return None
    return (str(_c.PREFERENCES_FILE), stat.st_mtime_ns, stat.st_size)


def invalidate_preferences_cache():
    """Force the next load_preferences() to re-read from disk."""
    global _prefs_cache_key
    _prefs_cache_key = None


def ensure_preferences_dir():
    """Ensure the preferences directory exists"""
    try:
        _c.PREFERENCES_DIR.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        logger.error("Failed to create preferences directory: %s", e, exc_info=True)


def _read_preferences_unlocked():
    """Read preferences file. Caller must hold PREFERENCES_LOCK for RMW."""
    if not _c.PREFERENCES_FILE.exists():
        return {}
    try:
        with open(_c.PREFERENCES_FILE, "r") as f:
            prefs = json.load(f)
        if not isinstance(prefs, dict):
            logger.warning("Preferences file contains non-dict data, returning empty dict")
            return {}
        return prefs
    except (json.JSONDecodeError, OSError) as e:
        logger.error(f"Failed to load preferences: {e}")
        return {}


def _write_preferences_unlocked(prefs):
    """Atomic write. Caller must hold PREFERENCES_LOCK."""
    if not isinstance(prefs, dict):
        logger.error(f"Cannot save preferences - not a dict: {type(prefs)}")
        return False

    temp_file = _c.PREFERENCES_DIR / f"preferences.{uuid.uuid4().hex}.tmp"
    try:
        with open(temp_file, "w") as f:
            json.dump(prefs, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        temp_file.replace(_c.PREFERENCES_FILE)
        invalidate_preferences_cache()
        return True
    except OSError as e:
        logger.error(f"Failed to save preferences: {e}")
        try:
            if temp_file.exists():
                temp_file.unlink()
        except OSError:
            pass
        return False


def load_preferences():
    """Load preferences from JSON file, reparsing only when it changed on disk."""
    global _prefs_cache_key, _prefs_cache_value
    ensure_preferences_dir()
    with _c.PREFERENCES_LOCK:
        key = _preferences_stat_key()
        if key is not None and key == _prefs_cache_key:
            return dict(_prefs_cache_value)

        prefs = _read_preferences_unlocked()
        _prefs_cache_key = key
        _prefs_cache_value = prefs
        if prefs:
            logger.debug("Loaded preference keys from file: %s", list(prefs.keys()))
        else:
            logger.debug("Preferences file empty or missing: %s", _c.PREFERENCES_FILE)
        return dict(prefs)


def save_preferences(prefs):
    """Replace preferences file contents (full write)."""
    ensure_preferences_dir()
    with _c.PREFERENCES_LOCK:
        ok = _write_preferences_unlocked(prefs)
        if ok:
            logger.debug(f"Successfully saved preferences to {_c.PREFERENCES_FILE}")
        return ok


def update_preferences(updates):
    """Atomically merge updates into preferences.json (safe under concurrent POSTs)."""
    if not isinstance(updates, dict) or not updates:
        return False
    ensure_preferences_dir()
    with _c.PREFERENCES_LOCK:
        prefs = _read_preferences_unlocked()
        prefs.update(updates)
        ok = _write_preferences_unlocked(prefs)
        if ok:
            logger.debug(f"Merged preference keys: {list(updates.keys())}")
        return ok


def validate_preferences_update(data):
    """Return sanitized preference values or an error message."""
    if not isinstance(data, dict):
        return None, "Preferences must be a JSON object"

    sanitized = {}
    allowed_keys = set(_c.PREFERENCE_ENUMS) | set(_c.PREFERENCE_RANGES)
    unknown_keys = sorted(set(data) - allowed_keys)
    if unknown_keys:
        return None, f"Unsupported preference key(s): {', '.join(unknown_keys)}"

    for key, allowed_values in _c.PREFERENCE_ENUMS.items():
        if key not in data:
            continue
        value = str(data[key])
        if value not in allowed_values:
            return None, f"Invalid value for {key}"
        sanitized[key] = value

    for key, (min_value, max_value) in _c.PREFERENCE_RANGES.items():
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


def public_preferences(prefs=None):
    """Preferences safe to send to the browser: no Kodi passwords, even encrypted."""
    data = dict(prefs if prefs is not None else load_preferences())
    raw = data.get("custom_servers")
    if not isinstance(raw, list):
        return data
    cleaned = []
    for entry in raw:
        if not isinstance(entry, dict):
            cleaned.append(entry)
            continue
        row = {
            key: value
            for key, value in entry.items()
            if key not in ("password", "password_enc")
        }
        row["has_auth"] = bool(
            entry.get("username") or entry.get("password") or entry.get("password_enc")
        )
        cleaned.append(row)
    data["custom_servers"] = cleaned
    return data


def get_persisted_server_id():
    prefs = load_preferences()
    server_id = prefs.get("active_server_id")
    try:
        server_id = int(server_id)
    except (TypeError, ValueError):
        return None
    return server_id if server_id in _c.KODI_SERVERS else None


def set_persisted_server_id(server_id: int):
    return update_preferences({"active_server_id": server_id})

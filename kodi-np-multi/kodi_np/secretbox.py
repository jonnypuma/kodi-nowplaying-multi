"""Encrypt custom-server Kodi passwords at rest in preferences.json.

The Fernet key is derived from the Flask secret, so a container restart with
the same ``FLASK_SECRET_KEY`` (or the persisted ``flask_secret_key`` file)
can still decrypt. Changing that secret makes stored passwords unreadable,
same as it invalidates sessions.
"""
from __future__ import annotations

import base64
import hashlib
import logging

from cryptography.fernet import Fernet, InvalidToken

from kodi_np import config as _c

logger = logging.getLogger("kodi.nowplaying")

PREFIX = "enc:v1:"
_fernet = None
_fernet_key_id = None


def _key_material() -> bytes:
    secret = _c.app.secret_key
    if isinstance(secret, str):
        secret = secret.encode("utf-8")
    return secret or b"kodi-np-multi"


def _box() -> Fernet:
    global _fernet, _fernet_key_id
    material = _key_material()
    if _fernet is not None and _fernet_key_id == material:
        return _fernet
    key = base64.urlsafe_b64encode(hashlib.sha256(material).digest())
    _fernet = Fernet(key)
    _fernet_key_id = material
    return _fernet


def encrypt_secret(plain: str) -> str:
    text = plain or ""
    if not text:
        return ""
    token = _box().encrypt(text.encode("utf-8")).decode("ascii")
    return PREFIX + token


def decrypt_secret(stored: str) -> str:
    """Decrypt a ``enc:v1:`` blob, or return legacy plaintext as-is."""
    raw = stored or ""
    if not raw:
        return ""
    if not raw.startswith(PREFIX):
        return raw
    try:
        return _box().decrypt(raw[len(PREFIX):].encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError, TypeError):
        logger.warning("Could not decrypt a stored Kodi password; treating it as empty")
        return ""


def is_encrypted_secret(stored: str) -> bool:
    return (stored or "").startswith(PREFIX)

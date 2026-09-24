"""Kodi Now Playing application package."""
from __future__ import annotations

__all__ = ["create_app"]


def create_app():
    from kodi_np.app import create_app as _create_app
    return _create_app()

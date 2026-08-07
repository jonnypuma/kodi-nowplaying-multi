"""Flask application factory."""
from __future__ import annotations

import logging

from kodi_np import config as _c
from kodi_np.cache import start_cache_poller  # noqa: F401 — re-exported by entry
from kodi_np.routes import register_blueprints
from kodi_np.servers import init_servers

logger = logging.getLogger("kodi.nowplaying")

_blueprints_registered = False


def create_app():
    """Create and configure the Flask app (singleton in config.app)."""
    global _blueprints_registered
    init_servers()
    if not _blueprints_registered:
        register_blueprints(_c.app)
        _blueprints_registered = True
    start_cache_poller()
    return _c.app


app = create_app()

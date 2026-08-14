"""HTTP route blueprints."""
from __future__ import annotations


def register_blueprints(app):
    from kodi_np.auth import bp as auth_bp
    from kodi_np.routes.pages import bp as pages_bp
    from kodi_np.routes.playback import bp as playback_bp
    from kodi_np.routes.servers_prefs import bp as servers_prefs_bp
    from kodi_np.routes.static_media import bp as static_media_bp
    from kodi_np.routes.overview import bp as overview_bp
    from kodi_np.routes.extras import bp as extras_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(servers_prefs_bp)
    app.register_blueprint(overview_bp)
    app.register_blueprint(extras_bp)
    from kodi_np.routes.events import bp as events_bp
    app.register_blueprint(events_bp)
    app.register_blueprint(pages_bp)
    app.register_blueprint(playback_bp)
    app.register_blueprint(static_media_bp)

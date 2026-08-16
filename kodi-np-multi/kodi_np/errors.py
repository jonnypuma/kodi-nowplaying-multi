"""Application-wide error handling.

Without these, a bad path under ``/api`` returns Werkzeug's HTML error page,
which the front-end JSON parsers choke on, and an unhandled exception leaks a
stack trace when Flask runs in debug.
"""
from __future__ import annotations

import logging

from flask import jsonify, render_template, request
from werkzeug.exceptions import HTTPException

logger = logging.getLogger("kodi.nowplaying")


def wants_json() -> bool:
    """True when the caller expects JSON rather than an HTML error page."""
    if request.path.startswith("/api/"):
        return True
    accept = request.accept_mimetypes
    return bool(accept.accept_json and not accept.accept_html)


def register_error_handlers(app):
    @app.errorhandler(HTTPException)
    def handle_http_exception(exc: HTTPException):
        code = exc.code or 500
        if wants_json():
            return jsonify({
                "success": False,
                "error": exc.name,
                "status": code,
            }), code
        return render_template(
            "error.html",
            code=code,
            name=exc.name,
            description=exc.description,
        ), code

    @app.errorhandler(Exception)
    def handle_unexpected_exception(exc: Exception):
        logger.exception("Unhandled error on %s %s", request.method, request.path)
        if wants_json():
            return jsonify({
                "success": False,
                "error": "Internal Server Error",
                "status": 500,
            }), 500
        return render_template(
            "error.html",
            code=500,
            name="Internal Server Error",
            description="Something went wrong while building this page. "
                        "Check the container logs for details.",
        ), 500

    return app

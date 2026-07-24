"""Artwork and static asset routes."""
from __future__ import annotations

import logging
import os

from flask import Blueprint, send_file

from kodi_np import config as _c
from kodi_np.art import resolve_safe_child

logger = logging.getLogger("kodi.nowplaying")

bp = Blueprint("static_media", __name__)


@bp.route("/media/<filename>")
def serve_image(filename):
    if not _c.ARTWORK_FILENAME_RE.fullmatch(filename):
        return "Invalid image path", 400
    path = resolve_safe_child(_c.ART_TMP_PATH, filename)
    if path and path.exists() and path.is_file():
        return send_file(path, mimetype="image/jpeg")
    return "Image not found", 404


@bp.route("/play-button.png")
def play_button():
    try:
        button_path = os.path.join(str(_c.APP_DIR), "play-button.png")
        if os.path.exists(button_path):
            return send_file(button_path, mimetype="image/png")
        logger.error("Play button file not found at: %s", button_path)
        return "Play button not found", 404
    except Exception as e:
        logger.error("Play button route error: %s", e)
        return "Play button error", 500


@bp.route("/pause-button.png")
def pause_button():
    try:
        button_path = os.path.join(str(_c.APP_DIR), "pause-button.png")
        if os.path.exists(button_path):
            return send_file(button_path, mimetype="image/png")
        logger.error("Pause button file not found at: %s", button_path)
        return "Pause button not found", 404
    except Exception as e:
        logger.error("Pause button route error: %s", e)
        return "Pause button error", 500


@bp.route("/static/<filename>")
def serve_static(filename):
    if not _c.STATIC_FILENAME_RE.fullmatch(filename):
        return "Invalid static path", 400
    path = resolve_safe_child(_c.APP_DIR, filename)
    if path and path.exists() and path.is_file():
        return send_file(path)
    return "Static file not found", 404


@bp.route("/favicon.ico")
def favicon():
    try:
        favicon_path = os.path.join(str(_c.APP_DIR), "favicon.ico")
        logger.debug("Favicon path: %s", favicon_path)
        logger.debug("Favicon exists: %s", os.path.exists(favicon_path))
        if os.path.exists(favicon_path):
            return send_file(favicon_path, mimetype="image/x-icon")
        logger.error("Favicon file not found at: %s", favicon_path)
        return "Favicon not found", 404
    except Exception as e:
        logger.error("Favicon route error: %s", e)
        return "Favicon error", 500

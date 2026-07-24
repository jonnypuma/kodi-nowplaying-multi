"""Static app pages (Jinja)."""
from __future__ import annotations

from flask import Blueprint, render_template

bp = Blueprint("pages", __name__)


@bp.route("/overview")
def overview_page():
    """Multi-Kodi wall: idle / playing / offline tiles for all configured servers."""
    return render_template("overview.html")


@bp.route("/")
def index():
    return render_template("index.html")


@bp.route("/loading")
def loading():
    return render_template("loading.html")

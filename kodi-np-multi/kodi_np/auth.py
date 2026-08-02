"""Optional session-based HTTP Basic Auth configuration and login flow."""
from __future__ import annotations

import hmac

from flask import Blueprint, redirect, render_template, request, session, url_for

from kodi_np import config as _c

bp = Blueprint("auth", __name__)


def auth_enabled() -> bool:
    return bool(_c.BASIC_AUTH)


def _credentials() -> tuple[str, str]:
    if ":" not in _c.BASIC_AUTH:
        return _c.BASIC_AUTH, ""
    return tuple(_c.BASIC_AUTH.split(":", 1))  # type: ignore[return-value]


def is_authenticated() -> bool:
    return not auth_enabled() or bool(session.get("web_authenticated"))


@bp.before_app_request
def require_login():
    if not auth_enabled() or is_authenticated():
        return None
    if request.endpoint in {
        "auth.login",
        "auth.logout",
        "static_media.favicon",
        "static_media.serve_static",
        "overview_api.health",
        "overview_api.health_live",
        "overview_api.health_ready",
    }:
        return None
    if request.path.startswith("/static/") or request.path == "/favicon.ico":
        return None
    if request.method == "GET" and not request.path.startswith("/api/"):
        return redirect(url_for("auth.login", next=request.full_path))
    return ("Authentication required", 401)


@bp.route("/login", methods=["GET", "POST"])
def login():
    if not auth_enabled():
        return redirect(url_for("pages.index"))
    next_url = request.args.get("next") or request.form.get("next") or "/"
    error = None
    if request.method == "POST":
        username, password = _credentials()
        supplied_user = request.form.get("username", "")
        supplied_password = request.form.get("password", "")
        if hmac.compare_digest(supplied_user, username) and hmac.compare_digest(
            supplied_password, password
        ):
            session["web_authenticated"] = True
            return redirect(next_url if next_url.startswith("/") else "/")
        error = "Those credentials were not accepted."
    return render_template("login.html", error=error, next=next_url)


@bp.route("/logout", methods=["POST"])
def logout():
    session.pop("web_authenticated", None)
    return redirect(url_for("auth.login"))

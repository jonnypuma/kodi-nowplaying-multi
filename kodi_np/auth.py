"""Optional session-based HTTP Basic Auth configuration and login flow."""
from __future__ import annotations

import hmac
import threading
import time

from flask import Blueprint, redirect, render_template, request, session, url_for

from kodi_np import config as _c

bp = Blueprint("auth", __name__)

_LOGIN_WINDOW_SECONDS = 15 * 60
_LOGIN_MAX_FAILURES = 5
_LOGIN_BLOCK_SECONDS = 60
_login_attempts = {}
_login_lock = threading.Lock()


def auth_enabled() -> bool:
    return bool(_c.BASIC_AUTH)


def _credentials() -> tuple[str, str]:
    if ":" not in _c.BASIC_AUTH:
        return _c.BASIC_AUTH, ""
    return tuple(_c.BASIC_AUTH.split(":", 1))  # type: ignore[return-value]


def is_authenticated() -> bool:
    return not auth_enabled() or bool(session.get("web_authenticated"))


def _client_ip() -> str:
    forwarded = (request.headers.get("X-Forwarded-For") or "").split(",")[0].strip()
    return forwarded or (request.remote_addr or "unknown")


def _login_allowed(ip: str) -> tuple[bool, int]:
    now = time.time()
    with _login_lock:
        entry = _login_attempts.get(ip)
        if not entry:
            return True, 0
        blocked_until = float(entry.get("blocked_until") or 0)
        if blocked_until > now:
            return False, int(blocked_until - now)
        started = float(entry.get("started") or now)
        if now - started > _LOGIN_WINDOW_SECONDS:
            _login_attempts.pop(ip, None)
        return True, 0


def _note_login_failure(ip: str) -> None:
    now = time.time()
    with _login_lock:
        entry = _login_attempts.get(ip) or {"fails": 0, "started": now, "blocked_until": 0}
        if now - float(entry.get("started") or now) > _LOGIN_WINDOW_SECONDS:
            entry = {"fails": 0, "started": now, "blocked_until": 0}
        entry["fails"] = int(entry.get("fails") or 0) + 1
        if entry["fails"] >= _LOGIN_MAX_FAILURES:
            entry["blocked_until"] = now + _LOGIN_BLOCK_SECONDS
            entry["fails"] = 0
            entry["started"] = now
        _login_attempts[ip] = entry


def _note_login_success(ip: str) -> None:
    with _login_lock:
        _login_attempts.pop(ip, None)


def safe_next_url(raw: str) -> str:
    """Clamp a ``next`` parameter to a same-origin relative path.

    ``//evil.example`` and ``/\\evil.example`` are protocol-relative and would
    send the browser off-site after a successful sign-in.
    """
    candidate = (raw or "").strip()
    if not candidate.startswith("/"):
        return "/"
    if candidate[:2] in ("//", "/\\"):
        return "/"
    return candidate


def _safe_compare(left: str, right: str) -> bool:
    left_b = (left or "").encode("utf-8")
    right_b = (right or "").encode("utf-8")
    if len(left_b) != len(right_b):
        hmac.compare_digest(left_b, left_b)
        return False
    return hmac.compare_digest(left_b, right_b)


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
    next_url = safe_next_url(request.args.get("next") or request.form.get("next") or "/")
    error = None
    ip = _client_ip()
    if request.method == "POST":
        allowed, retry_in = _login_allowed(ip)
        if not allowed:
            error = f"Too many sign-in attempts. Try again in {retry_in}s."
        else:
            username, password = _credentials()
            supplied_user = request.form.get("username", "")
            supplied_password = request.form.get("password", "")
            if _safe_compare(supplied_user, username) and _safe_compare(supplied_password, password):
                _note_login_success(ip)
                session["web_authenticated"] = True
                session.permanent = True
                return redirect(next_url)
            _note_login_failure(ip)
            error = "Those credentials were not accepted."
    return render_template("login.html", error=error, next=next_url)


@bp.route("/logout", methods=["POST"])
def logout():
    session.pop("web_authenticated", None)
    return redirect(url_for("auth.login"))

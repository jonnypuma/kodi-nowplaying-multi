"""404/500 handling for both HTML pages and JSON APIs (3.1.7)."""
from pathlib import Path

import pytest
from flask import Flask

TEMPLATES = Path(__file__).resolve().parents[1] / "kodi-np-multi" / "templates"


def test_unknown_api_path_returns_json_404(client):
    response = client.get("/api/definitely-not-a-route")
    assert response.status_code == 404
    assert response.mimetype == "application/json"
    payload = response.get_json()
    assert payload["success"] is False
    assert payload["status"] == 404


def test_unknown_page_returns_html_404(client):
    response = client.get("/definitely-not-a-page")
    assert response.status_code == 404
    assert response.mimetype == "text/html"
    body = response.get_data(as_text=True)
    assert "404" in body
    assert "Back to dashboard" in body


def test_json_accept_header_gets_json_even_off_api(client):
    response = client.get("/definitely-not-a-page", headers={"Accept": "application/json"})
    assert response.status_code == 404
    assert response.mimetype == "application/json"


def test_method_not_allowed_keeps_its_status(client):
    """The generic HTTPException handler must not flatten every error to 500."""
    response = client.get("/api/fanart")
    assert response.status_code == 405
    assert response.get_json()["status"] == 405


@pytest.fixture
def boom_app(app_module):
    """A throwaway app with raising routes.

    The real app is a singleton that has already served a request, so new
    routes cannot be attached to it. This exercises the handlers directly.
    """
    from kodi_np.errors import register_error_handlers

    app = Flask(__name__, template_folder=str(TEMPLATES))
    app.config["PROPAGATE_EXCEPTIONS"] = False

    @app.route("/api/boom")
    def api_boom():
        raise RuntimeError("kaboom")

    @app.route("/boom")
    def page_boom():
        raise RuntimeError("kaboom")

    register_error_handlers(app)
    return app


def test_unhandled_api_exception_returns_json_500(boom_app):
    with boom_app.test_client() as test_client:
        response = test_client.get("/api/boom")
    assert response.status_code == 500
    assert response.mimetype == "application/json"
    payload = response.get_json()
    assert payload["success"] is False
    assert payload["status"] == 500
    assert "kaboom" not in response.get_data(as_text=True)


def test_unhandled_page_exception_returns_html_500(boom_app):
    with boom_app.test_client() as test_client:
        response = test_client.get("/boom")
    assert response.status_code == 500
    assert response.mimetype == "text/html"
    assert "kaboom" not in response.get_data(as_text=True)

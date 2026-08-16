"""Login gate, logout, rate limiting, and API 401s (3.1.9)."""
import pytest


@pytest.fixture
def auth_on(app_module):
    """Enable BASIC_AUTH and reset the rate limiter for one test."""
    from kodi_np import auth as auth_mod

    app_module.BASIC_AUTH = "admin:s3cret"
    auth_mod._login_attempts.clear()
    try:
        yield auth_mod
    finally:
        app_module.BASIC_AUTH = ""
        auth_mod._login_attempts.clear()


def test_auth_disabled_by_default(client, app_module):
    assert app_module.BASIC_AUTH == ""
    assert client.get("/api/servers").status_code == 200


def test_login_page_redirects_when_auth_disabled(client):
    response = client.get("/login")
    assert response.status_code == 302


def test_page_request_redirects_to_login(client, auth_on):
    response = client.get("/overview")
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_api_request_returns_401_not_a_redirect(client, auth_on):
    response = client.get("/api/servers")
    assert response.status_code == 401


def test_health_endpoints_stay_open(client, auth_on):
    assert client.get("/health").status_code == 200


def test_successful_login_grants_access(client, auth_on):
    response = client.post("/login", data={"username": "admin", "password": "s3cret"})
    assert response.status_code == 302
    assert client.get("/api/servers").status_code == 200


def test_wrong_password_is_rejected(client, auth_on):
    response = client.post("/login", data={"username": "admin", "password": "wrong"})
    assert response.status_code == 200
    assert "not accepted" in response.get_data(as_text=True)
    assert client.get("/api/servers").status_code == 401


def test_logout_clears_the_session(client, auth_on):
    client.post("/login", data={"username": "admin", "password": "s3cret"})
    assert client.get("/api/servers").status_code == 200

    response = client.post("/logout")
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]
    assert client.get("/api/servers").status_code == 401


def test_repeated_failures_are_rate_limited(client, auth_on):
    for _ in range(auth_on._LOGIN_MAX_FAILURES):
        client.post("/login", data={"username": "admin", "password": "wrong"})

    blocked = client.post("/login", data={"username": "admin", "password": "s3cret"})
    body = blocked.get_data(as_text=True)
    assert "Too many sign-in attempts" in body
    # Correct credentials must not be honoured while blocked.
    assert client.get("/api/servers").status_code == 401


def test_login_does_not_redirect_off_site(client, auth_on):
    response = client.post(
        "/login?next=//evil.example",
        data={"username": "admin", "password": "s3cret"},
    )
    assert response.status_code == 302
    assert response.headers["Location"] == "/"


def test_login_preserves_a_relative_next(client, auth_on):
    response = client.post(
        "/login?next=/overview",
        data={"username": "admin", "password": "s3cret"},
    )
    assert response.headers["Location"] == "/overview"

def test_auth_disabled_by_default(client, app_module):
    app_module.BASIC_AUTH = ""
    response = client.get("/")
    assert response.status_code == 200


def test_optional_auth_login(client, app_module):
    app_module.BASIC_AUTH = "admin:secret"
    try:
        protected = client.get("/", follow_redirects=False)
        assert protected.status_code == 302
        assert "/login" in protected.headers["Location"]

        wrong = client.post("/login", data={"username": "admin", "password": "wrong"})
        assert wrong.status_code == 200
        assert b"not accepted" in wrong.data

        logged_in = client.post(
            "/login",
            data={"username": "admin", "password": "secret", "next": "/"},
            follow_redirects=False,
        )
        assert logged_in.status_code == 302
        assert client.get("/").status_code == 200
    finally:
        app_module.BASIC_AUTH = ""


def test_health_endpoints(client, app_module):
    app_module.BASIC_AUTH = ""
    assert client.get("/health/live").status_code == 200
    assert client.get("/health").get_json()["version"] == app_module.APP_VERSION
    assert client.get("/health/ready").status_code in (200, 503)

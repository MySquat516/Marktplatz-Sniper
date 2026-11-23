from tests.web.conftest import logged_in, post


def test_auth_disabled_without_password(make_app):
    assert make_app().test_client().get("/suchen").status_code == 200


def test_login_required_with_password(make_app):
    c = logged_in(make_app(password="geheim123"))
    resp = c.get("/suchen")
    assert resp.status_code == 302 and "/login" in resp.headers["Location"]
    page = post(c, "/login", username="admin", password="falsch").get_data(as_text=True)
    assert "Benutzer oder Passwort falsch" in page
    post(c, "/login", username="admin", password="geheim123")
    assert c.get("/suchen").status_code == 200
    post(c, "/logout")
    assert c.get("/suchen").status_code == 302


def test_login_lockout_after_five_failures(make_app):
    c = logged_in(make_app(password="geheim123"))
    for _ in range(5):
        post(c, "/login", username="admin", password="falsch")
    resp = c.post("/login", data={"csrf": "tok", "username": "admin", "password": "geheim123"})
    assert resp.status_code == 429


def test_healthz_without_login(make_app):
    assert make_app(password="geheim123").test_client().get("/healthz").status_code == 200


def test_session_secret_file_is_private(make_app, tmp_path):
    make_app(password="geheim123")
    secret = tmp_path / "session-secret"
    assert secret.exists() and oct(secret.stat().st_mode & 0o777) == "0o600"

from sniper.cli import create_runtime, ebay_credentials
from sniper.config import Settings
from sniper.db import set_setting


def settings(tmp_path, **env):
    return Settings.from_env({"DATA_DIR": str(tmp_path), **env})


def test_healthz(tmp_path):
    app, scheduler = create_runtime(settings(tmp_path))
    resp = app.test_client().get("/healthz")
    assert (resp.status_code, resp.get_data(as_text=True)) == (200, "ok")
    assert (tmp_path / "sniper.db").exists()


def test_ebay_credentials_prefer_environment(tmp_path):
    app, scheduler = create_runtime(settings(tmp_path))
    factory = scheduler.session_factory
    creds = ebay_credentials(settings(tmp_path), factory)
    assert creds() == ("", "")
    with factory() as s:
        set_setting(s, "ebay_client_id", "db-id")
        set_setting(s, "ebay_client_secret", "db-secret")
        s.commit()
    assert creds() == ("db-id", "db-secret")
    env = settings(tmp_path, EBAY_CLIENT_ID="env-id", EBAY_CLIENT_SECRET="env-secret")
    assert ebay_credentials(env, factory)() == ("env-id", "env-secret")

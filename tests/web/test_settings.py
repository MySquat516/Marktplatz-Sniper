from datetime import UTC, datetime

from sniper.db import get_setting
from sniper.engine import quota
from tests.web.conftest import logged_in, post


def test_settings_save_and_secret_not_rendered(client, session):
    post(client, "/einstellungen", ebay_client_id="my-id", ebay_client_secret="TOPSECRET")
    session.expire_all()
    assert get_setting(session, "ebay_client_id") == "my-id"
    assert get_setting(session, "ebay_client_secret") == "TOPSECRET"
    page = client.get("/einstellungen").get_data(as_text=True)
    assert "my-id" in page and "TOPSECRET" not in page


def test_empty_secret_keeps_stored_one(client, session):
    post(client, "/einstellungen", ebay_client_id="a", ebay_client_secret="s1")
    post(client, "/einstellungen", ebay_client_id="b", ebay_client_secret="")
    session.expire_all()
    assert (get_setting(session, "ebay_client_id"), get_setting(session, "ebay_client_secret")) == (
        "b",
        "s1",
    )


def test_quota_shown(client, session):
    now = datetime(2026, 11, 23, 7, 0, tzinfo=UTC)
    quota.record_call(session, now)
    quota.record_call(session, now)
    session.commit()
    assert "eBay-Abfragen heute: 2 von 5000" in client.get("/einstellungen").get_data(as_text=True)


def test_env_credentials_disable_fields(make_app):
    client = logged_in(make_app(env_ebay=True))
    page = client.get("/einstellungen").get_data(as_text=True)
    assert "per Umgebungsvariable gesetzt" in page

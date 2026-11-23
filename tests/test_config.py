from pathlib import Path

from sniper.config import Settings


def test_settings_defaults():
    s = Settings.from_env({})
    assert s.data_dir == Path("/data")
    assert s.port == 8095
    assert s.app_password == ""
    assert s.app_user == "admin"
    assert s.ebay_client_id == ""
    assert s.ebay_client_secret == ""


def test_settings_from_env():
    s = Settings.from_env(
        {
            "DATA_DIR": "/tmp/x",
            "PORT": "9000",
            "APP_PASSWORD": "geheim123",
            "APP_USER": "leon",
            "EBAY_CLIENT_ID": "id",
            "EBAY_CLIENT_SECRET": "sec",
        }
    )
    assert (s.data_dir, s.port, s.app_password, s.app_user) == (
        Path("/tmp/x"),
        9000,
        "geheim123",
        "leon",
    )
    assert (s.ebay_client_id, s.ebay_client_secret) == ("id", "sec")

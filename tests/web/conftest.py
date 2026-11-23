from datetime import UTC, datetime
from pathlib import Path

import pytest

from sniper.config import Settings
from sniper.db import make_session_factory
from sniper.models import Platform
from sniper.platforms.ebay import EbayAdapter
from sniper.platforms.http import HttpResponse
from sniper.platforms.kleinanzeigen import KleinanzeigenAdapter
from sniper.platforms.willhaben import WillhabenAdapter
from sniper.web import create_app

NOW = datetime(2026, 11, 23, 7, 0, tzinfo=UTC)
FIX = Path(__file__).parent.parent / "fixtures"
KA_URL = "https://www.kleinanzeigen.de/s-jacke/k0"
EBAY_URL = "https://www.ebay.de/sch/i.html?_nkw=carhartt"


class FakeHttp:
    def __init__(self, text=""):
        self.text = text

    def get(self, url, **kw):
        return HttpResponse(200, self.text, {})


class FakeScheduler:
    def __init__(self):
        self.checked = []

    def check_now(self, search_id):
        self.checked.append(search_id)


class Sent:
    def __init__(self, fail=False):
        self.fail = fail
        self.messages = []

    def __call__(self, url, message):
        from sniper.notify.sender import SendError

        if self.fail:
            raise SendError("Zustellung fehlgeschlagen")
        self.messages.append((url, message))


@pytest.fixture
def make_app(engine, tmp_path):
    def factory(password="", env_ebay=False, send=None):
        settings = Settings.from_env(
            {
                "DATA_DIR": str(tmp_path),
                "APP_PASSWORD": password,
                **({"EBAY_CLIENT_ID": "e", "EBAY_CLIENT_SECRET": "s"} if env_ebay else {}),
            }
        )
        http = FakeHttp((FIX / "kleinanzeigen" / "results.html").read_text(encoding="utf-8"))
        adapters = {
            Platform.KLEINANZEIGEN: KleinanzeigenAdapter(http, now=lambda: NOW),
            Platform.WILLHABEN: WillhabenAdapter(FakeHttp("<html></html>")),
            Platform.EBAY: EbayAdapter(FakeHttp(), lambda: ("", "")),
        }
        scheduler = FakeScheduler()
        app = create_app(
            settings,
            make_session_factory(engine),
            adapters,
            scheduler,
            send=send or Sent(),
            now=lambda: NOW,
        )
        app.config["TESTING"] = True
        app.scheduler = scheduler
        return app

    return factory


@pytest.fixture
def client(make_app):
    return logged_in(make_app())


def logged_in(app):
    c = app.test_client()
    with c.session_transaction() as s:
        s["csrf"] = "tok"
    return c


def post(client, path, **data):
    return client.post(path, data={"csrf": "tok", **data}, follow_redirects=True)

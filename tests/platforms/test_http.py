import pytest

from sniper.platforms.base import Blocked, NetworkError, RateLimited
from sniper.platforms.http import HttpClient, HttpResponse, check_blocked
from tests.fakes import FakeResponse, FakeSession


def resp(status=200, text="<html>ok</html>", headers=None):
    return HttpResponse(status=status, text=text, headers=headers or {})


@pytest.mark.parametrize("status", [403, 503])
def test_check_blocked_status(status):
    with pytest.raises(Blocked):
        check_blocked(resp(status))


def test_check_blocked_429_with_retry_after():
    with pytest.raises(RateLimited) as exc:
        check_blocked(resp(429, headers={"retry-after": "120"}))
    assert exc.value.retry_after == 120


def test_check_blocked_429_without_retry_after():
    with pytest.raises(RateLimited) as exc:
        check_blocked(resp(429))
    assert exc.value.retry_after is None


@pytest.mark.parametrize(
    "body",
    [
        "<title>Just a moment...</title>",
        '<script src="/cdn-cgi/challenge-platform/h/b/orchestrate"></script>',
        '<form id="challenge-form" action="/?__cf_chl_tk=abc">',
    ],
)
def test_check_blocked_cloudflare_challenge(body):
    with pytest.raises(Blocked):
        check_blocked(resp(200, text=body))


def test_check_blocked_normal_page_passes():
    check_blocked(resp(200, text="<html><body>Anzeigen</body></html>"))


class FakeClock:
    def __init__(self):
        self.now = 1000.0
        self.sleeps = []

    def clock(self):
        return self.now

    def sleep(self, s):
        self.sleeps.append(s)
        self.now += s


def test_spacing_per_host():
    c = FakeClock()
    http = HttpClient(min_spacing_s=10.0, clock=c.clock, sleep=c.sleep, session=FakeSession())
    http.get("https://www.kleinanzeigen.de/a")
    http.get("https://www.willhaben.at/b")
    assert c.sleeps == []
    http.get("https://www.kleinanzeigen.de/c")
    assert c.sleeps == [10.0]


def test_spacing_counts_elapsed_time():
    c = FakeClock()
    http = HttpClient(min_spacing_s=10.0, clock=c.clock, sleep=c.sleep, session=FakeSession())
    http.get("https://www.kleinanzeigen.de/a")
    c.now += 7
    http.get("https://www.kleinanzeigen.de/b")
    assert c.sleeps == [3.0]


def test_get_returns_response_and_lowercases_headers():
    session = FakeSession([FakeResponse(200, "hi", {"Retry-After": "5"})])
    http = HttpClient(session=session, sleep=lambda s: None)
    r = http.get("https://x.de/", params={"a": "1"}, headers={"H": "v"})
    assert (r.status, r.text, r.headers) == (200, "hi", {"retry-after": "5"})
    method, url, kwargs = session.calls[0]
    assert (method, url, kwargs["params"], kwargs["headers"]) == (
        "GET",
        "https://x.de/",
        {"a": "1"},
        {"H": "v"},
    )


def test_network_error_wrapped():
    http = HttpClient(session=FakeSession(error=OSError("connection reset")), sleep=lambda s: None)
    with pytest.raises(NetworkError, match="connection reset"):
        http.get("https://x.de/")

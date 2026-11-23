"""Kleine Test-Doubles, die in mehreren Testdateien gebraucht werden."""

from dataclasses import dataclass, field


@dataclass
class FakeResponse:
    status_code: int = 200
    text: str = ""
    headers: dict = field(default_factory=dict)


class FakeSession:
    """Steht für eine curl_cffi-Session; merkt sich Anfragen und liefert vorbereitete Antworten."""

    def __init__(self, responses=None, error=None):
        self.responses = list(responses or [])
        self.error = error
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        if self.error:
            raise self.error
        return self.responses.pop(0) if self.responses else FakeResponse()

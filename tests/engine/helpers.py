import json
from datetime import UTC, datetime

from sniper.db import Search, Target
from sniper.models import Listing, Platform, SearchSpec

NOW = datetime(2026, 11, 23, 7, 0, tzinfo=UTC)


def listing(i, platform=Platform.KLEINANZEIGEN, **kw):
    return Listing(
        platform=platform,
        external_id=str(i),
        title=kw.pop("title", f"Jacke {i}"),
        url=f"https://example/{i}",
        **kw,
    )


class FakeAdapter:
    """Liefert pro fetch-Aufruf das nächste vorbereitete Ergebnis (Liste oder Exception)."""

    def __init__(self, *results, platform=Platform.KLEINANZEIGEN):
        self.platform = platform
        self.results = list(results)
        self.calls = 0

    def fetch(self, spec):
        self.calls += 1
        result = self.results.pop(0) if self.results else []
        if isinstance(result, Exception):
            raise result
        return result


def make_search(session, name="Jacken", platform=Platform.KLEINANZEIGEN, targets=(), **kw):
    url = f"https://example/{name}"
    spec = SearchSpec(platform=platform, url=url)
    s = Search(
        name=name,
        platform=platform.value,
        url=url,
        spec_json=json.dumps(spec.to_dict()),
        created_at=kw.pop("created_at", NOW),
        **kw,
    )
    s.targets.extend(targets)
    session.add(s)
    session.flush()
    return s


def make_target(session, name="Handy", status_notices=False):
    t = Target(name=name, apprise_url=f"ntfy://{name}", status_notices=status_notices)
    session.add(t)
    session.flush()
    return t

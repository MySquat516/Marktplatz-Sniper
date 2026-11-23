import pytest

from sniper.db import make_engine, make_session_factory, migrate


@pytest.fixture
def engine(tmp_path):
    eng = make_engine(tmp_path)
    migrate(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def session(engine):
    factory = make_session_factory(engine)
    with factory() as s:
        yield s

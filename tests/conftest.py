import pytest

from topsongs import http, i18n


@pytest.fixture(autouse=True)
def german(monkeypatch):
    """Run every test in German, the language the assertions are written in.

    The env var covers the CLIs, which read TOPSONGS_LANGUAGE on start.
    """
    monkeypatch.setenv("TOPSONGS_LANGUAGE", "de")
    i18n.set_language("de")
    yield
    i18n.set_language("en")


@pytest.fixture
def sleeps(monkeypatch):
    """Record the waits of retries and throttling instead of sleeping."""
    calls: list[float] = []
    monkeypatch.setattr(http.time, "sleep", calls.append)
    return calls

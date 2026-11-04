import pytest


@pytest.fixture(autouse=True)
def local_mode(monkeypatch):
    """Tests describe local behaviour unless they opt into public mode themselves
    (the suite may run under /mount/src, which otherwise switches public mode on)."""
    monkeypatch.setenv("ROUTERESQ_PUBLIC", "0")

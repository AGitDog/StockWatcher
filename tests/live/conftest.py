"""Live tests talk to the real sources: switch off the network block of tests/conftest.py."""
import pytest


@pytest.fixture(autouse=True)
def _offline_insider_sources():
    """Overrides the fixture of the same name in tests/conftest.py: no network block here."""
    yield

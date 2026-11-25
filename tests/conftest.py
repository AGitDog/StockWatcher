"""Shared test setup: unit tests never reach the regulators' servers or live FX rates."""
import pytest

import insider_sources
import lot_filter


def pytest_addoption(parser):
    parser.addoption("--live", action="store_true", default=False,
                     help="also run tests/live: real calls to every data source (the Sunday check)")


def pytest_collection_modifyitems(config, items):
    if config.getoption("--live"):
        return
    skip = pytest.mark.skip(reason="live test: run with --live")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip)


def pytest_configure(config):
    config.addinivalue_line("markers", "live: real network calls, only with --live")


FAKE_USD_RATES = {"USD": 1.0, "EUR": 1.1, "GBP": 1.3, "CHF": 1.2, "CAD": 0.7}


@pytest.fixture(autouse=True)
def _offline_lot_filter(monkeypatch, tmp_path):
    """The list of too expensive Tokyo lots lives in a temporary file and is never rebuilt from Yahoo."""
    real_refresh = lot_filter.refresh_for_watchlist

    def no_refresh(symbols, today=None, path=None):
        return lot_filter.load_exclusions(path)

    no_refresh.real = real_refresh  # tests of the real function use this
    monkeypatch.setattr(lot_filter, "EXCLUSION_FILE", tmp_path / "zu_teure_pakete.json")
    monkeypatch.setattr(lot_filter, "refresh_for_watchlist", no_refresh)


@pytest.fixture(autouse=True)
def _offline_insider_sources(monkeypatch):
    def blocked(*args, **kwargs):
        raise ConnectionError("network access is blocked in unit tests")

    real_rate = insider_sources.usd_per_unit

    def fake_rate(currency):
        return FAKE_USD_RATES.get(str(currency or "USD").upper())

    fake_rate.real = real_rate  # tests of the real function use this
    monkeypatch.setattr(insider_sources, "_get", blocked)
    monkeypatch.setattr(insider_sources, "usd_per_unit", fake_rate)
    monkeypatch.setattr(insider_sources, "REQUEST_PAUSE_SECONDS", 0)
    insider_sources._six_purchases.cache_clear()
    insider_sources._tracefour_purchases.cache_clear()
    insider_sources._amf_notices.cache_clear()
    insider_sources.load_bafin_purchases.cache_clear()
    insider_sources._DISK_CACHES.clear()
    yield
    insider_sources._six_purchases.cache_clear()
    insider_sources._tracefour_purchases.cache_clear()
    insider_sources._amf_notices.cache_clear()
    insider_sources.load_bafin_purchases.cache_clear()
    insider_sources._DISK_CACHES.clear()

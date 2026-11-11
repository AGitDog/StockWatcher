"""Shared test setup: unit tests never reach the regulators' servers or live FX rates."""
import pytest

import insider_sources

FAKE_USD_RATES = {"USD": 1.0, "EUR": 1.1, "GBP": 1.3, "CHF": 1.2, "CAD": 0.7}


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
    insider_sources._amf_notices.cache_clear()
    insider_sources.load_bafin_purchases.cache_clear()
    insider_sources._DISK_CACHES.clear()
    yield
    insider_sources._six_purchases.cache_clear()
    insider_sources._amf_notices.cache_clear()
    insider_sources.load_bafin_purchases.cache_clear()
    insider_sources._DISK_CACHES.clear()

import pytest
import json
import time
from unittest.mock import patch, MagicMock

import finnhub_cache


@patch("finnhub_cache.get_secret")
def test_get_finnhub_key_env(mock_get_secret):
    """Test getting key via config_loader."""
    mock_get_secret.return_value = "TEST_KEY_ENV"
    assert finnhub_cache.get_finnhub_key() == "TEST_KEY_ENV"
    mock_get_secret.assert_called_once_with("finnhub", "api_key")


@patch("finnhub_cache.get_secret")
def test_get_finnhub_key_missing_returns_empty(mock_get_secret):
    """Missing optional key should return an empty string."""
    mock_get_secret.return_value = None
    assert finnhub_cache.get_finnhub_key() == ""


@patch("finnhub_cache.get_finnhub_key")
@patch("finnhub_cache._load_cache")
def test_recommendations_from_valid_cache(mock_load, mock_get_key):
    """A fresh cache entry is used without an API call."""
    mock_get_key.return_value = "KEY"
    mock_load.return_value = {"AAPL": {"timestamp": time.time(), "recommendation": [{"buy": 10}]}}
    with patch("finnhub_cache.requests.get") as mock_requests:
        assert finnhub_cache.get_recommendations("AAPL") == [{"buy": 10}]
        mock_requests.assert_not_called()


@patch("finnhub_cache.get_finnhub_key")
@patch("finnhub_cache._load_cache")
@patch("finnhub_cache._save_cache")
def test_recommendations_expired_cache_fetches_only_recommendations(mock_save, mock_load, mock_get_key):
    """An old entry triggers one call to the recommendation endpoint; price targets are not fetched (403 on the free plan)."""
    mock_get_key.return_value = "KEY"
    mock_load.return_value = {"AAPL": {"timestamp": time.time() - 30 * 60 * 60, "recommendation": []}}
    response = MagicMock(status_code=200)
    response.json.return_value = [{"buy": 20}]
    with patch("finnhub_cache.requests.get", return_value=response) as mock_requests:
        assert finnhub_cache.get_recommendations("AAPL") == [{"buy": 20}]
        assert mock_requests.call_count == 1
        assert "price-target" not in mock_requests.call_args.args[0]
        mock_save.assert_called_once()


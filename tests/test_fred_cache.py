import pytest
import time
from unittest.mock import patch, MagicMock

import fred_cache

@patch("fred_cache.get_secret")
def test_get_fred_key(mock_get_secret):
    """Test getting key via config_loader."""
    mock_get_secret.return_value = "TEST_FRED_ENV"
    assert fred_cache.get_fred_key() == "TEST_FRED_ENV"
    mock_get_secret.assert_called_once_with("fred", "api_key")


@patch("fred_cache.get_secret")
def test_get_fred_key_missing_returns_empty(mock_get_secret):
    """Missing optional key should return an empty string."""
    mock_get_secret.return_value = None
    assert fred_cache.get_fred_key() == ""

@patch("fred_cache.get_fred_key")
@patch("fred_cache._load_cache")
def test_get_yield_curve_spread_valid_cache(mock_load, mock_get_key):
    """Test that valid cache is used instead of making API calls."""
    mock_get_key.return_value = "KEY"
    mock_load.return_value = {
        "T10Y2Y": {
            "timestamp": time.time(), # Fresh
            "value": -0.5
        }
    }
    
    with patch("fred_cache.requests.get") as mock_requests:
        val = fred_cache.get_yield_curve_spread()
        mock_requests.assert_not_called()
        assert val == -0.5

@patch("fred_cache.get_fred_key")
@patch("fred_cache._load_cache")
@patch("fred_cache._save_cache")
def test_get_yield_curve_spread_expired_cache(mock_save, mock_load, mock_get_key):
    """Test that expired cache triggers API calls."""
    mock_get_key.return_value = "KEY"
    mock_load.return_value = {
        "T10Y2Y": {
            "timestamp": time.time() - (25 * 60 * 60), # 25 hours old
            "value": 0.0
        }
    }
    
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "observations": [{"value": "-0.1"}]
    }
    
    with patch("fred_cache.requests.get", return_value=mock_response) as mock_requests:
        val = fred_cache.get_yield_curve_spread()
        
        mock_requests.assert_called_once()
        assert val == -0.1
        mock_save.assert_called_once()

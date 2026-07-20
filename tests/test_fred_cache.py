import pytest
import os
import time
from unittest.mock import patch, MagicMock
from pathlib import Path

import fred_cache

@patch("fred_cache.os.environ.get")
def test_get_fred_key_env(mock_env_get):
    """Test getting key from environment variable."""
    mock_env_get.return_value = "TEST_FRED_ENV"
    assert fred_cache.get_fred_key() == "TEST_FRED_ENV"

@patch("fred_cache.os.environ.get")
@patch("fred_cache.Path.exists")
@patch("fred_cache.Path.read_text")
def test_get_fred_key_secrets(mock_read, mock_exists, mock_env_get):
    """Test getting key from secrets.toml."""
    mock_env_get.return_value = None
    mock_exists.return_value = True
    mock_read.return_value = '[fred]\napi_key = "TEST_FRED_SECRETS"\n'
    assert fred_cache.get_fred_key() == "TEST_FRED_SECRETS"

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

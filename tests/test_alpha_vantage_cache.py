import pytest
import os
import json
import time
from unittest.mock import patch, MagicMock
from pathlib import Path

import alpha_vantage_cache

@patch("alpha_vantage_cache.os.environ.get")
def test_get_av_key_env(mock_env_get):
    """Test getting key from environment variable."""
    mock_env_get.return_value = "TEST_AV_ENV"
    assert alpha_vantage_cache.get_av_key() == "TEST_AV_ENV"

@patch("alpha_vantage_cache.os.environ.get")
@patch("alpha_vantage_cache.Path.exists")
@patch("alpha_vantage_cache.Path.read_text")
def test_get_av_key_secrets(mock_read, mock_exists, mock_env_get):
    """Test getting key from secrets.toml."""
    mock_env_get.return_value = None
    mock_exists.return_value = True
    mock_read.return_value = '[alphavantage]\napi_key = "TEST_AV_SECRETS"\n'
    assert alpha_vantage_cache.get_av_key() == "TEST_AV_SECRETS"

@patch("alpha_vantage_cache.get_av_key")
@patch("alpha_vantage_cache._load_cache")
def test_get_fundamentals_valid_cache(mock_load, mock_get_key):
    """Test that valid cache is used instead of making API calls."""
    mock_get_key.return_value = "KEY"
    mock_load.return_value = {
        "AAPL": {
            "timestamp": time.time(), # Fresh
            "data": {"PERatio": "15"}
        }
    }
    
    with patch("alpha_vantage_cache.requests.get") as mock_requests:
        data = alpha_vantage_cache.get_fundamentals("AAPL")
        mock_requests.assert_not_called()
        assert data["PERatio"] == "15"

@patch("alpha_vantage_cache.get_av_key")
@patch("alpha_vantage_cache._load_cache")
@patch("alpha_vantage_cache._save_cache")
def test_get_fundamentals_expired_cache(mock_save, mock_load, mock_get_key):
    """Test that expired cache triggers API calls."""
    mock_get_key.return_value = "KEY"
    mock_load.return_value = {
        "AAPL": {
            "timestamp": time.time() - (31 * 24 * 60 * 60), # 31 days old (expired)
            "data": {"PERatio": "10"}
        }
    }
    
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"Symbol": "AAPL", "PERatio": "20"}
    
    with patch("alpha_vantage_cache.requests.get", return_value=mock_response) as mock_requests:
        data = alpha_vantage_cache.get_fundamentals("AAPL")
        
        mock_requests.assert_called_once()
        assert data["PERatio"] == "20"
        mock_save.assert_called_once()

@patch("alpha_vantage_cache.get_av_key")
@patch("alpha_vantage_cache._load_cache")
def test_get_fundamentals_rate_limit(mock_load, mock_get_key):
    """Test handling of Alpha Vantage rate limit."""
    mock_get_key.return_value = "KEY"
    mock_load.return_value = {}
    
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"Information": "Thank you for using Alpha Vantage! Our standard API call frequency is 5 calls per minute and 500 calls per day."}
    
    with patch("alpha_vantage_cache.requests.get", return_value=mock_response):
        data = alpha_vantage_cache.get_fundamentals("AAPL")
        assert data is None

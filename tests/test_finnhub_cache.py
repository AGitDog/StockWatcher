import pytest
import os
import json
import time
from unittest.mock import patch, MagicMock
from pathlib import Path

import finnhub_cache

@patch("finnhub_cache.os.environ.get")
def test_get_finnhub_key_env(mock_env_get):
    """Test getting key from environment variable."""
    mock_env_get.return_value = "TEST_KEY_ENV"
    assert finnhub_cache.get_finnhub_key() == "TEST_KEY_ENV"

@patch("finnhub_cache.os.environ.get")
@patch("finnhub_cache.Path.exists")
@patch("finnhub_cache.Path.read_text")
def test_get_finnhub_key_secrets(mock_read, mock_exists, mock_env_get):
    """Test getting key from secrets.toml."""
    mock_env_get.return_value = None
    mock_exists.return_value = True
    mock_read.return_value = '[finnhub]\napi_key = "TEST_KEY_SECRETS"\n'
    assert finnhub_cache.get_finnhub_key() == "TEST_KEY_SECRETS"

@patch("finnhub_cache.os.environ.get")
@patch("finnhub_cache.Path.exists")
@patch("finnhub_cache.Path.read_text")
def test_get_finnhub_key_secrets(mock_read, mock_exists, mock_env_get):
    """Test getting key from secrets.toml."""
    mock_env_get.return_value = None
    mock_exists.return_value = True
    mock_read.return_value = '[finnhub]\napi_key = "TEST_KEY_SECRETS"\n'
    assert finnhub_cache.get_finnhub_key() == "TEST_KEY_SECRETS"


@patch("finnhub_cache.os.environ.get")
@patch("finnhub_cache.Path.exists")
@patch("finnhub_cache.Path.read_text")
def test_get_finnhub_key_does_not_read_wrong_section(mock_read, mock_exists, mock_env_get):
    """Stellt sicher dass get_finnhub_key() nur den [finnhub]-Abschnitt liest."""
    mock_env_get.return_value = None
    mock_exists.return_value = True
    # secrets.toml has alphavantage key FIRST, then finnhub key
    mock_read.return_value = (
        '[alphavantage]\napi_key = "WRONG_AV_KEY"\n'
        '[finnhub]\napi_key = "CORRECT_FH_KEY"\n'
    )
    result = finnhub_cache.get_finnhub_key()
    assert result == "CORRECT_FH_KEY", f"Got wrong key: {result}"


@patch("finnhub_cache.os.environ.get")
@patch("finnhub_cache.Path.exists")
@patch("finnhub_cache.Path.read_text")
def test_get_finnhub_key_returns_empty_if_missing(mock_read, mock_exists, mock_env_get):
    """Fehlender Key soll leeren String zurückgeben, nicht crashen."""
    mock_env_get.return_value = None
    mock_exists.return_value = True
    mock_read.return_value = '[alphavantage]\napi_key = "SOME_KEY"\n'
    result = finnhub_cache.get_finnhub_key()
    assert result == ""


@patch("finnhub_cache.get_finnhub_key")
@patch("finnhub_cache._load_cache")
def test_get_analyst_data_valid_cache(mock_load, mock_get_key):
    """Test that valid cache is used instead of making API calls."""
    mock_get_key.return_value = "KEY"
    mock_load.return_value = {
        "AAPL": {
            "timestamp": time.time(), # Fresh
            "price_target": {"targetMean": 150},
            "recommendation": [{"buy": 10}]
        }
    }
    
    with patch("finnhub_cache.requests.get") as mock_requests:
        pt, rec = finnhub_cache.get_analyst_data("AAPL")
        
        # Requests should NOT be called
        mock_requests.assert_not_called()
        
        assert pt["targetMean"] == 150
        assert rec[0]["buy"] == 10

@patch("finnhub_cache.get_finnhub_key")
@patch("finnhub_cache._load_cache")
@patch("finnhub_cache._save_cache")
def test_get_analyst_data_expired_cache(mock_save, mock_load, mock_get_key):
    """Test that expired cache triggers API calls."""
    mock_get_key.return_value = "KEY"
    mock_load.return_value = {
        "AAPL": {
            "timestamp": time.time() - (30 * 60 * 60), # 30 hours old (expired)
            "price_target": {"targetMean": 100},
            "recommendation": []
        }
    }
    
    mock_pt_response = MagicMock()
    mock_pt_response.status_code = 200
    mock_pt_response.json.return_value = {"targetMean": 200}
    
    mock_rec_response = MagicMock()
    mock_rec_response.status_code = 200
    mock_rec_response.json.return_value = [{"buy": 20}]
    
    with patch("finnhub_cache.requests.get", side_effect=[mock_pt_response, mock_rec_response]) as mock_requests:
        pt, rec = finnhub_cache.get_analyst_data("AAPL")
        
        assert mock_requests.call_count == 2
        assert pt["targetMean"] == 200
        assert rec[0]["buy"] == 20
        mock_save.assert_called_once()


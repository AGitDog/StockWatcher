import pytest
import os
import json
import pandas as pd
from pathlib import Path
from datetime import datetime
from unittest.mock import patch, MagicMock

import backtest

@pytest.fixture
def mock_history_dir(tmp_path):
    d = tmp_path / "signal_history"
    d.mkdir()
    return d

def test_load_snapshots_empty(mock_history_dir):
    with patch("backtest.HISTORY_DIR", mock_history_dir):
        snapshots = backtest.load_snapshots()
        assert len(snapshots) == 0

def test_load_snapshots_with_data(mock_history_dir):
    file1 = mock_history_dir / "snapshot1.json"
    file1.write_text(json.dumps([{"symbol": "AAPL", "brodel_score": 50}]), encoding="utf-8")
    
    with patch("backtest.HISTORY_DIR", mock_history_dir):
        snapshots = backtest.load_snapshots()
        assert len(snapshots) == 1
        assert snapshots[0][1][0]["symbol"] == "AAPL"

@patch("backtest.yf")
def test_fetch_forward_return_success(mock_yf):
    mock_ticker = MagicMock()
    dates = pd.date_range("2024-01-01", periods=40)
    
    # Simulate price going from 100 to 110 (+10%)
    close_vals = [100.0] * 30 + [110.0] * 10
    mock_df = pd.DataFrame({"Close": close_vals}, index=dates)
    mock_ticker.history.return_value = mock_df
    mock_yf.Ticker.return_value = mock_ticker
    
    ret = backtest.fetch_forward_return("AAPL", datetime(2024, 1, 1), days=30)
    assert ret is not None
    assert abs(ret - 10.0) < 1e-5

@patch("backtest.yf")
def test_fetch_forward_return_empty(mock_yf):
    mock_ticker = MagicMock()
    mock_ticker.history.return_value = pd.DataFrame()
    mock_yf.Ticker.return_value = mock_ticker
    
    ret = backtest.fetch_forward_return("AAPL", datetime(2024, 1, 1), days=30)
    assert ret is None

@patch("backtest.load_snapshots")
@patch("backtest.fetch_forward_return")
def test_run_backtest_with_data(mock_fetch, mock_load, caplog):
    # Snapshot exactly 40 days ago
    past_date = datetime.now() - pd.Timedelta(days=40)
    
    mock_load.return_value = [
        (past_date, [{"symbol": "AAPL", "brodel_score": 80}])
    ]
    
    mock_fetch.return_value = 15.0 # +15%
    
    backtest.run_backtest(days=30)
    
    mock_fetch.assert_called_once()

@patch("backtest.load_snapshots")
def test_run_backtest_too_new(mock_load):
    # Snapshot from today (too new for 30 day backtest)
    mock_load.return_value = [
        (datetime.now(), [{"symbol": "AAPL", "brodel_score": 80}])
    ]
    
    with patch("backtest.fetch_forward_return") as mock_fetch:
        backtest.run_backtest(days=30)
        mock_fetch.assert_not_called()

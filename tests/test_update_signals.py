import os
import sys
import pytest
from unittest.mock import patch, mock_open, MagicMock
from pathlib import Path
from update_signals import run_update

@patch("update_signals.os.path.exists")
@patch("update_signals.sys.exit")
def test_run_update_watchlist_not_found(mock_exit, mock_exists):
    """Test that the script exits cleanly if the watchlist file does not exist."""
    mock_exists.return_value = False
    mock_exit.side_effect = SystemExit
    
    with pytest.raises(SystemExit):
        run_update()
    
    mock_exit.assert_called_once_with(1)

@patch("update_signals.os.path.exists")
@patch("update_signals.sys.exit")
@patch("builtins.open", new_callable=mock_open, read_data="")
def test_run_update_empty_watchlist(mock_file, mock_exit, mock_exists):
    """Test that the script exits cleanly if the watchlist is empty."""
    mock_exists.return_value = True
    mock_exit.side_effect = SystemExit
    
    with pytest.raises(SystemExit):
        run_update()
    
    mock_exit.assert_called_once_with(0)

@patch("update_signals.os.path.exists")
@patch("builtins.open", new_callable=mock_open, read_data="AAPL\nMSFT")
@patch("update_signals.build_symbol_signal_monitor")
@patch("update_signals.save_signal_snapshot")
@patch("update_signals.add_watchlist_peer_context")
def test_run_update_success(mock_peer_context, mock_save, mock_build, mock_file, mock_exists):
    """Test a successful run with valid entries."""
    mock_exists.return_value = True
    
    mock_build.side_effect = [
        {"symbol": "AAPL", "brodel_score": 80},
        {"symbol": "MSFT", "brodel_score": 90}
    ]
    
    mock_peer_context.side_effect = lambda x: x
    mock_save.return_value = Path("dummy/path.json")
    
    run_update()
    
    assert mock_build.call_count == 2
    mock_build.assert_any_call("AAPL", {})
    mock_build.assert_any_call("MSFT", {})
    
    mock_peer_context.assert_called_once()
    mock_save.assert_called_once()
    
    saved_watchlist_name = mock_save.call_args[0][0]
    saved_data = mock_save.call_args[0][1]
    
    assert saved_watchlist_name == "meine_watchlist.txt"
    assert len(saved_data) == 2
    assert saved_data[0]["symbol"] == "MSFT"
    assert saved_data[1]["symbol"] == "AAPL"

@patch("update_signals.os.path.exists")
@patch("builtins.open", new_callable=mock_open, read_data="AAPL\nINVALID")
@patch("update_signals.build_symbol_signal_monitor")
@patch("update_signals.save_signal_snapshot")
@patch("update_signals.add_watchlist_peer_context")
def test_run_update_with_exception(mock_peer_context, mock_save, mock_build, mock_file, mock_exists):
    """Test that an exception in one symbol doesn't stop the whole process."""
    mock_exists.return_value = True
    
    def build_side_effect(symbol, mappings):
        if symbol == "INVALID":
            raise ValueError("Test Error")
        return {"symbol": symbol, "brodel_score": 50}
        
    mock_build.side_effect = build_side_effect
    mock_peer_context.side_effect = lambda x: x
    mock_save.return_value = Path("dummy/path.json")
    
    run_update()
    
    assert mock_build.call_count == 2
    mock_save.assert_called_once()
    saved_data = mock_save.call_args[0][1]
    assert len(saved_data) == 1
    assert saved_data[0]["symbol"] == "AAPL"

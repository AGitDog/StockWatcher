import importlib
import pytest
from unittest.mock import patch


def test_app_module_imports_without_errors():
    """Verify that app.py and all its top-level imports load cleanly."""
    try:
        app = importlib.import_module("app")
    except Exception as e:
        pytest.fail(f"app.py failed to import with {type(e).__name__}: {e}")

    assert hasattr(app, "main"), "app.py must have a main entrypoint"
    assert hasattr(app, "render_stock_agent"), "app.py must define render_stock_agent"
    assert hasattr(app, "get_extended_fundamentals"), "app.py must define get_extended_fundamentals"


def test_all_stock_agent_imports_exist_and_are_callable():
    """Verify every symbol imported from stock_agent in app.py actually exists and is callable."""
    import stock_agent

    expected_symbols = [
        "build_watchlist_alerts",
        "build_signal_delta_report",
        "build_symbol_signal_monitor",
        "build_symbol_summary",
        "fetch_company_extended_fundamentals",
        "parse_watchlist_text",
        "parse_symbol_mappings",
        "add_watchlist_peer_context",
        "summarize_index_entries",
        "get_supported_indices",
        "list_watchlist_files",
        "load_signal_snapshot_history",
        "load_watchlist_file",
        "save_signal_snapshot",
        "save_watchlist_file",
    ]

    for symbol_name in expected_symbols:
        assert hasattr(stock_agent, symbol_name), (
            f"stock_agent is missing '{symbol_name}' which is imported by app.py"
        )
        assert callable(getattr(stock_agent, symbol_name)), (
            f"stock_agent.{symbol_name} must be callable"
        )


def test_all_strategy_and_engine_imports_exist():
    """Verify strategy and backtest engine imports used in app.py exist."""
    import strategies
    import backtest_engine
    import ml_weights
    from backtest_engine import engine

    assert hasattr(strategies, "build_strategy_signals"), "strategies must define build_strategy_signals"
    assert hasattr(backtest_engine, "BacktestEngine"), "backtest_engine must define BacktestEngine"
    assert hasattr(backtest_engine, "run_backtest_on_snapshots"), "backtest_engine must define run_backtest_on_snapshots"
    assert hasattr(ml_weights, "load_trained_weights"), "ml_weights must define load_trained_weights"
    assert hasattr(ml_weights, "train_on_snapshots"), "ml_weights must define train_on_snapshots"
    assert hasattr(engine, "load_snapshots"), "backtest_engine.engine must define load_snapshots"


def test_stock_agent_resilient_to_missing_genai():
    """Verify stock_agent imports cleanly even if google.genai raises an error or is missing."""
    with patch.dict("sys.modules", {"google.genai": None}):
        import stock_agent
        assert hasattr(stock_agent, "build_symbol_signal_monitor")
        assert hasattr(stock_agent, "fetch_company_extended_fundamentals")

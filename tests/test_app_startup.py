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
    assert hasattr(backtest_engine, "run_score_range_backtest"), "backtest_engine must define run_score_range_backtest"
    assert hasattr(backtest_engine, "ScoreRangeBacktestResult"), "backtest_engine must define ScoreRangeBacktestResult"
    assert hasattr(ml_weights, "load_trained_weights"), "ml_weights must define load_trained_weights"
    assert hasattr(ml_weights, "train_on_snapshots"), "ml_weights must define train_on_snapshots"
    assert hasattr(engine, "load_snapshots"), "backtest_engine.engine must define load_snapshots"


def test_stock_agent_resilient_to_missing_genai():
    """Verify stock_agent imports cleanly even if google.genai raises an error or is missing."""
    with patch.dict("sys.modules", {"google.genai": None}):
        import stock_agent
        assert hasattr(stock_agent, "build_symbol_signal_monitor")
        assert hasattr(stock_agent, "fetch_company_extended_fundamentals")


def test_render_stock_agent_layout():
    """Verify render_stock_agent creates exactly 3 tabs (Signal Monitor V2, Backtest & ML, Hilfe & Methodik)."""
    from unittest.mock import MagicMock
    import app

    tab_mock_1 = MagicMock()
    tab_mock_2 = MagicMock()
    tab_mock_3 = MagicMock()

    with patch("streamlit.tabs", return_value=[tab_mock_1, tab_mock_2, tab_mock_3]) as mock_tabs, \
         patch("streamlit.title"), \
         patch("streamlit.caption"), \
         patch("app.render_watchlist_signal_monitor"), \
         patch("app.render_backtest_tab"), \
         patch("app.render_help_tab"):
        app.render_stock_agent()
        mock_tabs.assert_called_once_with(["Signal Monitor V2", "Backtest & ML", "Hilfe & Methodik"])


def test_default_watchlist_contains_new_indices():
    """Verify that meine_watchlist.txt contains SOX, NBI, and Nikkei 225."""
    import app
    name, text = app.load_default_watchlist_text()
    assert name == "meine_watchlist.txt"
    assert "SOX" in text
    assert "NBI" in text
    assert "Nikkei 225" in text


def test_detail_fundamentals_rendering_with_opex():
    """Verify that detail fundamentals view handles opex metrics and charts cleanly."""
    from unittest.mock import MagicMock
    import app

    mock_fundamentals = {
        "symbol": "SAP.DE",
        "name": "SAP SE",
        "summary_de": "SAP ist ein Softwarehersteller.",
        "sector_de": "Technologie",
        "industry_de": "Software",
        "city": "Walldorf",
        "country": "Deutschland",
        "employees": 105000,
        "currency": "EUR",
        "current_price": 180.0,
        "target_mean_price": 210.0,
        "target_median_price": 205.0,
        "upside_pct": 16.7,
        "implied_market_cap": 250_000_000_000,
        "gross_margin_ttm": 72.0,
        "gross_margin_history": [
            {"Jahr": 2023, "Umsatz": 31_000_000_000, "Bruttogewinn": 22_000_000_000, "Bruttomarge": 71.0},
            {"Jahr": 2024, "Umsatz": 33_000_000_000, "Bruttogewinn": 24_000_000_000, "Bruttomarge": 72.7},
        ],
        "operating_margin_ttm": 24.5,
        "operating_cost_history": [
            {
                "Jahr": 2023,
                "Umsatz": 31_000_000_000,
                "OpEx": 15_000_000_000,
                "FE": 6_000_000_000,
                "SGA": 9_000_000_000,
                "Operativer_Gewinn": 7_000_000_000,
                "Operative_Marge": 22.6,
                "OpEx_Quote": 48.4,
                "FE_Quote": 19.4,
                "SGA_Quote": 29.0,
            },
            {
                "Jahr": 2024,
                "Umsatz": 33_000_000_000,
                "OpEx": 16_000_000_000,
                "FE": 6_500_000_000,
                "SGA": 9_500_000_000,
                "Operativer_Gewinn": 8_000_000_000,
                "Operative_Marge": 24.2,
                "OpEx_Quote": 48.5,
                "FE_Quote": 19.7,
                "SGA_Quote": 28.8,
            },
        ],
        "trailing_pe": 32.0,
        "forward_pe": 26.0,
        "peg_ratio": 1.9,
    }

    assert mock_fundamentals["operating_margin_ttm"] == 24.5
    assert len(mock_fundamentals["operating_cost_history"]) == 2
    assert mock_fundamentals["operating_cost_history"][1]["OpEx"] == 16_000_000_000


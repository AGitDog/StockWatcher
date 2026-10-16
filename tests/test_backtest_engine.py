"""Tests for backtest engine."""

import json
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock

import pandas as pd
import pytest

from backtest_engine import (
    BacktestEngine,
    Portfolio,
    ScoreRangeBacktestResult,
    ScoreRangePosition,
    Trade,
    run_score_range_backtest,
)
from backtest_engine.engine import (
    _calculate_metrics,
    _price_on_or_after,
    _price_on_or_before,
    load_snapshots,
)


@pytest.fixture
def mock_history_dir(tmp_path):
    d = tmp_path / "signal_history"
    d.mkdir()
    return d


def test_portfolio_opens_and_closes_trade():
    portfolio = Portfolio(initial_cash=100_000, transaction_cost_pct=0.0)
    trade = portfolio.open_trade(
        symbol="AAPL",
        direction="long",
        entry_date=datetime(2024, 1, 1),
        entry_price=100.0,
        position_size_pct=0.1,
        stop_loss=90.0,
        take_profit=120.0,
        strategy="momentum",
    )
    assert trade is not None
    assert len(portfolio.open_trades()) == 1

    portfolio.close_trade("AAPL", datetime(2024, 2, 1), 110.0)
    assert len(portfolio.open_trades()) == 0
    assert trade.pnl_pct == pytest.approx(10.0)


def test_portfolio_respects_max_positions():
    portfolio = Portfolio(initial_cash=100_000, max_positions=2)
    for symbol in ["A", "B", "C"]:
        portfolio.open_trade(
            symbol=symbol,
            direction="long",
            entry_date=datetime(2024, 1, 1),
            entry_price=100.0,
            position_size_pct=0.1,
        )
    assert len(portfolio.open_trades()) == 2


def test_portfolio_stop_loss():
    portfolio = Portfolio(initial_cash=100_000, transaction_cost_pct=0.0)
    portfolio.open_trade(
        symbol="AAPL",
        direction="long",
        entry_date=datetime(2024, 1, 1),
        entry_price=100.0,
        position_size_pct=0.1,
        stop_loss=95.0,
    )
    portfolio.apply_stop_take({"AAPL": 94.0}, datetime(2024, 1, 2))
    assert len(portfolio.open_trades()) == 0


def test_portfolio_sizes_trade_from_stop_risk():
    portfolio = Portfolio(initial_cash=100_000, transaction_cost_pct=0.0)
    trade = portfolio.open_trade(
        symbol="AAPL",
        direction="long",
        entry_date=datetime(2024, 1, 1),
        entry_price=100.0,
        position_size_pct=0.5,
        stop_loss=90.0,
        risk_per_trade_pct=0.01,
    )

    assert trade is not None
    assert trade.shares == pytest.approx(100.0)


def test_short_trade_books_profit_correctly():
    portfolio = Portfolio(initial_cash=100_000, transaction_cost_pct=0.0)
    trade = portfolio.open_trade(
        symbol="AAPL",
        direction="short",
        entry_date=datetime(2024, 1, 1),
        entry_price=100.0,
        position_size_pct=0.1,
    )

    assert trade is not None
    portfolio.close_trade("AAPL", datetime(2024, 1, 2), 90.0)

    assert trade.pnl_pct == pytest.approx(11.111111, rel=1e-5)
    assert portfolio.total_value({}) == pytest.approx(101_000.0)


def test_price_on_or_after():
    dates = pd.date_range("2024-01-01", periods=5)
    hist = pd.DataFrame({"Close": [100, 101, 102, 103, 104]}, index=dates)
    assert _price_on_or_after(hist, datetime(2024, 1, 3)) == 102.0
    assert _price_on_or_after(hist, datetime(2024, 1, 10)) is None


def test_price_on_or_before():
    dates = pd.date_range("2024-01-01", periods=5)
    hist = pd.DataFrame({"Close": [100, 101, 102, 103, 104]}, index=dates)
    assert _price_on_or_before(hist, datetime(2024, 1, 3)) == 102.0
    assert _price_on_or_before(hist, datetime(2023, 12, 31)) is None


def test_calculate_metrics():
    curve = pd.DataFrame({
        "total_value": [100_000, 105_000, 103_000, 110_000],
    })
    metrics = _calculate_metrics(curve)
    assert metrics["total_return_pct"] == pytest.approx(10.0)
    assert metrics["max_drawdown_pct"] <= 0


def test_load_snapshots(mock_history_dir):
    snapshot = {"timestamp": "2024-01-01T00:00:00Z", "items": [{"symbol": "AAPL", "brodel_score": 50}]}
    second_snapshot = {"timestamp": "2024-02-01T00:00:00Z", "items": [{"symbol": "MSFT", "brodel_score": 60}]}
    file_path = mock_history_dir / "test.json"
    file_path.write_text(json.dumps([snapshot, second_snapshot]), encoding="utf-8")

    snapshots = load_snapshots(mock_history_dir)
    assert len(snapshots) == 2
    assert snapshots[0][1][0]["symbol"] == "AAPL"
    assert snapshots[1][0] > snapshots[0][0]


@patch("backtest_engine.engine.fetch_prices")
@patch("backtest_engine.engine.fetch_benchmark_return")
def test_backtest_engine_runs(mock_benchmark, mock_fetch_prices, mock_history_dir):
    snapshot = {
        "timestamp": "2024-01-01T00:00:00Z",
        "items": [
            {"symbol": "AAPL", "brodel_score": 80},
            {"symbol": "MSFT", "brodel_score": 60},
        ],
    }
    file_path = mock_history_dir / "test.json"
    file_path.write_text(json.dumps([snapshot]), encoding="utf-8")

    dates = pd.date_range("2024-01-01", periods=40)
    mock_fetch_prices.return_value = {
        "AAPL": pd.DataFrame({"Close": [100.0] * 40}, index=dates),
        "MSFT": pd.DataFrame({"Close": [100.0] * 40}, index=dates),
    }
    mock_benchmark.return_value = 0.0

    engine = BacktestEngine(
        initial_cash=100_000,
        max_positions=2,
        rebalance_days=30,
    )
    snapshots = load_snapshots(mock_history_dir)
    result = engine.run(snapshots, strategy_name="test")

    assert result is not None
    assert result.num_trades >= 0
    assert result.initial_cash == 100_000


def test_score_range_backtest_entry_and_equal_allocation():
    """Verify that stocks entering the score range are bought on the entry date with equal capital."""
    dt1 = datetime(2024, 1, 10)
    dt2 = datetime(2024, 1, 15)

    snapshots = [
        (
            dt1,
            [
                {"symbol": "AAPL", "name": "Apple Inc.", "brodel_score": 65},
                {"symbol": "MSFT", "name": "Microsoft Corp.", "brodel_score": 75},  # Enters Day 1
            ],
        ),
        (
            dt2,
            [
                {"symbol": "AAPL", "name": "Apple Inc.", "brodel_score": 72},  # Climbs into range on Day 2
                {"symbol": "MSFT", "name": "Microsoft Corp.", "brodel_score": 78},  # Already in range, not rebought
                {"symbol": "NVDA", "name": "Nvidia Corp.", "brodel_score": 88},  # Above range
            ],
        ),
    ]

    dates = pd.date_range("2024-01-08", "2024-02-01", freq="D")
    price_data = {
        "MSFT": pd.DataFrame({"Close": [200.0] * 10 + [220.0] * 15}, index=dates),  # Bought at 200, now 220 (+10%)
        "AAPL": pd.DataFrame({"Close": [100.0] * 15 + [120.0] * 10}, index=dates),  # Bought at 100, now 120 (+20%)
    }

    result = run_score_range_backtest(
        snapshots=snapshots,
        min_score=70,
        max_score=80,
        lookback_days=100,
        initial_capital=10_000.0,
        entry_mode="fresh_entry",
        price_data=price_data,
        current_date=datetime(2024, 2, 1),
    )

    assert result.num_positions == 2
    assert result.initial_capital == 10_000.0

    # Capital is split equally: 5,000 each
    msft_pos = next(p for p in result.positions if p.symbol == "MSFT")
    aapl_pos = next(p for p in result.positions if p.symbol == "AAPL")

    assert msft_pos.allocated_capital == 5_000.0
    assert msft_pos.buy_score == 75
    assert msft_pos.buy_date == dt1
    assert msft_pos.buy_price == 200.0
    assert msft_pos.current_price == 220.0
    assert msft_pos.current_value == pytest.approx(5_500.0)
    assert msft_pos.return_pct == pytest.approx(10.0)

    assert aapl_pos.allocated_capital == 5_000.0
    assert aapl_pos.buy_score == 72
    assert aapl_pos.prev_score == 65
    assert aapl_pos.buy_date == dt2
    assert aapl_pos.buy_price == 100.0
    assert aapl_pos.current_price == 120.0
    assert aapl_pos.current_value == pytest.approx(6_000.0)
    assert aapl_pos.return_pct == pytest.approx(20.0)

    assert result.total_current_value == pytest.approx(11_500.0)
    assert result.total_profit_loss == pytest.approx(1_500.0)
    assert result.total_return_pct == pytest.approx(15.0)
    assert result.win_rate == pytest.approx(100.0)

    df = result.to_dataframe()
    assert len(df) == 2
    assert "Symbol" in df.columns
    assert "Kaufdatum" in df.columns
    assert "Kauf-Score" in df.columns
    assert "Kaufkurs (€/$)" in df.columns
    assert "Aktueller Wert (€)" in df.columns


def test_score_range_backtest_climbed_from_below_mode():
    """Verify climbed_from_below strictly requires prev_score < min_score."""
    dt1 = datetime(2024, 1, 1)
    dt2 = datetime(2024, 1, 5)

    snapshots = [
        (
            dt1,
            [
                {"symbol": "A", "brodel_score": 75},  # In range on Day 1 (no prev)
                {"symbol": "B", "brodel_score": 60},  # Below range
            ],
        ),
        (
            dt2,
            [
                {"symbol": "A", "brodel_score": 75},  # Still in range
                {"symbol": "B", "brodel_score": 72},  # Climbed from 60 to 72
            ],
        ),
    ]

    dates = pd.date_range("2024-01-01", "2024-01-10")
    price_data = {
        "A": pd.DataFrame({"Close": [10.0] * 10}, index=dates),
        "B": pd.DataFrame({"Close": [20.0] * 10}, index=dates),
    }

    result = run_score_range_backtest(
        snapshots=snapshots,
        min_score=70,
        max_score=80,
        entry_mode="climbed_from_below",
        price_data=price_data,
        current_date=datetime(2024, 1, 10),
    )

    # Only B climbed from below 70!
    assert result.num_positions == 1
    assert result.positions[0].symbol == "B"
    assert result.positions[0].prev_score == 60


def test_score_range_backtest_no_qualifying_returns_clean_result():
    """Verify that if no stocks meet criteria, 0 positions and cash intact are returned."""
    snapshots = [
        (
            datetime(2024, 1, 1),
            [{"symbol": "LOW", "brodel_score": 30}],
        )
    ]
    result = run_score_range_backtest(
        snapshots=snapshots,
        min_score=70,
        max_score=80,
        initial_capital=5_000.0,
    )
    assert result.num_positions == 0
    assert result.total_current_value == 5_000.0
    assert result.total_return_pct == 0.0
    assert result.to_dataframe().empty


def test_score_range_backtest_signal_items_price_fallback():
    """Verify fallback to signal_items Kurs text if market history is not in price_data."""
    snapshots = [
        (
            datetime(2024, 1, 1),
            [
                {
                    "symbol": "FALLBACK",
                    "brodel_score": 75,
                    "signal_items": ["Kurs 50.00, 5T 2.6%, Volumen 0.8x"],
                }
            ],
        )
    ]
    result = run_score_range_backtest(
        snapshots=snapshots,
        min_score=70,
        max_score=80,
        initial_capital=1_000.0,
        price_data={},  # Empty price data
        current_date=datetime(2024, 1, 5),
    )
    assert result.num_positions == 1
    pos = result.positions[0]
    assert pos.buy_price == 50.0
    assert pos.shares == pytest.approx(20.0)


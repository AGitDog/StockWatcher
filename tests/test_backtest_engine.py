"""Tests for backtest engine."""

import json
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock

import pandas as pd
import pytest

from backtest_engine import BacktestEngine, Portfolio, Trade
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

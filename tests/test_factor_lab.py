"""Tests for the factor_lab truth machine."""

from __future__ import annotations

import math
from datetime import datetime
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from factor_lab.backtest import (
    ETF_TEILFREISTELLUNG,
    TAX_RATE_DE,
    BacktestConfig,
    GermanTaxAccount,
    _cap_sector_weights,
    run_factor_backtest,
)
from factor_lab.data import _extract_close, download_close_prices, filter_single_currency, is_us_listing, to_yahoo_symbol
from factor_lab.evaluation import (
    deflated_sharpe_ratio,
    forward_returns,
    ic_summary,
    probabilistic_sharpe_ratio,
    quantile_returns,
    rank_ic_series,
    snapshot_score_ic,
    walk_forward_weights,
)
from factor_lab.factors import composite_score, compute_factor_panel, cross_sectional_rank, month_end_dates
from factor_lab.report import build_truth_report, build_verdict, report_to_jsonable


def _random_prices(n_symbols: int = 40, start: str = "2012-01-02", end: str = "2019-12-31", seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    index = pd.bdate_range(start, end)
    drift = rng.normal(0.0003, 0.0003, n_symbols)
    vol = rng.uniform(0.008, 0.025, n_symbols)
    returns = rng.normal(drift, vol, (len(index), n_symbols))
    return pd.DataFrame(100 * np.exp(np.cumsum(returns, axis=0)), index=index, columns=[f"S{i}" for i in range(n_symbols)])


def _benchmark(index: pd.DatetimeIndex, daily: float = 0.0003) -> pd.Series:
    return pd.Series(100 * np.exp(np.arange(len(index)) * daily), index=index)


# --- factors ---

def test_month_end_dates_picks_last_trading_day():
    index = pd.bdate_range("2024-01-01", "2024-03-31")
    ends = month_end_dates(index)
    assert list(ends.strftime("%Y-%m-%d")) == ["2024-01-31", "2024-02-29", "2024-03-29"]


def test_factors_do_not_use_future_prices():
    close = _random_prices(10)
    dates = month_end_dates(close.index)
    signal_date = dates[30]
    before = compute_factor_panel(close, dates, ["momentum_12_1", "low_volatility", "reversal_1m", "trend_200d"])
    changed = close.copy()
    changed.loc[changed.index > signal_date] *= 3.0
    after = compute_factor_panel(changed, dates, ["momentum_12_1", "low_volatility", "reversal_1m", "trend_200d"])
    for name in before:
        pd.testing.assert_series_equal(before[name].loc[signal_date], after[name].loc[signal_date])


def test_momentum_skips_most_recent_month():
    index = pd.bdate_range("2020-01-01", periods=300)
    prices = pd.Series(100.0, index=index)
    prices.iloc[-21:] = 200.0  # jump only inside the skipped last month
    close = pd.DataFrame({"A": prices})
    factor = compute_factor_panel(close, pd.DatetimeIndex([index[-1]]), ["momentum_12_1"])["momentum_12_1"]
    assert factor.iloc[0, 0] == pytest.approx(0.0)


def test_low_volatility_ranks_calm_stock_higher():
    rng = np.random.default_rng(3)
    index = pd.bdate_range("2020-01-01", periods=300)
    calm = 100 * np.exp(np.cumsum(rng.normal(0, 0.005, 300)))
    wild = 100 * np.exp(np.cumsum(rng.normal(0, 0.03, 300)))
    close = pd.DataFrame({"calm": calm, "wild": wild}, index=index)
    factor = compute_factor_panel(close, pd.DatetimeIndex([index[-1]]), ["low_volatility"])["low_volatility"]
    assert factor.iloc[0]["calm"] > factor.iloc[0]["wild"]


def test_composite_requires_every_factor():
    date = pd.Timestamp("2024-01-31")
    a = pd.DataFrame({"X": [1.0], "Y": [2.0], "Z": [3.0]}, index=[date])
    b = pd.DataFrame({"X": [3.0], "Y": [np.nan], "Z": [1.0]}, index=[date])
    score = composite_score({"a": a, "b": b})
    assert math.isnan(score.loc[date, "Y"])
    assert score.loc[date, "X"] == pytest.approx(score.loc[date, "Z"])


def test_composite_rejects_empty_weights():
    with pytest.raises(ValueError):
        composite_score({"a": pd.DataFrame()}, {"a": 0.0})


def test_unknown_factor_raises():
    with pytest.raises(ValueError):
        compute_factor_panel(_random_prices(3), None, ["astrology"])


# --- evaluation ---

def test_forward_returns_label_next_period():
    index = pd.bdate_range("2024-01-01", "2024-03-31")
    close = pd.DataFrame({"A": np.linspace(100, 130, len(index))}, index=index)
    dates = month_end_dates(index)
    fwd = forward_returns(close, dates)
    expected = close.loc[dates[1], "A"] / close.loc[dates[0], "A"] - 1
    assert fwd.loc[dates[0], "A"] == pytest.approx(expected)
    assert math.isnan(fwd.loc[dates[-1], "A"])


def test_rank_ic_perfect_and_inverse():
    dates = pd.DatetimeIndex(["2024-01-31", "2024-02-29"])
    scores = pd.DataFrame([list(range(20)), list(range(20))], index=dates)
    fwd = pd.DataFrame([list(range(20)), list(range(19, -1, -1))], index=dates)
    ic = rank_ic_series(scores, fwd)
    assert ic.iloc[0] == pytest.approx(1.0)
    assert ic.iloc[1] == pytest.approx(-1.0)


def test_ic_summary_statistics():
    summary = ic_summary(pd.Series([0.1, 0.1, 0.1, -0.1]))
    assert summary["n"] == 4
    assert summary["mean_ic"] == pytest.approx(0.05)
    assert summary["hit_rate"] == pytest.approx(0.75)
    assert ic_summary(pd.Series(dtype=float))["n"] == 0


def test_quantile_returns_monotonic_for_perfect_score():
    dates = pd.DatetimeIndex(["2024-01-31"])
    scores = pd.DataFrame([list(range(50))], index=dates, dtype=float)
    fwd = pd.DataFrame([[v / 100 for v in range(50)]], index=dates)
    q = quantile_returns(scores, fwd)
    assert list(q.values) == sorted(q.values)


def test_walk_forward_has_no_lookahead():
    close = _random_prices(30)
    dates = month_end_dates(close.index)
    factors = compute_factor_panel(close, dates, ["momentum_12_1", "low_volatility"])
    fwd = forward_returns(close, dates)
    base = walk_forward_weights(factors, fwd, min_train_periods=24, embargo_periods=1)
    test_date = base["weight_history"].index[10]
    position = list(dates).index(test_date)
    # Labels of the test date and the embargoed date before it must not matter.
    tampered = fwd.copy()
    tampered.iloc[position - 1 :] = np.random.default_rng(9).normal(0, 1, tampered.iloc[position - 1 :].shape)
    other = walk_forward_weights(factors, tampered, min_train_periods=24, embargo_periods=1)
    pd.testing.assert_series_equal(base["weight_history"].loc[test_date], other["weight_history"].loc[test_date])


def test_walk_forward_learns_dominant_factor():
    rng = np.random.default_rng(5)
    dates = pd.date_range("2010-01-31", periods=80, freq="M")
    symbols = [f"S{i}" for i in range(40)]
    good = pd.DataFrame(rng.normal(size=(80, 40)), index=dates, columns=symbols)
    noise = pd.DataFrame(rng.normal(size=(80, 40)), index=dates, columns=symbols)
    fwd = good * 0.05 + pd.DataFrame(rng.normal(0, 0.01, (80, 40)), index=dates, columns=symbols)
    result = walk_forward_weights({"good": good, "noise": noise}, fwd, min_train_periods=24)
    assert result["last_weights"]["good"] > abs(result["last_weights"]["noise"])
    assert result["learned_beats_equal"] is True


def test_deflated_sharpe_falls_with_more_trials():
    rng = np.random.default_rng(2)
    returns = pd.Series(rng.normal(0.01, 0.04, 120))
    one = deflated_sharpe_ratio(returns, 1)
    many = deflated_sharpe_ratio(returns, 100)
    assert one == pytest.approx(probabilistic_sharpe_ratio(returns))
    assert many < one


def test_deflated_sharpe_handles_degenerate_input():
    assert math.isnan(deflated_sharpe_ratio(pd.Series([0.01, 0.01, 0.01]), 5))


def test_snapshot_score_ic_perfect_ranking():
    index = pd.bdate_range("2024-01-01", periods=60)
    symbols = [f"S{i}" for i in range(15)]
    growth = np.array([1 + 0.001 * i for i in range(15)])
    close = pd.DataFrame(100 * growth ** np.arange(60)[:, None], index=index, columns=symbols)
    snapshots = [
        (datetime(2024, 1, 2, 11, 0), [{"symbol": s, "brodel_score": i} for i, s in enumerate(symbols)]),
        (datetime(2024, 3, 20, 11, 0), [{"symbol": s, "brodel_score": i} for i, s in enumerate(symbols)]),
    ]
    result = snapshot_score_ic(snapshots, close, horizon_days=21)
    assert result["summary"]["n"] == 1
    assert result["ic"].iloc[0] == pytest.approx(1.0)
    assert result["skipped_without_horizon"] == 1


def test_snapshot_score_ic_counts_only_non_overlapping_days():
    index = pd.bdate_range("2024-01-01", periods=80)
    symbols = [f"S{i}" for i in range(15)]
    growth = np.array([1 + 0.001 * i for i in range(15)])
    close = pd.DataFrame(100 * growth ** np.arange(80)[:, None], index=index, columns=symbols)
    snapshots = [
        (day.to_pydatetime(), [{"symbol": s, "brodel_score": i} for i, s in enumerate(symbols)])
        for day in index[:10]
    ]
    result = snapshot_score_ic(snapshots, close, horizon_days=5)
    assert result["summary"]["n"] == 10
    assert result["summary_independent"]["n"] == 2


# --- tax ---

def test_tax_allowance_and_withholding():
    account = GermanTaxAccount(TAX_RATE_DE, 1000.0)
    assert account.realize(2024, 800.0) == pytest.approx(0.0)
    assert account.realize(2024, 1200.0) == pytest.approx(TAX_RATE_DE * 1000.0)


def test_tax_refund_on_loss_within_year():
    account = GermanTaxAccount(TAX_RATE_DE, 0.0)
    paid = account.realize(2024, 1000.0)
    refund = account.realize(2024, -400.0)
    assert paid == pytest.approx(TAX_RATE_DE * 1000.0)
    assert refund == pytest.approx(-TAX_RATE_DE * 400.0)
    assert account.total_paid == pytest.approx(TAX_RATE_DE * 600.0)


def test_tax_loss_carry_into_next_year():
    account = GermanTaxAccount(TAX_RATE_DE, 0.0)
    account.realize(2023, -500.0)
    assert account.realize(2024, 300.0) == pytest.approx(0.0)
    assert account.realize(2024, 400.0) == pytest.approx(TAX_RATE_DE * 200.0)


def test_allowance_resets_each_year():
    account = GermanTaxAccount(TAX_RATE_DE, 1000.0)
    account.realize(2023, 1000.0)
    assert account.realize(2024, 1000.0) == pytest.approx(0.0)


# --- sector cap ---

def test_sector_cap_redistributes_excess():
    weights = pd.Series({"A": 0.25, "B": 0.25, "C": 0.25, "D": 0.25})
    sectors = {"A": "Tech", "B": "Tech", "C": "Tech", "D": "Energy"}
    capped = _cap_sector_weights(weights, sectors, 0.5)
    assert capped[["A", "B", "C"]].sum() == pytest.approx(0.5)
    assert capped["D"] == pytest.approx(0.5)


def test_sector_cap_leaves_cash_when_impossible():
    weights = pd.Series({"A": 0.5, "B": 0.5})
    capped = _cap_sector_weights(weights, {"A": "Tech", "B": "Tech"}, 0.25)
    assert capped.sum() == pytest.approx(0.25)


def test_sector_cap_ignores_unknown_sector():
    weights = pd.Series({"A": 0.5, "B": 0.5})
    capped = _cap_sector_weights(weights, {}, 0.25)
    pd.testing.assert_series_equal(capped, weights)


# --- backtest ---

def test_backtest_executes_after_signal_and_reports_metrics():
    close = _random_prices(40)
    result = run_factor_backtest(close, _benchmark(close.index), BacktestConfig(top_n=10))
    assert (result.rebalances["exec_date"] > result.rebalances["signal_date"]).all()
    assert result.metrics["n_rebalances"] > 50
    assert result.equity["strategy"].notna().all()
    assert result.metrics["final_value_after_tax"] <= result.metrics["final_value_pre_tax"] + 1e-6


def test_backtest_without_tax_or_costs_pays_nothing():
    close = _random_prices(40)
    config = BacktestConfig(top_n=10, apply_tax=False, transaction_cost_pct=0.0)
    result = run_factor_backtest(close, _benchmark(close.index), config)
    assert result.metrics["taxes_paid"] == pytest.approx(0.0)
    assert result.metrics["costs_paid"] == pytest.approx(0.0)
    assert result.metrics["final_value_after_tax"] == pytest.approx(result.metrics["final_value_pre_tax"])


def test_benchmark_tax_uses_partial_exemption():
    close = _random_prices(40)
    bench = _benchmark(close.index, daily=0.0005)
    config = BacktestConfig(top_n=10, transaction_cost_pct=0.0)
    result = run_factor_backtest(close, bench, config)
    gain = result.benchmark_metrics["final_value_pre_tax"] - config.initial_capital
    expected = TAX_RATE_DE * max(0.0, gain * (1 - ETF_TEILFREISTELLUNG) - config.tax_allowance)
    assert result.benchmark_metrics["taxes_paid"] == pytest.approx(expected)


def test_trend_filter_reduces_exposure_in_downtrend():
    close = _random_prices(40)
    falling = pd.Series(100 * np.exp(-np.arange(len(close.index)) * 0.0005), index=close.index)
    result = run_factor_backtest(close, falling, BacktestConfig(top_n=10, risk_off_exposure=0.5))
    later = result.rebalances.iloc[12:]
    assert later["risk_off"].all()
    assert (later["exposure"] == 0.5).all()
    off = run_factor_backtest(close, falling, BacktestConfig(top_n=10, trend_filter=False))
    assert not off.rebalances["risk_off"].any()


def test_backtest_never_runs_negative_cash():
    close = _random_prices(40)
    result = run_factor_backtest(close, _benchmark(close.index), BacktestConfig(top_n=5, weighting="inverse_vol"))
    assert (result.equity["strategy"] > 0).all()


def test_backtest_needs_enough_universe():
    close = _random_prices(5)
    with pytest.raises(ValueError):
        run_factor_backtest(close, _benchmark(close.index), BacktestConfig(min_universe=30))


# --- report ---

def test_truth_report_contains_verdict_and_is_serialisable():
    import json

    close = _random_prices(40)
    report = build_truth_report(close, _benchmark(close.index), BacktestConfig(top_n=10), min_train_periods=24)
    assert report["verdict"]
    assert "composite" in report["factor_ic"]
    assert report["walk_forward"] is not None
    json.dumps(report_to_jsonable(report), default=str)


def test_verdict_prefers_etf_when_strategy_loses():
    report = {
        "factor_ic": {"composite": {"t_stat": 0.5}},
        "walk_forward": {"learned_beats_equal": False},
        "backtest": {
            "metrics": {"cagr_after_tax": 0.05, "deflated_sharpe_excess": 0.2, "max_drawdown": -0.4},
            "benchmark_metrics": {"cagr_after_tax": 0.07, "max_drawdown": -0.5},
        },
    }
    text = " ".join(build_verdict(report))
    assert "nicht signifikant" in text
    assert "ETF ist nach Kosten und Steuern" in text
    assert "Gleichgewichtung bleibt" in text


# --- data ---

def test_symbol_normalisation_and_currency_filter():
    assert to_yahoo_symbol("BRK.B") == "BRK-B"
    assert to_yahoo_symbol("sap.de") == "SAP.DE"
    assert is_us_listing("AAPL")
    assert not is_us_listing("7203.T")
    assert not is_us_listing("^GSPC")
    assert filter_single_currency(["AAPL", "SAP.DE", "BRK.B", "AAPL"]) == ["AAPL", "BRK-B"]
    assert filter_single_currency(["AAPL", "SAP.DE"], us_only=False) == ["AAPL", "SAP.DE"]


def test_extract_close_handles_multiindex():
    index = pd.bdate_range("2024-01-01", periods=3)
    columns = pd.MultiIndex.from_product([["Close", "Volume"], ["A", "B"]])
    raw = pd.DataFrame(np.ones((3, 4)), index=index, columns=columns)
    close = _extract_close(raw, ["A", "B"])
    assert list(close.columns) == ["A", "B"]


def test_download_uses_cache(tmp_path):
    index = pd.bdate_range("2024-01-01", periods=3)
    raw = pd.DataFrame(
        np.ones((3, 2)), index=index, columns=pd.MultiIndex.from_product([["Close"], ["A", "B"]])
    )
    with patch("yfinance.download", return_value=raw) as mock_download:
        first = download_close_prices(["A", "B"], start="2024-01-01", end="2024-01-05", cache_dir=tmp_path)
        second = download_close_prices(["A", "B"], start="2024-01-01", end="2024-01-05", cache_dir=tmp_path)
    assert mock_download.call_count == 1
    pd.testing.assert_frame_equal(first, second)

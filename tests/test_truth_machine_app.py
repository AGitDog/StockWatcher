"""Tests for the truth machine integration in app.py."""

from __future__ import annotations

import numpy as np
import pandas as pd


def _report():
    from factor_lab import BacktestConfig, build_truth_report

    rng = np.random.default_rng(0)
    index = pd.bdate_range("2012-01-02", "2018-12-31")
    returns = rng.normal(0.0003, 0.015, (len(index), 40))
    close = pd.DataFrame(100 * np.exp(np.cumsum(returns, axis=0)), index=index, columns=[f"S{i}" for i in range(40)])
    bench = pd.Series(100 * np.exp(np.arange(len(index)) * 0.0003), index=index)
    return build_truth_report(close, bench, BacktestConfig(top_n=10), min_train_periods=24)


def test_app_exposes_truth_machine_sections():
    import app

    assert callable(app.render_truth_machine_section)
    assert callable(app.render_brodel_check_section)


def test_truth_metrics_rows_compare_strategy_and_etf():
    import app

    rows = app.build_truth_metrics_rows(_report())
    labels = [row["Kennzahl"] for row in rows]
    assert "Rendite p. a. nach Endverkauf und Steuer" in labels
    assert "Maximaler Verlust" in labels
    assert all(set(row) == {"Kennzahl", "Strategie", "ETF"} for row in rows)
    assert all(row["Strategie"] for row in rows)


def test_truth_metrics_rows_handle_missing_values():
    import app

    nan = float("nan")
    report = {
        "backtest": {
            "metrics": {k: nan for k in ["cagr", "cagr_after_tax", "volatility", "max_drawdown", "sharpe", "final_value_after_tax", "taxes_paid", "costs_paid"]},
            "benchmark_metrics": {k: nan for k in ["cagr", "cagr_after_tax", "volatility", "max_drawdown", "sharpe", "final_value_after_tax", "taxes_paid"]},
        }
    }
    rows = app.build_truth_metrics_rows(report)
    assert all(row["Strategie"] == "–" for row in rows)


def test_factor_ic_rows_include_composite():
    import app

    rows = app.build_factor_ic_rows(_report())
    assert any(row["Faktor"] == "composite" for row in rows)


def test_truth_machine_section_renders_without_report():
    from streamlit.testing.v1 import AppTest

    def page():
        import app

        app.render_truth_machine_section()
        app.render_brodel_check_section()

    at = AppTest.from_function(page)
    at.run(timeout=60)
    assert not at.exception
    labels = [button.label for button in at.button]
    assert "Wahrheitsmaschine starten" in labels
    assert "Brodel-Score messen" in labels

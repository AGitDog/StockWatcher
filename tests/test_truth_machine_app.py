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
    assert "Score messen" in labels


def _rendered_help_text(render_name: str) -> str:
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_string(f"import app\napp.{render_name}()\n")
    at.run(timeout=60)
    assert not at.exception
    parts = [m.value for m in at.markdown] + [c.value for c in at.caption] + [i.value for i in at.info]
    parts += [str(t.value) for t in at.table] + [c.value for c in at.code]
    return "\n".join(parts)


def test_truth_machine_help_explains_etf_benchmark():
    text = _rendered_help_text("render_truth_machine_help")
    for term in ["Teilfreistellung", "Sparerpauschbetrag", "26,375", "SPY", "QQQ", "URTH", "DIA", "Survivorship", "Trendfilter", "Deflated Sharpe"]:
        assert term in text, term


def test_help_tab_includes_truth_machine_and_fixed_macro_text():
    text = _rendered_help_text("render_help_tab")
    assert "Die Wahrheitsmaschine einfach erklärt" in text
    assert "negative Scores dadurch geteilt" not in text  # the overlay only applied to the old version
    assert "60 Snapshot-Tage" in text


def test_help_tab_omits_removed_sections():
    text = _rendered_help_text("render_help_tab")
    for removed in ["meine_watchlist.txt", "Der menschliche Faktor", "Empfohlener Einstiegsplan", "headless"]:
        assert removed not in text, removed

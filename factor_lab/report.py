"""Combine factor statistics, walk-forward test and backtest into one honest report."""

from __future__ import annotations

import math
from typing import Any

import pandas as pd

from .backtest import BacktestConfig, FactorBacktestResult, run_factor_backtest
from .evaluation import forward_returns, ic_summary, quantile_returns, rank_ic_series, walk_forward_weights
from .factors import DEFAULT_FACTOR_WEIGHTS, FACTOR_DESCRIPTIONS, composite_score, compute_factor_panel, month_end_dates

T_STAT_SIGNIFICANT = 2.0
DSR_ROBUST = 0.95

CAVEATS = [
    "Survivorship Bias: Das Universum besteht aus heutigen Indexmitgliedern. Spaeter "
    "gestrichene oder insolvente Firmen fehlen. Das schoent absolute Renditen und "
    "bevorzugt rueckblickend schwankungsstarke Titel, weil nur deren Gewinner ueberlebt haben.",
    "Dividenden stecken in den bereinigten Kursen und werden steuerfrei reinvestiert, "
    "auf beiden Seiten des Vergleichs.",
    "Die Vorabpauschale des ETF ist nicht modelliert, das beguenstigt den ETF leicht.",
    "Jede getestete Variante erhoeht die Gefahr eines Zufallstreffers. Die Anzahl "
    "der Versuche gehoert in die Deflated Sharpe Ratio.",
]


def _finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and not math.isnan(value)


def build_verdict(report: dict[str, Any]) -> list[str]:
    """Plain German conclusions derived only from the measured numbers."""
    lines: list[str] = []
    composite = report["factor_ic"].get("composite", {})
    t_stat = composite.get("t_stat")
    if _finite(t_stat) and t_stat >= T_STAT_SIGNIFICANT:
        lines.append(f"Der Faktor-Score sortiert die Folgerenditen signifikant (t = {t_stat:.1f}).")
    elif _finite(t_stat):
        lines.append(f"Der Faktor-Score sortiert die Folgerenditen nicht signifikant (t = {t_stat:.1f}, Schwelle 2,0).")

    wf = report.get("walk_forward")
    if wf:
        learned_t = (wf.get("summary_learned") or {}).get("t_stat")
        if wf["learned_beats_equal"] and _finite(learned_t) and learned_t >= T_STAT_SIGNIFICANT:
            lines.append(f"Gelernte Gewichte schlagen die Gleichgewichtung out of sample, signifikant (t = {learned_t:.1f}).")
        elif wf["learned_beats_equal"]:
            t_text = f" (t = {learned_t:.1f})" if _finite(learned_t) else ""
            lines.append(f"Gelernte Gewichte schlagen die Gleichgewichtung out of sample, aber nicht signifikant{t_text}. Das reicht nicht fuer einen Wechsel.")
        else:
            lines.append("Gelernte Gewichte schlagen die Gleichgewichtung out of sample nicht. Gleichgewichtung bleibt.")

    bt = report["backtest"]
    excess = bt["metrics"]["cagr"] - bt["benchmark_metrics"]["cagr"]
    dsr = bt["metrics"].get("deflated_sharpe_excess")
    if _finite(excess) and excess > 0 and _finite(dsr) and dsr >= DSR_ROBUST:
        lines.append(f"Die Strategie schlaegt den ETF um {excess * 100:.1f} Prozentpunkte pro Jahr, statistisch belastbar.")
    elif _finite(excess) and excess > 0:
        lines.append(f"Die Strategie schlaegt den ETF um {excess * 100:.1f} Prozentpunkte pro Jahr, aber nicht statistisch belastbar.")
    elif _finite(excess):
        lines.append(f"Der ETF ist um {-excess * 100:.1f} Prozentpunkte pro Jahr besser.")

    dd_s = bt["metrics"].get("max_drawdown")
    dd_b = bt["benchmark_metrics"].get("max_drawdown")
    if _finite(dd_s) and _finite(dd_b):
        lines.append(f"Maximaler Verlust: Strategie {dd_s * 100:.0f} Prozent, ETF {dd_b * 100:.0f} Prozent.")
    return lines


def build_truth_report(
    close: pd.DataFrame,
    benchmark_close: pd.Series,
    config: BacktestConfig | None = None,
    walk_forward: bool = True,
    min_train_periods: int = 36,
) -> dict[str, Any]:
    """Run every check of the truth machine on one price panel."""
    config = config or BacktestConfig()
    weights = config.factor_weights or DEFAULT_FACTOR_WEIGHTS
    prices = close.sort_index().ffill()
    dates = month_end_dates(prices.index)
    factor_values = compute_factor_panel(prices, dates, list(weights))
    scores = composite_score(factor_values, weights)
    fwd = forward_returns(prices, dates)

    factor_ic: dict[str, dict[str, float]] = {}
    for name, values in factor_values.items():
        factor_ic[name] = ic_summary(rank_ic_series(values, fwd))
    composite_ic = rank_ic_series(scores, fwd)
    factor_ic["composite"] = ic_summary(composite_ic)

    wf_result = None
    if walk_forward and len(factor_values) > 1:
        wf_result = walk_forward_weights(factor_values, fwd, min_train_periods=min_train_periods)

    result: FactorBacktestResult = run_factor_backtest(prices, benchmark_close, config, scores=scores)
    report: dict[str, Any] = {
        "universe_size": int(prices.shape[1]),
        "period": {"start": result.metrics["start"], "end": result.metrics["end"]},
        "factors": {name: FACTOR_DESCRIPTIONS.get(name, "") for name in weights},
        "factor_weights": dict(weights),
        "factor_ic": factor_ic,
        "composite_ic_series": composite_ic,
        "quintile_monthly_returns": quantile_returns(scores, fwd),
        "walk_forward": None if wf_result is None else {
            "summary_learned": wf_result["summary_learned"],
            "summary_equal": wf_result["summary_equal"],
            "learned_beats_equal": wf_result["learned_beats_equal"],
            "last_weights": wf_result["last_weights"],
        },
        "backtest": {
            "metrics": result.metrics,
            "benchmark_metrics": result.benchmark_metrics,
        },
        "backtest_result": result,
        "caveats": list(CAVEATS),
    }
    report["verdict"] = build_verdict(report)
    return report


def report_to_jsonable(report: dict[str, Any]) -> dict[str, Any]:
    """Drop heavy objects and convert pandas types for JSON output."""
    out: dict[str, Any] = {}
    for key, value in report.items():
        if key == "backtest_result":
            continue
        if isinstance(value, pd.Series):
            out[key] = {str(k.date() if hasattr(k, "date") else k): (None if pd.isna(v) else float(v)) for k, v in value.items()}
        elif isinstance(value, dict):
            out[key] = _clean(value)
        else:
            out[key] = value
    return out


def _clean(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(v) for v in value]
    if isinstance(value, float) and math.isnan(value):
        return None
    if hasattr(value, "item"):
        return value.item()
    return value

"""Command line entry point: ``python -m factor_lab``.

Example::

    python -m factor_lab --universe "S&P 500" --benchmark SPY --start 2005-01-01
    python -m factor_lab --brodel   # measure the stored Brodel-Score snapshots
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

from .backtest import BacktestConfig
from .data import download_close_prices, filter_single_currency, load_sector_map, load_universe
from .evaluation import snapshot_score_ic
from .report import build_truth_report, report_to_jsonable

REPORT_DIR = Path("cache/factor_lab/reports")


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Wahrheitsmaschine: Faktor-Backtest gegen einen ETF, ohne Kosten und Steuern.")
    parser.add_argument("--universe", default="S&P 500", help="Indexname oder Pfad zu einer Watchlist-Datei.")
    parser.add_argument("--benchmark", default="SPY", help="Benchmark-ETF, zum Beispiel SPY oder URTH.")
    parser.add_argument("--start", default="2005-01-01")
    parser.add_argument("--end", default=None)
    parser.add_argument("--factors", default=None, help="Kommagetrennte Faktoren, zum Beispiel momentum_12_1,low_volatility.")
    parser.add_argument("--top-n", type=int, default=20)
    parser.add_argument("--weighting", choices=["equal", "inverse_vol"], default="equal")
    parser.add_argument("--rebalance-months", type=int, default=1)
    parser.add_argument("--no-trend-filter", action="store_true")
    parser.add_argument("--risk-off-exposure", type=float, default=0.5)
    parser.add_argument("--sector-cap", type=float, default=None, help="Maximaler Anteil je Sektor, zum Beispiel 0.25.")
    parser.add_argument("--capital", type=float, default=100_000.0)
    parser.add_argument("--n-trials", type=int, default=1, help="Anzahl bisher getesteter Varianten fuer die Deflated Sharpe Ratio.")
    parser.add_argument("--brodel", action="store_true", help="Statt des Faktor-Backtests die gespeicherten Brodel-Scores messen.")
    parser.add_argument("--horizon-days", type=int, default=21)
    parser.add_argument("--out", default=str(REPORT_DIR))
    return parser.parse_args(argv)


def _run_brodel(args: argparse.Namespace) -> dict:
    from backtest_engine.engine import load_snapshots

    snapshots = load_snapshots()
    symbols = sorted({item.get("symbol") for _, items in snapshots for item in items if item.get("symbol")})
    first = min(ts for ts, _ in snapshots).strftime("%Y-%m-%d") if snapshots else args.start
    # Local-currency returns are fine for a rank correlation, so no currency filter here.
    close = download_close_prices(filter_single_currency(symbols, us_only=False), start=first)
    result = snapshot_score_ic(snapshots, close, horizon_days=args.horizon_days)
    summary = result["summary"]
    print(f"Snapshot-Tage: {result['n_snapshot_days']}, auswertbar: {summary['n']}, ohne {args.horizon_days}-Tage-Horizont: {result['skipped_without_horizon']}")
    if summary["n"]:
        print(f"Mittlerer Rank-IC: {summary['mean_ic']:+.3f}  t-Wert: {summary['t_stat']:.2f}  Trefferquote: {summary['hit_rate'] * 100:.0f} %")
    independent = result["summary_independent"]
    if independent["n"]:
        t_text = f"{independent['t_stat']:.2f}" if independent["n"] > 1 else "n/a"
        print(f"Ohne ueberlappende Fenster: {independent['n']} Messpunkte, mittlerer Rank-IC {independent['mean_ic']:+.3f}, t-Wert {t_text}")
    if independent["n"] < 24:
        print("Hinweis: Unter 24 unabhaengigen Messpunkten ist keine belastbare Aussage moeglich.")
    return {"summary": summary, "summary_independent": independent, "n_snapshot_days": result["n_snapshot_days"], "ic": {str(k.date()): v for k, v in result["ic"].items()}}


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.WARNING)
    args = _parse_args(argv)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    if args.brodel:
        payload = _run_brodel(args)
        (out_dir / f"brodel_ic_{stamp}.json").write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        return 0

    symbols = load_universe(args.universe)
    print(f"Universum: {len(symbols)} Titel in einer Waehrung. Lade Kurse ab {args.start} ...")
    close = download_close_prices(symbols + [args.benchmark], start=args.start, end=args.end)
    if args.benchmark not in close.columns:
        print(f"Benchmark {args.benchmark} konnte nicht geladen werden.", file=sys.stderr)
        return 1
    benchmark = close.pop(args.benchmark)

    factor_weights = {name.strip(): 1.0 for name in args.factors.split(",") if name.strip()} if args.factors else None
    config = BacktestConfig(
        factor_weights=factor_weights,
        top_n=args.top_n,
        weighting=args.weighting,
        rebalance_months=args.rebalance_months,
        trend_filter=not args.no_trend_filter,
        risk_off_exposure=args.risk_off_exposure,
        max_sector_weight=args.sector_cap,
        sectors=load_sector_map() if args.sector_cap else None,
        initial_capital=args.capital,
        n_trials=args.n_trials,
    )
    report = build_truth_report(close, benchmark, config)
    m = report["backtest"]["metrics"]
    b = report["backtest"]["benchmark_metrics"]
    print(f"\nZeitraum {report['period']['start']} bis {report['period']['end']}, {report['universe_size']} Titel")
    print(f"{'':28}{'Strategie':>14}{args.benchmark:>14}")
    rows = [
        ("CAGR", m["cagr"], b["cagr"], True),
        ("Volatilitaet", m["volatility"], b["volatility"], True),
        ("Max. Drawdown", m["max_drawdown"], b["max_drawdown"], True),
        ("Sharpe", m["sharpe"], b["sharpe"], False),
        ("Endvermoegen", m["final_value"], b["final_value"], None),
    ]
    for label, left, right, pct in rows:
        if pct is True:
            print(f"{label:28}{left * 100:>13.1f}%{right * 100:>13.1f}%")
        elif pct is False:
            print(f"{label:28}{left:>14.2f}{right:>14.2f}")
        else:
            print(f"{label:28}{left:>14,.0f}{right:>14,.0f}")
    print(f"Deflated Sharpe (Ueberrendite) {m['deflated_sharpe_excess']:.2f}")
    print("\nUrteil:")
    for line in report["verdict"]:
        print(f"- {line}")

    target = out_dir / f"truth_report_{stamp}.json"
    target.write_text(json.dumps(report_to_jsonable(report), indent=2, default=str), encoding="utf-8")
    report["backtest_result"].equity.to_csv(out_dir / f"equity_{stamp}.csv")
    print(f"\nBericht gespeichert: {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

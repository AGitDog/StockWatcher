"""Statistical evaluation: information coefficient, quantile spreads, walk-forward
weight learning with embargo, and the deflated Sharpe ratio."""

from __future__ import annotations

import math
from datetime import datetime
from statistics import NormalDist
from typing import Any

import numpy as np
import pandas as pd

from .factors import common_eligibility, cross_sectional_rank

_NORMAL = NormalDist()
EULER_MASCHERONI = 0.5772156649015329


def forward_returns(close: pd.DataFrame, dates: pd.DatetimeIndex) -> pd.DataFrame:
    """Return from each signal date to the next one (the label for that date).

    The last date has no label and is NaN.
    """
    sampled = close.sort_index().ffill().reindex(dates)
    return sampled.shift(-1) / sampled - 1.0


def rank_ic_series(scores: pd.DataFrame, fwd: pd.DataFrame, min_names: int = 10) -> pd.Series:
    """Spearman correlation between score and forward return, one value per date."""
    values: dict[pd.Timestamp, float] = {}
    for date in scores.index:
        if date not in fwd.index:
            continue
        pair = pd.concat([scores.loc[date], fwd.loc[date]], axis=1, keys=["s", "r"]).dropna()
        if len(pair) < min_names or pair["s"].nunique() < 2 or pair["r"].nunique() < 2:
            continue
        values[date] = float(pair["s"].rank().corr(pair["r"].rank()))
    return pd.Series(values, dtype=float).sort_index()


def ic_summary(ic: pd.Series) -> dict[str, float]:
    """Mean IC, its t-statistic and the share of positive periods."""
    ic = ic.dropna()
    n = int(len(ic))
    if n == 0:
        return {"n": 0, "mean_ic": float("nan"), "std_ic": float("nan"), "t_stat": float("nan"), "hit_rate": float("nan")}
    std = float(ic.std(ddof=1)) if n > 1 else float("nan")
    t_stat = float(ic.mean() / std * math.sqrt(n)) if n > 1 and std > 0 else float("nan")
    return {
        "n": n,
        "mean_ic": float(ic.mean()),
        "std_ic": std,
        "t_stat": t_stat,
        "hit_rate": float((ic > 0).mean()),
    }


def quantile_returns(scores: pd.DataFrame, fwd: pd.DataFrame, n_quantiles: int = 5) -> pd.Series:
    """Average forward return per score quantile (1 = worst, n = best)."""
    collected: dict[int, list[float]] = {q: [] for q in range(1, n_quantiles + 1)}
    for date in scores.index:
        if date not in fwd.index:
            continue
        pair = pd.concat([scores.loc[date], fwd.loc[date]], axis=1, keys=["s", "r"]).dropna()
        if len(pair) < n_quantiles * 2:
            continue
        buckets = pd.qcut(pair["s"].rank(method="first"), n_quantiles, labels=False) + 1
        means = pair["r"].groupby(buckets).mean()
        for q, value in means.items():
            collected[int(q)].append(float(value))
    return pd.Series({q: float(np.mean(v)) if v else float("nan") for q, v in collected.items()})


def walk_forward_weights(
    factor_values: dict[str, pd.DataFrame],
    fwd: pd.DataFrame,
    min_train_periods: int = 36,
    embargo_periods: int = 1,
    ridge_lambda: float = 1.0,
) -> dict[str, Any]:
    """Learn factor weights on an expanding window and test them strictly out of sample.

    At signal date i the label of date d is known once date d+1 has passed, so only
    dates up to i-1 carry known labels. The embargo removes a further
    ``embargo_periods`` dates to avoid overlap between training labels and the test.
    The learned score is compared with the equal-weight score on the same dates.
    """
    names = list(factor_values)
    ranks = {name: cross_sectional_rank(values) for name, values in common_eligibility(factor_values).items()}
    fwd_rank = cross_sectional_rank(fwd)
    dates = list(fwd.index)

    # Pre-stack each date once; the expanding window then just concatenates.
    per_date: dict[pd.Timestamp, tuple[np.ndarray, np.ndarray]] = {}
    for date in dates:
        frame = pd.concat([ranks[n].loc[date] for n in names] + [fwd_rank.loc[date]], axis=1).dropna()
        if not frame.empty:
            per_date[date] = (frame.iloc[:, :-1].values - 0.5, frame.iloc[:, -1].values - 0.5)

    learned_scores: dict[pd.Timestamp, pd.Series] = {}
    equal_scores: dict[pd.Timestamp, pd.Series] = {}
    weight_history: dict[pd.Timestamp, dict[str, float]] = {}
    xtx = np.zeros((len(names), len(names)))
    xty = np.zeros(len(names))
    n_obs = 0
    included = 0  # number of leading dates already added to the normal equations
    for i, date in enumerate(dates):
        last_label = i - 1 - embargo_periods
        while included <= last_label:
            stacked = per_date.get(dates[included])
            if stacked is not None:
                x, y = stacked
                xtx += x.T @ x
                xty += x.T @ y
                n_obs += len(y)
            included += 1
        if last_label + 1 < min_train_periods or n_obs < 50:
            continue
        coef = np.linalg.solve(xtx + ridge_lambda * np.eye(len(names)), xty)
        weight_history[date] = {n: float(c) for n, c in zip(names, coef)}
        current = pd.concat([ranks[n].loc[date] for n in names], axis=1, keys=names).dropna()
        if current.empty:
            continue
        learned_scores[date] = pd.Series((current.values - 0.5) @ coef, index=current.index)
        equal_scores[date] = current.mean(axis=1)

    learned = pd.DataFrame(learned_scores).T
    equal = pd.DataFrame(equal_scores).T
    ic_learned = rank_ic_series(learned, fwd) if not learned.empty else pd.Series(dtype=float)
    ic_equal = rank_ic_series(equal, fwd) if not equal.empty else pd.Series(dtype=float)
    summary_learned = ic_summary(ic_learned)
    summary_equal = ic_summary(ic_equal)
    beats = (
        summary_learned["n"] > 0
        and not math.isnan(summary_learned["mean_ic"])
        and summary_learned["mean_ic"] > summary_equal["mean_ic"]
    )
    last_weights = weight_history[max(weight_history)] if weight_history else {}
    return {
        "ic_learned": ic_learned,
        "ic_equal": ic_equal,
        "summary_learned": summary_learned,
        "summary_equal": summary_equal,
        "learned_beats_equal": bool(beats),
        "last_weights": last_weights,
        "weight_history": pd.DataFrame(weight_history).T,
    }


def sharpe_ratio(returns: pd.Series, periods_per_year: int = 12) -> float:
    """Annualised Sharpe ratio with a zero risk-free rate."""
    returns = returns.dropna()
    if len(returns) < 2 or returns.std(ddof=1) == 0:
        return float("nan")
    return float(returns.mean() / returns.std(ddof=1) * math.sqrt(periods_per_year))


def _sharpe_moments(returns: pd.Series) -> tuple[float, float, float]:
    sr = float(returns.mean() / returns.std(ddof=1))
    skew = float(returns.skew())
    kurt = float(returns.kurt()) + 3.0  # pandas reports excess kurtosis
    return sr, skew, kurt


def probabilistic_sharpe_ratio(returns: pd.Series, benchmark_sr: float = 0.0) -> float:
    """Probability that the true per-period Sharpe ratio exceeds ``benchmark_sr``.

    Accounts for sample length, skewness and fat tails (Bailey and Lopez de Prado, 2012).
    """
    returns = returns.dropna()
    t = len(returns)
    if t < 3 or returns.std(ddof=1) == 0:
        return float("nan")
    sr, skew, kurt = _sharpe_moments(returns)
    denom = 1.0 - skew * sr + (kurt - 1.0) / 4.0 * sr**2
    if denom <= 0:
        return float("nan")
    z = (sr - benchmark_sr) * math.sqrt(t - 1) / math.sqrt(denom)
    return float(_NORMAL.cdf(z))


def deflated_sharpe_ratio(returns: pd.Series, n_trials: int = 1) -> float:
    """Probabilistic Sharpe ratio against the best Sharpe expected from luck alone.

    With ``n_trials`` tested configurations, the expected maximum Sharpe of pure noise
    rises. The benchmark uses the estimator variance of the Sharpe ratio as a proxy for
    the variance across trials (Bailey and Lopez de Prado, 2014). A value above 0.95
    means the result is unlikely to be a product of trying many variants.
    """
    returns = returns.dropna()
    t = len(returns)
    if t < 3 or returns.std(ddof=1) == 0:
        return float("nan")
    n_trials = max(int(n_trials), 1)
    if n_trials == 1:
        return probabilistic_sharpe_ratio(returns, 0.0)
    sr, skew, kurt = _sharpe_moments(returns)
    sr_variance = max((1.0 - skew * sr + (kurt - 1.0) / 4.0 * sr**2) / (t - 1), 1e-12)
    expected_max = math.sqrt(sr_variance) * (
        (1.0 - EULER_MASCHERONI) * _NORMAL.inv_cdf(1.0 - 1.0 / n_trials)
        + EULER_MASCHERONI * _NORMAL.inv_cdf(1.0 - 1.0 / (n_trials * math.e))
    )
    return probabilistic_sharpe_ratio(returns, expected_max)


def snapshot_score_ic(
    snapshots: list[tuple[datetime, list[dict[str, Any]]]],
    close: pd.DataFrame,
    horizon_days: int = 21,
    score_key: str = "brodel_score",
    min_names: int = 10,
) -> dict[str, Any]:
    """Measure how well a stored snapshot score ranks the following returns.

    For each snapshot day the score is compared with the return from the first
    trading day on or after the snapshot to ``horizon_days`` trading days later.
    Snapshots of the same calendar day are merged; the latest one wins.
    """
    close = close.sort_index().ffill()
    by_day: dict[pd.Timestamp, dict[str, float]] = {}
    for timestamp, items in sorted(snapshots, key=lambda entry: entry[0]):
        day = pd.Timestamp(timestamp)
        if day.tzinfo is not None:
            day = day.tz_convert(None)
        day = day.normalize()
        scores = by_day.setdefault(day, {})
        for item in items:
            symbol = item.get("symbol")
            score = item.get(score_key)
            if symbol and isinstance(score, (int, float)) and not isinstance(score, bool):
                scores[symbol] = float(score)

    ic_values: dict[pd.Timestamp, float] = {}
    start_positions: dict[pd.Timestamp, int] = {}
    skipped_without_horizon = 0
    for day, scores in sorted(by_day.items()):
        position = int(close.index.searchsorted(day))
        if position + horizon_days >= len(close.index):
            skipped_without_horizon += 1
            continue
        start = close.iloc[position]
        end = close.iloc[position + horizon_days]
        fwd = end / start - 1.0
        pair = pd.concat([pd.Series(scores, dtype=float), fwd], axis=1, keys=["s", "r"]).dropna()
        if len(pair) < min_names or pair["s"].nunique() < 2 or pair["r"].nunique() < 2:
            continue
        ic_values[day] = float(pair["s"].rank().corr(pair["r"].rank()))
        start_positions[day] = position

    ic = pd.Series(ic_values, dtype=float).sort_index()
    # Consecutive snapshot days share most of their forward window, which inflates the
    # t-statistic. Keep only days whose windows do not overlap for an honest estimate.
    independent: list[pd.Timestamp] = []
    next_free = -1
    for day in ic.index:
        if start_positions[day] >= next_free:
            independent.append(day)
            next_free = start_positions[day] + horizon_days
    return {
        "ic": ic,
        "summary": ic_summary(ic),
        "summary_independent": ic_summary(ic.loc[independent]),
        "n_snapshot_days": len(by_day),
        "skipped_without_horizon": skipped_without_horizon,
        "horizon_days": horizon_days,
    }

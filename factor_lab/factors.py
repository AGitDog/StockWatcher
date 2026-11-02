"""Price-only factors that can be reconstructed for any historical date.

All factors are computed from data up to and including the signal date. They are
sampled on month-end trading days and converted to cross-sectional percentile ranks,
so absolute scale and outliers do not matter.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

TRADING_DAYS_PER_YEAR = 252
TRADING_DAYS_PER_MONTH = 21

# Equal weights are the benchmark. Learned weights must beat them out of sample.
DEFAULT_FACTOR_WEIGHTS: dict[str, float] = {
    "momentum_12_1": 1.0,
    "low_volatility": 1.0,
}

FACTOR_DESCRIPTIONS: dict[str, str] = {
    "momentum_12_1": "Rendite der letzten 12 Monate ohne den juengsten Monat (Jegadeesh/Titman).",
    "momentum_6_1": "Rendite der letzten 6 Monate ohne den juengsten Monat.",
    "low_volatility": "Negative annualisierte Volatilitaet der letzten 12 Monate (Low-Vol-Anomalie).",
    "reversal_1m": "Negative Rendite des letzten Monats (kurzfristige Umkehr, hoher Umschlag).",
    "trend_200d": "Abstand des Kurses zum 200-Tage-Durchschnitt.",
}


def month_end_dates(index: pd.DatetimeIndex) -> pd.DatetimeIndex:
    """Last available trading day of each calendar month in ``index``."""
    if len(index) == 0:
        return pd.DatetimeIndex([])
    series = pd.Series(index, index=index)
    last_per_month = series.groupby([index.year, index.month]).max()
    return pd.DatetimeIndex(last_per_month.values)


def compute_factor_panel(
    close: pd.DataFrame,
    dates: pd.DatetimeIndex | None = None,
    factors: list[str] | None = None,
) -> dict[str, pd.DataFrame]:
    """Compute raw factor values (higher = better) sampled on ``dates``.

    ``close`` is a wide frame of adjusted daily closes (rows = days, columns = symbols).
    A value is NaN when the symbol lacks enough history on that date.
    """
    close = close.sort_index()
    if dates is None:
        dates = month_end_dates(close.index)
    names = factors or list(DEFAULT_FACTOR_WEIGHTS)
    m = TRADING_DAYS_PER_MONTH
    y = TRADING_DAYS_PER_YEAR

    raw: dict[str, pd.DataFrame] = {}
    log_returns = np.log(close).diff()
    for name in names:
        if name == "momentum_12_1":
            values = close.shift(m) / close.shift(y) - 1.0
        elif name == "momentum_6_1":
            values = close.shift(m) / close.shift(6 * m) - 1.0
        elif name == "low_volatility":
            values = -log_returns.rolling(y, min_periods=int(y * 0.8)).std() * np.sqrt(y)
        elif name == "reversal_1m":
            values = -(close / close.shift(m) - 1.0)
        elif name == "trend_200d":
            values = close / close.rolling(200, min_periods=200).mean() - 1.0
        else:
            raise ValueError(f"Unbekannter Faktor: {name}")
        raw[name] = values.reindex(dates)
    return raw


def cross_sectional_rank(values: pd.DataFrame) -> pd.DataFrame:
    """Percentile rank per date across symbols (0..1, higher = better)."""
    return values.rank(axis=1, pct=True)


def composite_score(
    factor_values: dict[str, pd.DataFrame],
    weights: dict[str, float] | None = None,
) -> pd.DataFrame:
    """Weighted mean of cross-sectional factor ranks.

    A symbol only gets a score on a date if every weighted factor is available,
    so newly listed stocks cannot slip in with a partial score.
    """
    weights = weights or {name: 1.0 for name in factor_values}
    active = {name: w for name, w in weights.items() if w and name in factor_values}
    if not active:
        raise ValueError("Keine aktiven Faktorgewichte.")
    total = float(sum(abs(w) for w in active.values()))
    masked = common_eligibility({name: factor_values[name] for name in active})
    score = None
    for name, w in active.items():
        ranked = cross_sectional_rank(masked[name]) * (w / total)
        score = ranked if score is None else score + ranked
    return score


def common_eligibility(factor_values: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    """Blank out every symbol-date that lacks any factor, so all ranks share one population."""
    frames = list(factor_values.values())
    if not frames:
        return {}
    mask = frames[0].notna()
    for frame in frames[1:]:
        mask = mask & frame.reindex_like(frames[0]).notna()
    return {name: frame.reindex_like(frames[0]).where(mask) for name, frame in factor_values.items()}

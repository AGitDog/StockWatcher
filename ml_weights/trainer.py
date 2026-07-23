"""Train optimized score weights from historical snapshots and forward returns."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)

WEIGHTS_FILE = Path("ml_weights/optimized_weights.json")
COMPONENT_NAMES = [
    "EPS-Revisionen",
    "Kursziele & Konsens",
    "Preis/Volumen",
    "News-Sentiment",
    "Event-Druck",
    "Insider-Aktivitaet",
    "Relative Staerke",
    "Short Interest",
    "Fundamentale Bewertung",
    "Technische Indikatoren",
]


def _fetch_forward_return(symbol: str, start_date: datetime, days: int = 30) -> float | None:
    """Fetch forward return for a symbol from start_date."""
    try:
        end_date = start_date + timedelta(days=days + 10)
        ticker = yf.Ticker(symbol)
        hist = ticker.history(
            start=start_date.strftime("%Y-%m-%d"),
            end=end_date.strftime("%Y-%m-%d"),
            auto_adjust=True,
        )
        if hist.empty or len(hist) < 2:
            return None

        start_price = float(hist["Close"].iloc[0])
        target_date = start_date + timedelta(days=days)
        tz = hist.index.tz
        if tz:
            target_ts = pd.Timestamp(target_date).tz_localize(tz)
        else:
            target_ts = pd.Timestamp(target_date)

        idx = hist.index.get_indexer([target_ts], method="nearest")[0]
        if idx == -1:
            return None
        end_price = float(hist["Close"].iloc[idx])
        return (end_price / start_price - 1.0) * 100.0
    except Exception as e:
        logger.debug(f"Konnte Forward-Rendite für {symbol} nicht laden: {e}")
        return None


def _extract_component_scores(item: dict[str, Any]) -> dict[str, float]:
    """Extract component scores from a signal item."""
    breakdown = item.get("signal_breakdown", {}) or {}
    scores: dict[str, float] = {}
    for name in COMPONENT_NAMES:
        comp = breakdown.get(name, {}) or {}
        scores[name] = float(comp.get("score", 0) or 0)
    return scores


def build_training_data(
    snapshots: list[tuple[datetime, list[dict[str, Any]]]],
    forward_days: int = 30,
    min_snapshots: int = 5,
) -> pd.DataFrame:
    """Build a DataFrame of component scores and forward returns."""
    if len(snapshots) < min_snapshots:
        logger.warning("Nicht genug Snapshots für ML-Training.")
        return pd.DataFrame()

    rows: list[dict[str, Any]] = []
    for snapshot_date, items in snapshots:
        for item in items:
            symbol = item.get("symbol")
            if not symbol:
                continue
            fwd = _fetch_forward_return(symbol, snapshot_date, days=forward_days)
            if fwd is None:
                continue
            scores = _extract_component_scores(item)
            row = {"symbol": symbol, "snapshot_date": snapshot_date, "forward_return": fwd}
            row.update(scores)
            rows.append(row)

    if not rows:
        return pd.DataFrame()

    return pd.DataFrame(rows)


class ScoreWeightTrainer:
    """Train and apply optimized score weights."""

    def __init__(self, component_names: list[str] | None = None) -> None:
        self.component_names = component_names or COMPONENT_NAMES
        self.weights: dict[str, float] = {name: 1.0 for name in self.component_names}
        self.intercept: float = 0.0
        self.performance: dict[str, float] = {}

    def fit(self, df: pd.DataFrame) -> dict[str, float]:
        """Fit weights using linear regression with non-negative coefficients."""
        if df.empty or "forward_return" not in df.columns:
            return self.weights

        X = df[self.component_names].fillna(0).values
        y = df["forward_return"].values

        # Add small ridge penalty for stability
        ridge_lambda = 0.1
        XtX = X.T @ X + ridge_lambda * np.eye(X.shape[1])
        Xty = X.T @ y
        try:
            coef = np.linalg.solve(XtX, Xty)
        except np.linalg.LinAlgError:
            coef = np.linalg.lstsq(X, y, rcond=None)[0]

        # Enforce non-negative weights (shorting signals is not the goal here)
        coef = np.maximum(coef, 0)

        # Normalize so max weight is 1.0 for interpretability
        max_weight = float(np.max(coef)) if np.max(coef) > 0 else 1.0
        normalized = coef / max_weight

        self.weights = {name: float(normalized[i]) for i, name in enumerate(self.component_names)}
        self.intercept = 0.0

        # Evaluate: correlation of weighted score with forward return
        weighted_score = df[self.component_names].fillna(0).values @ normalized
        self.performance["correlation"] = float(np.corrcoef(weighted_score, y)[0, 1]) if len(y) > 1 else 0.0
        self.performance["mean_forward_return_top_quintile"] = float(
            df.loc[weighted_score >= np.percentile(weighted_score, 80), "forward_return"].mean()
        ) if len(y) > 0 else 0.0

        logger.info("Gewichtung trainiert: %s", self.weights)
        return self.weights

    def predict_score(self, item: dict[str, Any]) -> float:
        """Apply trained weights to a signal item."""
        scores = _extract_component_scores(item)
        weighted = sum(scores[name] * self.weights.get(name, 1.0) for name in self.component_names)
        return weighted + self.intercept

    def save(self, path: Path = WEIGHTS_FILE) -> None:
        """Save weights to JSON."""
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "weights": self.weights,
            "intercept": self.intercept,
            "performance": self.performance,
            "trained_at": datetime.utcnow().isoformat(),
        }
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def load(self, path: Path = WEIGHTS_FILE) -> bool:
        """Load weights from JSON."""
        if not path.exists():
            return False
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            self.weights = data.get("weights", self.weights)
            self.intercept = data.get("intercept", 0.0)
            self.performance = data.get("performance", {})
            return True
        except Exception as e:
            logger.warning(f"Konnte Gewichte nicht laden: {e}")
            return False


def train_on_snapshots(
    snapshots: list[tuple[datetime, list[dict[str, Any]]]],
    forward_days: int = 30,
    save_path: Path = WEIGHTS_FILE,
) -> ScoreWeightTrainer:
    """Train weights from snapshots and save them."""
    trainer = ScoreWeightTrainer()
    df = build_training_data(snapshots, forward_days=forward_days)
    if df.empty:
        logger.warning("Keine Trainingsdaten verfügbar.")
        return trainer
    trainer.fit(df)
    trainer.save(save_path)
    return trainer


def load_trained_weights(path: Path = WEIGHTS_FILE) -> ScoreWeightTrainer:
    """Load previously trained weights."""
    trainer = ScoreWeightTrainer()
    trainer.load(path)
    return trainer

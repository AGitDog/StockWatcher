"""Tests for ML weight trainer."""

from datetime import datetime
from unittest.mock import patch, MagicMock

import pandas as pd
import pytest

from ml_weights.trainer import (
    ScoreWeightTrainer,
    build_training_data,
    _extract_component_scores,
    COMPONENT_NAMES,
)


def test_extract_component_scores():
    item = {
        "symbol": "AAPL",
        "signal_breakdown": {
            "EPS-Revisionen": {"score": 5},
            "Kursziele & Konsens": {"score": 8},
        },
    }
    scores = _extract_component_scores(item)
    assert scores["EPS-Revisionen"] == 5.0
    assert scores["Kursziele & Konsens"] == 8.0
    assert scores["Preis/Volumen"] == 0.0


def test_trainer_fit_non_negative_weights():
    trainer = ScoreWeightTrainer()
    df = pd.DataFrame({
        "EPS-Revisionen": [5, 0, 10, 2],
        "Kursziele & Konsens": [8, 2, 5, 0],
        "Preis/Volumen": [3, 1, 8, 0],
        "News-Sentiment": [2, -1, 4, 0],
        "Event-Druck": [1, 0, 3, 0],
        "Insider-Aktivitaet": [0, 0, 6, 0],
        "Relative Staerke": [4, 1, 7, 0],
        "Short Interest": [0, 0, 5, 0],
        "Fundamentale Bewertung": [2, 0, 4, 0],
        "Technische Indikatoren": [3, 0, 6, 0],
        "forward_return": [10.0, -2.0, 15.0, 0.0],
    })
    weights = trainer.fit(df)
    assert all(w >= 0 for w in weights.values())
    assert max(weights.values()) == 1.0


def test_trainer_predict_score():
    trainer = ScoreWeightTrainer()
    trainer.weights = {name: 1.0 for name in COMPONENT_NAMES}
    item = {
        "symbol": "AAPL",
        "signal_breakdown": {name: {"score": i} for i, name in enumerate(COMPONENT_NAMES)},
    }
    score = trainer.predict_score(item)
    expected = sum(range(len(COMPONENT_NAMES)))
    assert score == pytest.approx(expected)


@patch("ml_weights.trainer._fetch_forward_return")
def test_build_training_data(mock_fetch):
    mock_fetch.return_value = 5.0
    snapshots = [
        (datetime(2024, 1, 1), [
            {"symbol": "AAPL", "signal_breakdown": {name: {"score": 1} for name in COMPONENT_NAMES}},
        ]),
        (datetime(2024, 2, 1), [
            {"symbol": "AAPL", "signal_breakdown": {name: {"score": 2} for name in COMPONENT_NAMES}},
        ]),
        (datetime(2024, 3, 1), [
            {"symbol": "AAPL", "signal_breakdown": {name: {"score": 3} for name in COMPONENT_NAMES}},
        ]),
        (datetime(2024, 4, 1), [
            {"symbol": "AAPL", "signal_breakdown": {name: {"score": 4} for name in COMPONENT_NAMES}},
        ]),
        (datetime(2024, 5, 1), [
            {"symbol": "AAPL", "signal_breakdown": {name: {"score": 5} for name in COMPONENT_NAMES}},
        ]),
    ]
    df = build_training_data(snapshots, forward_days=30)
    assert not df.empty
    assert "forward_return" in df.columns
    assert "AAPL" in df["symbol"].values


def test_trainer_save_and_load(tmp_path):
    trainer = ScoreWeightTrainer()
    trainer.weights = {name: 0.5 for name in COMPONENT_NAMES}
    path = tmp_path / "weights.json"
    trainer.save(path)

    loaded = ScoreWeightTrainer()
    assert loaded.load(path)
    assert loaded.weights == trainer.weights


# --- Out-of-sample guard ---

from ml_weights.trainer import validate_out_of_sample, train_on_snapshots  # noqa: E402


def _synthetic_training_frame(n_dates: int, signal_component: str, seed: int = 0) -> pd.DataFrame:
    """Forward returns driven by one component plus noise; other components are pure noise."""
    import numpy as np

    rng = np.random.default_rng(seed)
    rows = []
    dates = pd.date_range("2024-01-01", periods=n_dates, freq="D")
    for date in dates:
        for i in range(20):
            row = {name: float(rng.integers(-5, 6)) for name in COMPONENT_NAMES}
            row["forward_return"] = 2.0 * row[signal_component] + rng.normal(0, 1)
            row["symbol"] = f"S{i}"
            row["snapshot_date"] = date
            rows.append(row)
    return pd.DataFrame(rows)


def test_validate_out_of_sample_rejects_too_few_dates():
    df = _synthetic_training_frame(15, "EPS-Revisionen")
    result = validate_out_of_sample(df, forward_days=30)
    assert result["validated"] is False
    assert result["n_dates"] == 15
    assert "mindestens" in result["reason"]


def test_validate_out_of_sample_accepts_real_signal():
    df = _synthetic_training_frame(200, "EPS-Revisionen")
    result = validate_out_of_sample(df, forward_days=30)
    assert result["validated"] is True
    assert result["oos_ic_trained"] > result["oos_ic_equal"]


def test_validate_out_of_sample_embargo_separates_train_and_test():
    df = _synthetic_training_frame(200, "EPS-Revisionen")
    result = validate_out_of_sample(df, forward_days=30)
    # 200 dates, 140 for training, 30 days embargo -> 30 test dates remain.
    assert result["oos_ic_trained"] is not None


def test_unvalidated_trainer_uses_equal_weights():
    trainer = ScoreWeightTrainer()
    trainer.weights = {name: 0.0 for name in COMPONENT_NAMES}
    trainer.weights["EPS-Revisionen"] = 1.0
    item = {"signal_breakdown": {name: {"score": 2} for name in COMPONENT_NAMES}}
    assert trainer.validated is False
    assert trainer.predict_score(item) == pytest.approx(2 * len(COMPONENT_NAMES))
    trainer.validated = True
    assert trainer.predict_score(item) == pytest.approx(2)


def test_legacy_weights_file_is_not_validated(tmp_path):
    import json

    path = tmp_path / "weights.json"
    path.write_text(json.dumps({"weights": {name: 0.1 for name in COMPONENT_NAMES}}), encoding="utf-8")
    trainer = ScoreWeightTrainer()
    assert trainer.load(path)
    assert trainer.validated is False


def test_validated_flag_round_trips(tmp_path):
    trainer = ScoreWeightTrainer()
    trainer.validated = True
    path = tmp_path / "weights.json"
    trainer.save(path)
    loaded = ScoreWeightTrainer()
    loaded.load(path)
    assert loaded.validated is True


@patch("ml_weights.trainer.build_training_data")
def test_train_on_snapshots_records_oos_result(mock_build, tmp_path):
    mock_build.return_value = _synthetic_training_frame(15, "EPS-Revisionen")
    trainer = train_on_snapshots([], forward_days=30, save_path=tmp_path / "w.json")
    assert trainer.validated is False
    assert trainer.performance["oos_n_dates"] == 15
    assert trainer.performance["oos_validated"] is False


def test_validate_out_of_sample_counts_calendar_days():
    df = _synthetic_training_frame(10, "EPS-Revisionen")
    later = df.copy()
    later["snapshot_date"] = later["snapshot_date"] + pd.Timedelta(hours=6)
    result = validate_out_of_sample(pd.concat([df, later]), forward_days=30)
    assert result["n_dates"] == 10

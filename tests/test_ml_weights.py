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

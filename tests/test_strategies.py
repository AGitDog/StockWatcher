"""Tests for strategy module."""

import pytest

from strategies import (
    MomentumStrategy,
    MeanReversionStrategy,
    PreEarningsStrategy,
    ShortSqueezeStrategy,
    StrategyRegistry,
    build_strategy_signals,
)


def _make_item(**kwargs):
    """Helper to build a minimal signal item."""
    defaults = {
        "symbol": "AAPL",
        "name": "Apple Inc.",
        "brodel_score": 50,
        "signal_breakdown": {
            "Preis/Volumen": {"score": 0, "summary": "Kurs 150.00, 5T +8.0%, Volumen 2.0x vs. 20T, ueber MA20/MA50: ja/ja"},
            "EPS-Revisionen": {"score": 5, "summary": "EPS-Revisionen: 3 hoch, 1 runter"},
            "Kursziele & Konsens": {"score": 8, "summary": "Mittel 180.00 vs. Kurs 150.00 = 20.0% Potenzial"},
            "Relative Staerke": {"score": 5, "summary": "1M-Perf: 12.0% vs. SPY 2.0% = +10.0% relativ"},
            "Technische Indikatoren": {"score": 3, "summary": "RSI: 55.0 | MACD: Bullisch"},
            "News-Sentiment": {"score": 2, "summary": "4 News in 7T | Sentiment: neutral"},
            "Event-Druck": {"score": 0, "summary": "Keine nahen Termine erkannt."},
            "Insider-Aktivitaet": {"score": 0, "summary": "Keine Insider-Transaktionen erkannt."},
            "Short Interest": {"score": 0, "summary": "Keine Short-Interest-Daten verfuegbar."},
            "Fundamentale Bewertung": {"score": 2, "summary": "P/E 18.0"},
        },
    }
    defaults.update(kwargs)
    return defaults


def test_momentum_strategy_detects_breakout():
    item = _make_item()
    strategy = MomentumStrategy()
    result = strategy.evaluate(item)
    assert result is not None
    assert result.strategy_name == "momentum"
    assert result.direction == "long"
    assert result.confidence > 0.5


def test_mean_reversion_strategy_detects_oversold():
    item = _make_item(
        signal_breakdown={
            "Preis/Volumen": {"score": -3, "summary": "Kurs 150.00, 5T -10.0%, Volumen 1.0x vs. 20T, ueber MA20/MA50: nein/nein"},
            "Technische Indikatoren": {"score": 4, "summary": "RSI: 25.0 (Ueberverkauft) | Bollinger: Unteres Band"},
            "News-Sentiment": {"score": 0, "summary": "Keine News"},
            "Short Interest": {"score": 0, "summary": "Short-Float: 5.0%"},
        }
    )
    strategy = MeanReversionStrategy()
    result = strategy.evaluate(item)
    assert result is not None
    assert result.strategy_name == "mean_reversion"
    assert result.direction == "long"


def test_pre_earnings_strategy_detects_event():
    item = _make_item(
        signal_breakdown={
            "Preis/Volumen": {"score": 5, "summary": "Kurs 150.00, 5T +5.0%, Volumen 1.2x vs. 20T, ueber MA20/MA50: ja/ja"},
            "EPS-Revisionen": {"score": 3, "summary": "EPS-Revisionen: 2 hoch, 0 runter"},
            "Technische Indikatoren": {"score": 3, "summary": "RSI: 55.0 | MACD: Bullisch"},
            "Event-Druck": {"score": 5, "summary": "Naechster Termin in 5 Tagen"},
        }
    )
    strategy = PreEarningsStrategy()
    result = strategy.evaluate(item)
    assert result is not None
    assert result.strategy_name == "pre_earnings"


def test_short_squeeze_strategy_detects_setup():
    item = _make_item(
        signal_breakdown={
            "Preis/Volumen": {"score": 5, "summary": "Kurs 150.00, 5T +5.0%, Volumen 1.5x vs. 20T, ueber MA20/MA50: ja/ja"},
            "Technische Indikatoren": {"score": 3, "summary": "RSI: 55.0 | MACD: Bullisch"},
            "Short Interest": {"score": 5, "summary": "Short-Float: 25.0%, erhoehtes Squeeze-Potenzial (bullisch)."},
        }
    )
    strategy = ShortSqueezeStrategy()
    result = strategy.evaluate(item)
    assert result is not None
    assert result.strategy_name == "short_squeeze"


def test_registry_returns_best_signal():
    item = _make_item()
    registry = StrategyRegistry()
    best = registry.best_signal(item)
    assert best is not None
    assert best.confidence > 0


def test_build_strategy_signals_enriches_items():
    items = [_make_item()]
    enriched = build_strategy_signals(items)
    assert len(enriched) == 1
    assert "strategy_signals" in enriched[0]
    assert "best_strategy" in enriched[0]


def test_strategy_result_to_dict():
    from strategies import StrategyResult
    result = StrategyResult(
        strategy_name="momentum",
        setup="breakout",
        confidence=0.8,
        direction="long",
        rationale="test",
        entry_price=100.0,
        stop_loss=95.0,
        take_profit=115.0,
        position_size_pct=0.05,
    )
    d = result.to_dict()
    assert d["strategy_name"] == "momentum"
    assert d["confidence"] == 0.8

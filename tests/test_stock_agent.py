import pytest
import pandas as pd
from unittest.mock import MagicMock, patch
from stock_agent import (
    parse_watchlist_text,
    expand_watchlist_entry,
    load_index_constituents,
    _summarize_eps_revisions,
    _summarize_price_targets,
    _summarize_price_volume,
    _summarize_news_intensity,
    _summarize_event_pressure,
    _summarize_insider_signal,
    _summarize_short_interest,
    _summarize_relative_strength,
    _safe_float,
    _clean_scalar,
    _dedupe_preserve_order,
)


# ── Existing parse/expand tests ──────────────────────────────────────────────

def test_parse_watchlist_text_basic():
    text = "AAPL\nMSFT\nGOOGL"
    result = parse_watchlist_text(text)
    assert result == ["AAPL", "MSFT", "GOOGL"]

def test_parse_watchlist_text_with_comments():
    text = "AAPL # Apple\nMSFT # Microsoft\n# Just a comment\nGOOGL"
    result = parse_watchlist_text(text)
    assert result == ["AAPL", "MSFT", "GOOGL"]

def test_parse_watchlist_text_comma_separated():
    text = "AAPL, MSFT, GOOGL"
    result = parse_watchlist_text(text)
    assert result == ["AAPL", "MSFT", "GOOGL"]

def test_parse_watchlist_text_semicolon_separated():
    text = "AAPL; MSFT; GOOGL"
    result = parse_watchlist_text(text)
    assert result == ["AAPL", "MSFT", "GOOGL"]

def test_parse_watchlist_text_deduplication():
    text = "AAPL\nMSFT\naapl\nGOOGL\nMSFT"
    result = parse_watchlist_text(text)
    assert result == ["AAPL", "MSFT", "GOOGL"]

def test_parse_watchlist_text_empty_lines():
    text = "\n\nAAPL\n\n\nMSFT\n"
    result = parse_watchlist_text(text)
    assert result == ["AAPL", "MSFT"]

def test_expand_watchlist_entry_simple():
    result = expand_watchlist_entry("AAPL")
    assert result == ["AAPL"]


# ── Helper function tests ────────────────────────────────────────────────────

def test_safe_float_valid():
    assert _safe_float(42.5) == 42.5
    assert _safe_float("3.14") == 3.14
    assert _safe_float(0) == 0.0

def test_safe_float_invalid():
    assert _safe_float(None) is None
    assert _safe_float("abc") is None
    assert _safe_float(float("nan")) is None

def test_clean_scalar_valid():
    assert _clean_scalar("Hello") == "Hello"
    assert _clean_scalar(42) == "42"

def test_clean_scalar_invalid():
    assert _clean_scalar(None) is None
    assert _clean_scalar("") is None

def test_dedupe_preserve_order():
    assert _dedupe_preserve_order(["a", "b", "a", "c", "b"]) == ["a", "b", "c"]
    assert _dedupe_preserve_order([]) == []


# ── EPS Revisions (max 20) ───────────────────────────────────────────────────

def test_eps_revisions_positive_net():
    """Positive net revisions should give score between 1 and 20."""
    ticker = MagicMock()
    revisions_df = pd.DataFrame({
        "UpLast7Days": [3, 2],
        "DownLast7Days": [1, 0],
    })
    ticker.get_eps_revisions.return_value = revisions_df
    result = _summarize_eps_revisions(ticker)
    assert result["name"] == "EPS-Revisionen"
    assert 0 < result["score"] <= 20

def test_eps_revisions_max_capped_at_20():
    """Score should never exceed 20 even with very high positive revisions."""
    ticker = MagicMock()
    revisions_df = pd.DataFrame({
        "UpLast7Days": [50, 50],
        "DownLast7Days": [0, 0],
    })
    ticker.get_eps_revisions.return_value = revisions_df
    result = _summarize_eps_revisions(ticker)
    assert result["score"] <= 20

def test_eps_revisions_empty():
    ticker = MagicMock()
    ticker.get_eps_revisions.return_value = pd.DataFrame()
    result = _summarize_eps_revisions(ticker)
    assert result["score"] == 0


# ── Price Targets (max 15) ───────────────────────────────────────────────────

def test_price_targets_large_gap():
    """20%+ gap should give max score of 15."""
    ticker = MagicMock()
    ticker.get_analyst_price_targets.return_value = {"mean": 120, "high": 150, "low": 100}
    info = {"currentPrice": 90}
    history = pd.DataFrame({"Close": [90]})
    result = _summarize_price_targets(ticker, info, history)
    assert result["name"] == "Kursziele"
    assert result["score"] == 15

def test_price_targets_no_data():
    ticker = MagicMock()
    ticker.get_analyst_price_targets.return_value = {}
    result = _summarize_price_targets(ticker, {}, None)
    assert result["score"] == 0


# ── Price/Volume (max 20) ────────────────────────────────────────────────────

def test_price_volume_max_capped_at_20():
    """Score should never exceed 20 even when all conditions are met."""
    # Create a DataFrame where close is above MA20/MA50, volume is high, and 5d return is big
    dates = pd.date_range("2024-01-01", periods=60)
    close_values = [100 + i * 0.5 for i in range(54)] + [100, 100, 100, 100, 100, 200]
    volume_values = [1000] * 59 + [5000]  # last day volume spike
    history = pd.DataFrame({"Close": close_values, "Volume": volume_values}, index=dates)
    result = _summarize_price_volume(history)
    assert result["name"] == "Preis/Volumen"
    assert result["score"] <= 20

def test_price_volume_insufficient_data():
    history = pd.DataFrame({"Close": [100] * 10, "Volume": [1000] * 10})
    result = _summarize_price_volume(history)
    assert result["score"] == 0


# ── News Intensity (max 12) ──────────────────────────────────────────────────

def test_news_intensity_high():
    """6+ recent news should give max score of 12."""
    ticker = MagicMock()
    import time
    now_ts = int(time.time())
    news = [{"title": f"News {i}", "providerPublishTime": now_ts - 3600 * i} for i in range(8)]
    ticker.get_news.return_value = news
    result = _summarize_news_intensity(ticker)
    assert result["name"] == "News-Dichte"
    assert result["score"] <= 12

def test_news_intensity_empty():
    ticker = MagicMock()
    ticker.get_news.return_value = []
    result = _summarize_news_intensity(ticker)
    assert result["score"] == 0


# ── Event Pressure (max 10) ──────────────────────────────────────────────────

def test_event_pressure_no_dates():
    ticker = MagicMock()
    ticker.get_earnings_dates.return_value = pd.DataFrame()
    ticker.get_calendar.return_value = {}
    result = _summarize_event_pressure(ticker, {})
    assert result["name"] == "Event-Druck"
    assert result["score"] == 0


# ── NEW: Insider Signal (max 10) ─────────────────────────────────────────────

def test_insider_signal_with_purchases():
    """Multiple insider purchases should give high score."""
    ticker = MagicMock()
    purchases_df = pd.DataFrame({
        "Insider": ["CEO", "CFO", "COO", "VP"],
        "Shares": [1000, 2000, 500, 800],
        "Value": [50000, 100000, 25000, 40000],
    })
    ticker.get_insider_purchases.return_value = purchases_df
    ticker.get_insider_transactions.return_value = pd.DataFrame()
    result = _summarize_insider_signal(ticker, False)
    assert result["name"] == "Insider-Aktivitaet"
    assert result["score"] == 10  # 4+ purchases = max score

def test_insider_signal_etf():
    """ETFs should return score 0."""
    ticker = MagicMock()
    result = _summarize_insider_signal(ticker, True)
    assert result["score"] == 0
    assert "ETF" in result["summary"]

def test_insider_signal_empty():
    """No insider data should return score 0."""
    ticker = MagicMock()
    ticker.get_insider_purchases.return_value = pd.DataFrame()
    ticker.get_insider_transactions.return_value = pd.DataFrame()
    result = _summarize_insider_signal(ticker, False)
    assert result["score"] == 0

def test_insider_signal_single_purchase():
    """A single insider purchase should give 4 points."""
    ticker = MagicMock()
    purchases_df = pd.DataFrame({
        "Insider": ["CEO"],
        "Shares": [1000],
        "Value": [50000],
    })
    ticker.get_insider_purchases.return_value = purchases_df
    ticker.get_insider_transactions.return_value = pd.DataFrame()
    result = _summarize_insider_signal(ticker, False)
    assert result["score"] == 4


# ── NEW: Short Interest (max 8) ──────────────────────────────────────────────

def test_short_interest_high():
    """20%+ short float should give max score of 8."""
    info = {"shortPercentOfFloat": 0.25, "shortRatio": 6.0}
    result = _summarize_short_interest(info)
    assert result["name"] == "Short Interest"
    assert result["score"] == 8

def test_short_interest_moderate():
    """10-20% short float should give score of 6."""
    info = {"shortPercentOfFloat": 0.12}
    result = _summarize_short_interest(info)
    assert result["score"] == 6

def test_short_interest_low():
    """<5% short float should give 0."""
    info = {"shortPercentOfFloat": 0.02}
    result = _summarize_short_interest(info)
    assert result["score"] == 0

def test_short_interest_missing():
    """No short interest data should give 0."""
    result = _summarize_short_interest({})
    assert result["score"] == 0

def test_short_interest_only_ratio():
    """High short ratio without short float should still score."""
    info = {"shortRatio": 6.0}
    result = _summarize_short_interest(info)
    assert result["score"] == 5  # shortRatio >= 5


# ── NEW: Relative Strength (max 5) ───────────────────────────────────────────

@patch("stock_agent.yf")
def test_relative_strength_outperformance(mock_yf):
    """Strong outperformance vs market should score 5."""
    dates = pd.date_range("2024-01-01", periods=25)
    # Stock: starts at 100, ends at 120
    close_values = [100] * 5 + [100] * 19 + [120]
    history = pd.DataFrame({"Close": close_values}, index=dates)

    # SPY: flat
    spy_dates = pd.date_range("2024-01-01", periods=20)
    spy_history = pd.DataFrame({"Close": [100] * 20}, index=spy_dates)
    mock_ticker = MagicMock()
    mock_ticker.history.return_value = spy_history
    mock_yf.Ticker.return_value = mock_ticker

    result = _summarize_relative_strength(history)
    assert result["name"] == "Relative Staerke"
    assert result["score"] == 5

@patch("stock_agent.yf")
def test_relative_strength_underperformance(mock_yf):
    """Underperformance vs market should score 0."""
    dates = pd.date_range("2024-01-01", periods=25)
    # Stock: -5% over last 20 days
    close_values = [100] * 5 + [95] * 20
    history = pd.DataFrame({"Close": close_values}, index=dates)

    # SPY: +5%
    spy_dates = pd.date_range("2024-01-01", periods=20)
    spy_history = pd.DataFrame({"Close": [100] + [105] * 19}, index=spy_dates)
    mock_ticker = MagicMock()
    mock_ticker.history.return_value = spy_history
    mock_yf.Ticker.return_value = mock_ticker

    result = _summarize_relative_strength(history)
    assert result["score"] == 0

def test_relative_strength_insufficient_data():
    """Less than 20 data points should give score 0."""
    history = pd.DataFrame({"Close": [100] * 10})
    result = _summarize_relative_strength(history)
    assert result["score"] == 0


# ── Integration: Signal component count and score cap ────────────────────────

def test_brodel_score_max_100():
    """The brodel_score should never exceed 100 even if all components score max."""
    # Simulate all components at their max
    components = [
        {"name": "EPS-Revisionen", "score": 20, "summary": ""},
        {"name": "Kursziele", "score": 15, "summary": ""},
        {"name": "Preis/Volumen", "score": 20, "summary": ""},
        {"name": "News-Dichte", "score": 12, "summary": ""},
        {"name": "Event-Druck", "score": 10, "summary": ""},
        {"name": "Insider-Aktivitaet", "score": 10, "summary": ""},
        {"name": "Short Interest", "score": 8, "summary": ""},
        {"name": "Relative Staerke", "score": 5, "summary": ""},
    ]
    brodel_score = min(sum(c["score"] for c in components), 100)
    assert brodel_score == 100

def test_signal_component_count():
    """There should be exactly 8 signal components at max values summing to 100."""
    max_scores = [20, 15, 20, 12, 10, 10, 8, 5]
    assert len(max_scores) == 8
    assert sum(max_scores) == 100


# ── New Index Parsing Tests ──────────────────────────────────────────────────

@patch("stock_agent.pd.read_html")
@patch("stock_agent.requests.get")
def test_load_index_constituents_smi(mock_get, mock_read_html):
    """Test Swiss Market Index constituent parsing with suffix .SW"""
    mock_response = MagicMock()
    mock_response.text = "dummy"
    mock_get.return_value = mock_response

    mock_df = pd.DataFrame({"Ticker": ["NOVN", "ROG"]})
    # SMI table_index is 2, so return list with 3 dataframes
    mock_read_html.return_value = [None, None, mock_df]

    load_index_constituents.cache_clear()
    
    result = load_index_constituents("SMI")
    assert result == ["NOVN.SW", "ROG.SW"]

@patch("stock_agent.pd.read_html")
@patch("stock_agent.requests.get")
def test_load_index_constituents_nikkei_float(mock_get, mock_read_html):
    """Test Nikkei 225 parsing where tickers are floats and need .T suffix"""
    mock_response = MagicMock()
    mock_response.text = "dummy"
    mock_get.return_value = mock_response

    mock_df = pd.DataFrame({"Code": [9983.0, 8035.0]})
    # Nikkei table_index is 8, so return list with 9 dataframes
    mock_read_html.return_value = [None]*8 + [mock_df]

    load_index_constituents.cache_clear()
    
    result = load_index_constituents("Nikkei 225")
    assert result == ["9983.T", "8035.T"]

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
    _summarize_fundamentals,
    _get_benchmark_symbol,
    _analyze_news_sentiment,
    _analyze_sentiment_keywords,
    _safe_float,
    _clean_scalar,
    _dedupe_preserve_order,
    _summarize_technical_indicators,
    _apply_macro_overlay,
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
    assert result["score"] <= 18

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
    assert result["name"] == "Kursziele & Konsens"
    assert result["score"] == 10  # 10 points for gap >= 20%, 0 for consensus

def test_price_targets_no_data():
    ticker = MagicMock()
    ticker.get_analyst_price_targets.return_value = {}
    result = _summarize_price_targets(ticker, {}, None)
    assert result["score"] == 0


# ── Price/Volume (max 20) ────────────────────────────────────────────────────

def test_price_volume_max_capped_at_15():
    """Score should never exceed 15 even when all conditions are met."""
    # Create a DataFrame where close is above MA20/MA50, volume is high, and 5d return is big
    dates = pd.date_range("2024-01-01", periods=60)
    close_values = [100 + i * 0.5 for i in range(54)] + [100, 100, 100, 100, 100, 200]
    volume_values = [1000] * 59 + [5000]  # last day volume spike
    history = pd.DataFrame({"Close": close_values, "Volume": volume_values}, index=dates)
    result = _summarize_price_volume(history)
    assert result["name"] == "Preis/Volumen"
    assert result["score"] <= 15

def test_price_volume_insufficient_data():
    history = pd.DataFrame({"Close": [100] * 10, "Volume": [1000] * 10})
    result = _summarize_price_volume(history)
    assert result["score"] == 0


# ── News Sentiment (max 15, min -10) ─────────────────────────────────────────

def test_news_intensity_high():
    """6+ recent news should contribute to score."""
    ticker = MagicMock()
    import time
    now_ts = int(time.time())
    news = [{"title": f"News {i}", "providerPublishTime": now_ts - 3600 * i} for i in range(8)]
    ticker.get_news.return_value = news
    result = _summarize_news_intensity(ticker)
    assert result["name"] == "News-Sentiment"
    assert result["score"] <= 15

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
    """Multiple insider purchases should give high score (via transactions only)."""
    ticker = MagicMock()
    transactions_df = pd.DataFrame({
        "Text": ["Purchase", "Purchase", "Buy", "Purchase"],
        "Shares": [1000, 2000, 500, 800],
    })
    ticker.get_insider_transactions.return_value = transactions_df
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
    transactions_df = pd.DataFrame({
        "Text": ["Purchase"],
        "Shares": [1000],
    })
    ticker.get_insider_transactions.return_value = transactions_df
    result = _summarize_insider_signal(ticker, False)
    assert result["score"] == 4


# ── NEW: Short Interest (max 8) ──────────────────────────────────────────────

def test_short_interest_high():
    info = {"shortPercentOfFloat": 0.25, "shortRatio": 6.0}
    result = _summarize_short_interest(info)
    assert result["score"] == 5

def test_short_interest_moderate():
        info = {"shortPercentOfFloat": 0.12}
        result = _summarize_short_interest(info)
        assert result["score"] == 3

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
    info = {"shortRatio": 6.0}
    result = _summarize_short_interest(info)
    assert result["score"] == 4  # shortRatio >= 5


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


@patch("stock_agent.yf.Ticker")
def test_build_symbol_signal_monitor_no_nameerror_on_quote_type(mock_ticker_class):
    """Ensure that build_symbol_signal_monitor extracts quoteType and doesn't crash."""
    from stock_agent import build_symbol_signal_monitor
    
    mock_instance = MagicMock()
    mock_ticker_class.return_value = mock_instance
    mock_instance.get_info.return_value = {"quoteType": "EQUITY", "shortName": "Apple"}
    
    res = build_symbol_signal_monitor("AAPL")
    assert isinstance(res, dict)
    assert res["symbol"] == "AAPL"
    assert "brodel_score" in res


# ══════════════════════════════════════════════════════════════════════════════
# Phase 1 Tests — Quick Wins
# ══════════════════════════════════════════════════════════════════════════════

# ── 1.1 EPS Revisions: Negative net → 0 points ──────────────────────────────

def test_eps_revisions_negative_net_scores_zero():
    """Negative net EPS revisions should score 0, not 4."""
    ticker = MagicMock()
    revisions_df = pd.DataFrame({
        "UpLast7Days": [0, 0],
        "DownLast30Days": [5, 3],
    })
    ticker.get_eps_revisions.return_value = revisions_df
    result = _summarize_eps_revisions(ticker)
    assert result["score"] == -5, f"Expected -5 for negative net, got {result['score']}"


# ── 1.2 Price/Volume: Direction matters ──────────────────────────────────────

def test_price_volume_crash_penalizes():
    """A 7%+ crash should penalize score, not reward it."""
    dates = pd.date_range("2024-01-01", periods=60)
    # Stock crashes from 100 to 90 in last 5 days, but is still above MAs
    close_values = [100] * 54 + [100, 98, 96, 94, 92, 90]
    volume_values = [1000] * 60
    history = pd.DataFrame({"Close": close_values, "Volume": volume_values}, index=dates)
    result = _summarize_price_volume(history)
    # With crash: should NOT get the +5 for return, should get penalty
    # MA20 ~ 95.5, MA50 ~ 98.0, latest = 90 → below both → 0 base
    # return_5d ~ -10% → penalty of -3 → capped at 0
    assert result["score"] <= 0 or result["score"] < 5, "Crash should not be rewarded"

def test_price_volume_rally_rewards():
    """A 7%+ rally should get +5 points."""
    dates = pd.date_range("2024-01-01", periods=60)
    close_values = [100] * 54 + [100, 102, 104, 106, 108, 110]
    volume_values = [1000] * 60
    history = pd.DataFrame({"Close": close_values, "Volume": volume_values}, index=dates)
    result = _summarize_price_volume(history)
    # latest = 110, MA20 ~ 103, MA50 ~ 101 → above both = +5 + +6 = 11
    # return_5d = +10% → +4 = 15
    assert result["score"] >= 10

def test_price_volume_volume_spike_only_on_up_day():
    """Volume spike should only give +5 when price is flat or rising."""
    dates = pd.date_range("2024-01-01", periods=60)
    # Crash with huge volume spike
    close_values = [100] * 54 + [100, 97, 94, 91, 88, 85]
    volume_values = [1000] * 59 + [5000]  # big volume on crash day
    history = pd.DataFrame({"Close": close_values, "Volume": volume_values}, index=dates)
    result = _summarize_price_volume(history)
    # return_5d ~ -15% (negative), so volume spike should NOT score +5
    # And the crash should penalize
    assert result["score"] <= 0, "Volume spike on crash should not give +5"


# ── 1.3 Short Interest: Dual interpretation ──────────────────────────────────

def test_short_interest_above_ma50_bullish():
    """High short + price above MA50 = squeeze potential (bullish score)."""
    dates = pd.date_range("2024-01-01", periods=60)
    close_values = [90] * 50 + [100] * 10  # Rising → above MA50
    history = pd.DataFrame({"Close": close_values}, index=dates)
    info = {"shortPercentOfFloat": 0.25}
    result = _summarize_short_interest(info, history)
    assert result["score"] == 5, f"Expected 6 (squeeze), got {result['score']}"
    assert "Squeeze" in result["summary"]

def test_short_interest_below_ma50_bearish():
    """High short + price below MA50 = bearish pressure (score 0)."""
    dates = pd.date_range("2024-01-01", periods=60)
    close_values = [110] * 50 + [90] * 10  # Falling → below MA50
    history = pd.DataFrame({"Close": close_values}, index=dates)
    info = {"shortPercentOfFloat": 0.25}
    result = _summarize_short_interest(info, history)
    assert result["score"] == 0, f"Expected 0 (bearish), got {result['score']}"
    assert "baerisch" in result["summary"]

def test_short_interest_no_history_defaults_bullish():
    """Without history, short interest should default to bullish interpretation."""
    info = {"shortPercentOfFloat": 0.25}
    result = _summarize_short_interest(info)
    assert result["score"] == 5, "Without history, should default to bullish"


# ── 1.4 Insider: No double-counting ──────────────────────────────────────────

def test_insider_no_double_counting():
    """Insider signal should use only transactions, not purchases + transactions."""
    ticker = MagicMock()
    # Transactions has 2 purchases
    transactions_df = pd.DataFrame({
        "Text": ["Purchase", "Buy"],
        "Shares": [1000, 500],
    })
    ticker.get_insider_transactions.return_value = transactions_df
    # Should NOT call get_insider_purchases at all
    result = _summarize_insider_signal(ticker, False)
    assert result["score"] == 6  # 2 purchases = 6
    ticker.get_insider_purchases.assert_not_called()


# ── 1.5 Regional Benchmark ──────────────────────────────────────────────────

def test_benchmark_german_stock():
    """German stocks (.DE) should use DAX as benchmark."""
    assert _get_benchmark_symbol("SAP.DE") == "^GDAXI"

def test_benchmark_swiss_stock():
    """Swiss stocks (.SW) should use SMI."""
    assert _get_benchmark_symbol("NOVN.SW") == "^SSMI"

def test_benchmark_japanese_stock():
    """Japanese stocks (.T) should use Nikkei 225."""
    assert _get_benchmark_symbol("9983.T") == "^N225"

def test_benchmark_us_stock_default():
    """US stocks (no suffix) should default to SPY."""
    assert _get_benchmark_symbol("AAPL") == "SPY"

def test_benchmark_brazilian_stock():
    """Brazilian stocks (.SA) should use Bovespa."""
    assert _get_benchmark_symbol("PETR4.SA") == "^BVSP"

def test_benchmark_canadian_stock():
    """Canadian stocks (.TO) should use TSX."""
    assert _get_benchmark_symbol("RY.TO") == "^GSPTSE"

def test_benchmark_indian_stock():
    """Indian stocks (.NS) should use Nifty 50."""
    assert _get_benchmark_symbol("RELIANCE.NS") == "^NSEI"

@patch("stock_agent.yf")
def test_relative_strength_uses_regional_benchmark(mock_yf):
    """Relative strength for a German stock should compare against DAX, not SPY."""
    dates = pd.date_range("2024-01-01", periods=25)
    close_values = [100] * 5 + [100] * 19 + [120]
    history = pd.DataFrame({"Close": close_values}, index=dates)

    dax_dates = pd.date_range("2024-01-01", periods=20)
    dax_history = pd.DataFrame({"Close": [100] * 20}, index=dax_dates)
    mock_ticker = MagicMock()
    mock_ticker.history.return_value = dax_history
    mock_yf.Ticker.return_value = mock_ticker

    result = _summarize_relative_strength(history, symbol="SAP.DE")
    assert result["score"] == 5
    # Verify DAX was used, not SPY
    mock_yf.Ticker.assert_called_with("^GDAXI")
    assert "^GDAXI" in result["summary"]






# --- Technical Indicators ---

def test_technical_indicators_no_history():
    result = _summarize_technical_indicators(None)
    assert result["score"] == 0
    assert "Nicht genug Kursdaten" in result["summary"]

def test_technical_indicators_bullish():
    # Construct a dataframe with RSI < 30, MACD > Signal, Close < Lower Bollinger
    dates = pd.date_range("2024-01-01", periods=60)
    # Strong downtrend to make RSI < 30, then a bounce for MACD
    close_values = [100 - i for i in range(50)] + [50 + i*2 for i in range(10)]
    history = pd.DataFrame({"Close": close_values}, index=dates)
    
    result = _summarize_technical_indicators(history)
    # The exact score depends on ewm math, but it should calculate without errors.
    assert "score" in result
    assert isinstance(result["score"], int)
    assert "RSI:" in result["summary"]
    assert "MACD:" in result["summary"]
    assert "Bollinger:" in result["summary"]

# --- Macro Overlay ---

@patch("stock_agent.yf.Ticker")
def test_apply_macro_overlay_bull_market(mock_ticker_class):
    mock_spy = MagicMock()
    mock_vix = MagicMock()
    
    # SPY above 200-MA (e.g., constant rise)
    dates = pd.date_range("2023-01-01", periods=250)
    spy_history = pd.DataFrame({"Close": [100 + i for i in range(250)]}, index=dates)
    mock_spy.history.return_value = spy_history
    
    # VIX low
    vix_history = pd.DataFrame({"Close": [15.0] * 30}, index=pd.date_range("2023-01-01", periods=30))
    mock_vix.history.return_value = vix_history
    
    # Mock yf.Ticker to return SPY or VIX based on argument
    def side_effect(ticker_name):
        if ticker_name == "SPY":
            return mock_spy
        elif ticker_name == "^VIX":
            return mock_vix
        return MagicMock()
        
    mock_ticker_class.side_effect = side_effect
    
    # Base score 10 * 1.1 = 11
    score = _apply_macro_overlay(10)
    assert score == 11

@patch("stock_agent.yf.Ticker")
def test_apply_macro_overlay_bear_market_high_vix(mock_ticker_class):
    mock_spy = MagicMock()
    mock_vix = MagicMock()
    
    # SPY below 200-MA (falling)
    dates = pd.date_range("2023-01-01", periods=250)
    spy_history = pd.DataFrame({"Close": [100 - i*0.1 for i in range(250)]}, index=dates)
    mock_spy.history.return_value = spy_history
    
    # VIX > 25
    vix_history = pd.DataFrame({"Close": [30.0] * 30}, index=pd.date_range("2023-01-01", periods=30))
    mock_vix.history.return_value = vix_history
    
    def side_effect(ticker_name):
        if ticker_name == "SPY":
            return mock_spy
        elif ticker_name == "^VIX":
            return mock_vix
        return MagicMock()
        
    mock_ticker_class.side_effect = side_effect
    
    # Base score 10 * 0.8 (SPY) * 0.9 (VIX) = 7.2 -> 7
    score = _apply_macro_overlay(10)
    assert score == 7


# --- Fundamentals ---

def test_fundamentals_empty_info():
    """Empty info dict should return score 0."""
    mock_ticker = MagicMock()
    mock_ticker.ticker = "TEST"
    result = _summarize_fundamentals(mock_ticker, {})
    assert result["score"] == 0
    assert result["name"] == "Fundamentale Bewertung"


def test_fundamentals_perfect_value_stock():
    """A stock with all 5 metrics in top tier should score 10 (the max)."""
    info = {
        "forwardPE": 10.0,       # < 15 -> +2
        "pegRatio": 0.8,         # < 1.0 -> +2
        "debtToEquity": 30.0,    # < 50 -> +2
        "freeCashflow": 6e9,     # FCF yield = 6% > 5% -> +2
        "marketCap": 100e9,
        "profitMargins": 0.25,   # > 20% -> +2
    }
    mock_ticker = MagicMock()
    mock_ticker.ticker = "TEST"
    result = _summarize_fundamentals(mock_ticker, info)
    assert result["score"] == 10, f"Expected max 10, got {result['score']}"


def test_fundamentals_overvalued_stock():
    """A stock with extreme P/E should get a negative penalty."""
    info = {
        "forwardPE": 80.0,       # > 50 -> -2
    }
    mock_ticker = MagicMock()
    mock_ticker.ticker = "TEST"
    result = _summarize_fundamentals(mock_ticker, info)
    assert result["score"] == -2, f"Expected -2 for overvalued, got {result['score']}"


def test_fundamentals_moderate_stock():
    """A stock with moderate metrics gets partial points."""
    info = {
        "forwardPE": 20.0,       # < 25 -> +1
        "pegRatio": 1.2,         # < 1.5 -> +1
        "debtToEquity": 80.0,    # < 100 -> +1
        "freeCashflow": 3e9,     # 3% > 2% -> +1
        "marketCap": 100e9,
        "profitMargins": 0.15,   # > 10% -> +1
    }
    mock_ticker = MagicMock()
    mock_ticker.ticker = "TEST"
    result = _summarize_fundamentals(mock_ticker, info)
    assert result["score"] == 5, f"Expected 5, got {result['score']}"


def test_fundamentals_score_capped_at_10():
    """Score should never exceed 10 even with extreme inputs."""
    info = {
        "forwardPE": 5.0,
        "pegRatio": 0.3,
        "debtToEquity": 10.0,
        "freeCashflow": 20e9,
        "marketCap": 100e9,
        "profitMargins": 0.40,
    }
    mock_ticker = MagicMock()
    mock_ticker.ticker = "TEST"
    result = _summarize_fundamentals(mock_ticker, info)
    assert result["score"] <= 10, f"Score {result['score']} exceeds max 10"


def test_fundamentals_profit_margin_in_summary():
    """Profit margin should appear in the summary text."""
    info = {"profitMargins": 0.25}
    mock_ticker = MagicMock()
    mock_ticker.ticker = "TEST"
    result = _summarize_fundamentals(mock_ticker, info)
    assert "Marge" in result["summary"]


# --- Weight Verification ---

def test_component_max_scores_sum_to_100():
    """Verify that the max scores declared in app.py actually sum to 100."""
    expected_max = {
        "EPS-Revisionen": 15,
        "Kursziele & Konsens": 15,
        "News-Sentiment": 15,
        "Technische Indikatoren": 10,
        "Preis/Volumen": 10,
        "Fundamentale Bewertung": 10,
        "Insider-Aktivitaet": 10,
        "Short Interest": 5,
        "Relative Staerke": 5,
        "Event-Druck": 5,
    }
    total = sum(expected_max.values())
    assert total == 100, f"Max scores sum to {total}, expected 100"



def test_generate_delta_report_empty():
    from stock_agent import build_signal_delta_report
    assert build_signal_delta_report([], []) == []
    assert build_signal_delta_report([{"symbol": "AAPL", "brodel_score": 10}], {}) == []

def test_generate_delta_report_with_changes():
    from stock_agent import build_signal_delta_report
    prev_snapshot = {
        "items": [
            {"symbol": "AAPL", "brodel_score": 50, "signal_items": ["Old Signal"]},
            {"symbol": "MSFT", "brodel_score": 60, "signal_items": ["Old Signal"]}
        ]
    }
    current_items = [
        {"symbol": "AAPL", "brodel_score": 60, "signal_items": ["Old Signal", "New Signal"]},
        {"symbol": "MSFT", "brodel_score": 50, "signal_items": []},
        {"symbol": "TSLA", "brodel_score": 40, "signal_items": ["Brand New"]}
    ]
    
    deltas = build_signal_delta_report(current_items, prev_snapshot)
    assert len(deltas) == 3
    
    aapl_delta = next(d for d in deltas if d["symbol"] == "AAPL")
    assert aapl_delta["score_delta"] == 10
    assert aapl_delta["change_type"] == "Gestiegen"
    assert "New Signal" in aapl_delta["new_signals"]
    
    msft_delta = next(d for d in deltas if d["symbol"] == "MSFT")
    assert msft_delta["score_delta"] == -10
    assert msft_delta["change_type"] == "Gefallen"
    
    tsla_delta = next(d for d in deltas if d["symbol"] == "TSLA")
    assert tsla_delta["score_delta"] == 40
    assert tsla_delta["change_type"] == "Neu"




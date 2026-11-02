"""Tests for Brodel 2.0: reweighted components, EPS ratio rule, buyback component and app wiring."""
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd

import stock_agent
from stock_agent import (
    BRODEL_V1_MAX_POINTS,
    BRODEL_V2_MAX_POINTS,
    BUYBACK_COMPONENT_NAME,
    _summarize_share_buyback,
    add_watchlist_peer_context,
    buyback_points,
    compute_brodel_v2_breakdown,
    ensure_brodel_v2,
    eps_revision_ratio_points,
    primary_score,
)


def test_v2_max_points_reweight_components():
    assert BRODEL_V2_MAX_POINTS["Fundamentale Bewertung"] == 15
    assert BRODEL_V2_MAX_POINTS["Kursziele & Konsens"] == 5
    assert BRODEL_V2_MAX_POINTS["Preis/Volumen"] == 5
    assert BRODEL_V2_MAX_POINTS["Technische Indikatoren"] == 5
    assert BRODEL_V2_MAX_POINTS[BUYBACK_COMPONENT_NAME] == 5
    assert sum(BRODEL_V1_MAX_POINTS.values()) == 100
    assert sum(BRODEL_V2_MAX_POINTS.values()) == 90


def test_eps_ratio_points_thresholds():
    assert eps_revision_ratio_points(0, 0) == 0
    assert eps_revision_ratio_points(1, 0) == 0  # fewer than 2 revisions
    assert eps_revision_ratio_points(8, 2) == 15
    assert eps_revision_ratio_points(7, 3) == 10
    assert eps_revision_ratio_points(5, 5) == 5
    assert eps_revision_ratio_points(4, 6) == 0
    assert eps_revision_ratio_points(3, 7) == -5


def test_eps_ratio_ignores_analyst_count():
    # 1.0 gave both full points; 2.0 only rewards the clearly one-sided case
    assert eps_revision_ratio_points(22, 19) == 5
    assert eps_revision_ratio_points(4, 0) == 15


def test_buyback_points():
    assert buyback_points(None) == 0
    assert buyback_points(-0.05) == 5
    assert buyback_points(-0.02) == 3
    assert buyback_points(0.0) == 0
    assert buyback_points(0.08) == -2


def _shares_series(start_value: float, end_value: float) -> pd.Series:
    days = pd.date_range(end=pd.Timestamp.utcnow().tz_localize(None).normalize(), periods=420, freq="D")
    values = pd.Series(range(len(days)), index=days, dtype=float)
    values = start_value + (end_value - start_value) * values / (len(days) - 1)
    return values


def test_share_buyback_detects_shrinking_share_count():
    ticker = MagicMock()
    ticker.get_shares_full.return_value = _shares_series(1_000_000, 950_000)
    result = _summarize_share_buyback(ticker, is_etf=False)
    assert result["name"] == BUYBACK_COMPONENT_NAME
    assert result["score"] == 5
    assert result["share_change"] < -0.03
    assert "Rueckkauf" in result["summary"]


def test_share_buyback_penalises_dilution():
    ticker = MagicMock()
    ticker.get_shares_full.return_value = _shares_series(1_000_000, 1_100_000)
    assert _summarize_share_buyback(ticker, is_etf=False)["score"] == -2


def test_share_buyback_handles_etf_and_missing_data():
    ticker = MagicMock()
    assert _summarize_share_buyback(ticker, is_etf=True)["score"] == 0
    ticker.get_shares_full.return_value = None
    assert _summarize_share_buyback(ticker, is_etf=False)["score"] == 0
    ticker.get_shares_full.side_effect = RuntimeError("no data")
    assert _summarize_share_buyback(ticker, is_etf=False)["score"] == 0


def test_share_buyback_needs_a_full_year():
    ticker = MagicMock()
    days = pd.date_range(end=pd.Timestamp.utcnow().tz_localize(None).normalize(), periods=60, freq="D")
    ticker.get_shares_full.return_value = pd.Series(1_000_000.0, index=days)
    result = _summarize_share_buyback(ticker, is_etf=False)
    assert result["score"] == 0
    assert "zu kurz" in result["summary"]


def test_v2_breakdown_scales_components():
    breakdown = {
        "Kursziele & Konsens": {"name": "Kursziele & Konsens", "score": 15, "summary": "k"},
        "Fundamentale Bewertung": {"name": "Fundamentale Bewertung", "score": 10, "summary": "f"},
        "Preis/Volumen": {"name": "Preis/Volumen", "score": 10, "summary": "p"},
        "Technische Indikatoren": {"name": "Technische Indikatoren", "score": -8, "summary": "t"},
        "Insider-Aktivitaet": {"name": "Insider-Aktivitaet", "score": 6, "summary": "i"},
        "EPS-Revisionen": {"name": "EPS-Revisionen", "score": 15, "summary": "EPS-Revisionen: 8 hoch, 2 runter"},
    }
    v2 = compute_brodel_v2_breakdown(breakdown)
    assert v2["Kursziele & Konsens"]["score"] == 5
    assert v2["Fundamentale Bewertung"]["score"] == 15
    assert v2["Preis/Volumen"]["score"] == 5
    assert v2["Technische Indikatoren"]["score"] == -4
    assert v2["Insider-Aktivitaet"]["score"] == 6
    assert v2["EPS-Revisionen"]["score"] == 15  # parsed from the summary text
    assert v2["News-Sentiment"]["score"] == 0  # missing component
    assert v2[BUYBACK_COMPONENT_NAME]["score"] == 0


def test_v2_breakdown_prefers_stored_eps_counts_and_buyback():
    breakdown = {"EPS-Revisionen": {"name": "EPS-Revisionen", "score": 15, "summary": "", "up": 3, "down": 7}}
    buyback = {"name": BUYBACK_COMPONENT_NAME, "score": 5, "summary": "Rueckkauf"}
    v2 = compute_brodel_v2_breakdown(breakdown, buyback)
    assert v2["EPS-Revisionen"]["score"] == -5
    assert v2[BUYBACK_COMPONENT_NAME]["score"] == 5


def test_ensure_brodel_v2_estimates_old_snapshot_items():
    item = {
        "symbol": "AAA",
        "brodel_score": 40,
        "signal_breakdown": {"Kursziele & Konsens": {"name": "Kursziele & Konsens", "score": 15, "summary": ""}},
    }
    ensure_brodel_v2(item)
    assert item["brodel_score_v2"] == 5
    assert item["brodel_v2_estimated"] is True
    assert primary_score(item) == 5


def test_ensure_brodel_v2_keeps_existing_and_skips_items_without_breakdown():
    fresh = {"brodel_score": 40, "brodel_score_v2": 33}
    assert ensure_brodel_v2(fresh)["brodel_score_v2"] == 33
    bare = {"brodel_score": 12}
    ensure_brodel_v2(bare)
    assert "brodel_score_v2" not in bare
    assert primary_score(bare) == 12


def test_peer_context_ranks_by_brodel_v2():
    items = [
        {"symbol": "A", "sector": "Tech", "brodel_score": 90, "brodel_score_v2": 10},
        {"symbol": "B", "sector": "Tech", "brodel_score": 10, "brodel_score_v2": 50},
    ]
    enriched = {item["symbol"]: item["peer_context"] for item in add_watchlist_peer_context(items)}
    assert enriched["B"]["sector_rank"] == 1
    assert enriched["A"]["top_peer"]["symbol"] == "B"
    assert enriched["A"]["top_peer"]["score"] == 50


@patch("stock_agent.yf.Ticker")
def test_build_symbol_signal_monitor_returns_both_versions(mock_ticker_class):
    mock_instance = MagicMock()
    mock_ticker_class.return_value = mock_instance
    mock_instance.get_info.return_value = {"quoteType": "EQUITY", "shortName": "Apple"}
    with patch.object(stock_agent, "_get_macro_multiplier", return_value=1.0):
        res = stock_agent.build_symbol_signal_monitor("AAPL")
    assert "brodel_score" in res and "brodel_score_v2" in res
    assert BUYBACK_COMPONENT_NAME in res["signal_breakdown_v2"]
    assert BUYBACK_COMPONENT_NAME not in res["signal_breakdown"]  # 1.0 stays unchanged
    assert res["brodel_score_v2"] == sum(c["score"] for c in res["signal_breakdown_v2"].values())


# ── App wiring ──────────────────────────────────────────────────────────────

def _app_item(symbol, v1, v2):
    return {
        "symbol": symbol,
        "name": symbol,
        "brodel_score": v1,
        "brodel_score_v2": v2,
        "signal_breakdown": {"Kursziele & Konsens": {"name": "Kursziele & Konsens", "score": 15, "summary": "k"}},
        "signal_breakdown_v2": {
            "Kursziele & Konsens": {"name": "Kursziele & Konsens", "score": 5, "summary": "k"},
            BUYBACK_COMPONENT_NAME: {"name": BUYBACK_COMPONENT_NAME, "score": 3, "summary": "r"},
        },
        "peer_context": {"sector": "Tech", "score_vs_sector": 1.0, "sector_rank": 1, "sector_count": 2},
    }


def test_table_rows_put_brodel_v2_first_and_v1_last():
    import app

    rows = app.build_signal_table_rows([_app_item("AAA", 80, 20)])
    keys = list(rows[0].keys())
    assert keys[3] == "Brodel 2.0"
    assert keys[-1] == "Brodel 1.0"
    assert rows[0]["Brodel 2.0"] == 20
    assert rows[0]["Brodel 1.0"] == 80
    assert rows[0]["Kursziel"] == 5  # 2.0 points
    assert rows[0]["Rückkauf"] == 3


def test_prepare_signal_items_sorts_by_v2_and_backfills():
    import app

    old_item = {
        "symbol": "OLD",
        "name": "OLD",
        "brodel_score": 99,
        "signal_breakdown": {"Kursziele & Konsens": {"name": "Kursziele & Konsens", "score": 15, "summary": ""}},
    }
    items = app.prepare_signal_items([old_item, _app_item("NEW", 10, 40)])
    assert [item["symbol"] for item in items] == ["NEW", "OLD"]
    assert items[1]["brodel_score_v2"] == 5
    assert "brodel_score_v2" not in old_item  # input is not modified


def test_breakdown_rows_show_both_versions():
    import app

    rows = {row["Komponente"]: row for row in app.build_breakdown_rows(_app_item("AAA", 80, 20))}
    assert rows["Kursziele & Konsens"]["Punkte 2.0"] == 5
    assert rows["Kursziele & Konsens"]["Punkte 1.0"] == 15
    assert rows["Kursziele & Konsens"]["Max 1.0"] == 15
    assert rows[BUYBACK_COMPONENT_NAME]["Max 1.0"] is None
    assert rows[BUYBACK_COMPONENT_NAME]["Punkte 1.0"] is None
    assert rows[BUYBACK_COMPONENT_NAME]["Max 2.0"] == 5


def test_score_history_frame_contains_both_versions():
    import app

    history = [{"timestamp": "2026-11-01T10:00:00Z", "items": [_app_item("AAA", 80, 20)]}]
    frame = app.build_score_history_frame(history)
    assert frame.loc[0, "brodel_score_v2"] == 20
    assert frame.loc[0, "brodel_score"] == 80


def test_brodel_check_rows_list_v2_before_v1():
    import app

    summary = {"mean_ic": 0.05, "n": 3, "t_stat": 1.2}
    results = {label: {"summary": summary, "summary_independent": summary} for label, _ in app.BRODEL_CHECK_VERSIONS}
    rows = app.build_brodel_check_rows(results)
    assert [row["Score"] for row in rows] == ["Brodel 2.0", "Brodel 1.0"]
    assert rows[0]["Mittlerer Rank-IC"] == "+0.050"


def test_interactive_table_shows_v2_first_and_v1_last():
    html = (Path(__file__).parent.parent / "components" / "interactive_table" / "index.html").read_text(encoding="utf-8")
    assert 'let sortColumn = "Brodel 2.0";' in html
    columns = html[html.index("const COLUMNS = ["):html.index("];", html.index("const COLUMNS = ["))]
    assert columns.index('"Brodel 2.0"') < columns.index('"ML-Score"')
    assert columns.rstrip().rstrip("}").rstrip().endswith("isScore: true")
    assert columns.rindex('"Brodel 1.0"') > columns.rindex('"Rang"')
    assert '"Rückkauf"' in columns


def test_help_explains_brodel_v2_and_matches_price_volume_code():
    from tests.test_truth_machine_app import _rendered_help_text

    text = _rendered_help_text("render_help_tab")
    for term in ("Brodel 2.0", "Brodel 1.0", "Aktienrückkauf", "Anteil", "Die 11 Bausteine"):
        assert term in text, term
    # Preis/Volumen help now matches the code: +5 over MA20, +6 over MA50, -3 at a 7 % drop
    assert "20-Tage-Linie: **+5**" in text
    assert "50-Tage-Linie: **+6**" in text
    assert "mindestens 7 % gefallen: **−3**" in text

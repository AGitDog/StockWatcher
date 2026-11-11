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
    assert enriched["A"]["score_basis"] == "points"


def test_peer_context_ranks_by_rank_score_within_region_and_sector():
    items = [
        {"symbol": "BGEO.L", "sector": "Financial Services", "brodel_score_v2": 38, "brodel_score_v3": 90.6},
        {"symbol": "HSBA.L", "sector": "Financial Services", "brodel_score_v2": 70, "brodel_score_v3": 60.0},
        {"symbol": "DBK.DE", "sector": "Financial Services", "brodel_score_v2": 55, "brodel_score_v3": 75.0},
        {"symbol": "JPM", "sector": "Financial Services", "brodel_score_v2": 80, "brodel_score_v3": 95.0},
        {"symbol": "SAP.DE", "sector": "Technology", "brodel_score_v2": 60, "brodel_score_v3": 99.0},
        {"symbol": "EUNL.DE", "sector": "Financial Services", "brodel_score_v2": 20},
    ]
    enriched = {item["symbol"]: item["peer_context"] for item in add_watchlist_peer_context(items)}
    bgeo = enriched["BGEO.L"]
    assert bgeo["score_basis"] == "rank"
    assert bgeo["region"] == "europe"
    assert (bgeo["sector_rank"], bgeo["sector_count"]) == (1, 3)  # JPM, SAP.DE and the ETF are not peers
    assert bgeo["sector_average"] == 75.2
    assert bgeo["score_vs_sector"] == 15.4
    assert bgeo["top_peer"] == {"symbol": "DBK.DE", "name": None, "score": 75.0}
    assert enriched["HSBA.L"]["sector_rank"] == 3
    etf = enriched["EUNL.DE"]
    assert etf["score_basis"] == "points"
    assert (etf["sector_rank"], etf["sector_count"]) == (1, 1)


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
            "EPS-Revisionen": {"name": "EPS-Revisionen", "score": v2 - 8},
        },
        "peer_context": {"sector": "Tech", "score_vs_sector": 1.0, "sector_rank": 1, "sector_count": 2},
    }


def test_table_rows_put_brodel_v2_first_without_v1():
    import app

    rows = app.build_signal_table_rows([_app_item("AAA", 80, 20)])
    keys = [key for key in rows[0] if not key.startswith("_")]
    assert keys[3:5] == ["Rang-Score", "Punkte-Score"]
    assert "Punkte-Score alt" not in keys
    assert keys[-1] == "Rang"
    assert rows[0]["Punkte-Score"] == 20
    assert rows[0]["Kursziel"] == 5  # 2.0 points
    assert rows[0]["Rückkauf"] == 3
    assert "ML-Score" not in rows[0]


def test_table_rows_carry_rank_blocks_and_a_numeric_rank():
    import app

    item = _app_item("AAA", 80, 20)
    item["brodel_score_v3"] = 90.6
    item["signal_breakdown_v3"] = {"Qualitaet": 24.1, "Momentum": 19.1, "EPS-Revisionen": 19.6,
                                   "Bewertung": 13.9, "Aktienrueckkauf": 4.9, "Insider": None}
    item["peer_context"] = {"sector": "Financial Services", "score_basis": "rank", "score_vs_sector": 37.3,
                            "sector_rank": 10, "sector_count": 43}
    etf = _app_item("ETF", 0, 5)
    etf["peer_context"] = {"sector": "Unbekannt", "score_basis": "points", "score_vs_sector": 4.0,
                           "sector_rank": 2, "sector_count": 9}
    row, etf_row = app.build_signal_table_rows([item, etf])
    assert row["R:Qualitaet"] == 24.1 and row["R:Insider"] is None
    assert row["Rang"] == "10/43" and row["_rang_pos"] == 10  # sorted as a number, not as text
    assert row["Vs. Sektor"] == 37.3
    assert etf_row["Vs. Sektor"] is None and etf_row["Rang"] is None  # no points mixed into a Rang-Score column


def test_prepare_signal_items_sorts_by_rank_score_first():
    import app

    low, high, none = _app_item("LOW", 0, 60), _app_item("HIGH", 0, 10), _app_item("NONE", 0, 90)
    low["brodel_score_v3"], high["brodel_score_v3"] = 40.0, 90.6
    assert [item["symbol"] for item in app.prepare_signal_items([low, none, high])] == ["HIGH", "LOW", "NONE"]
    assert app.score_label(high) == "Rang-Score 90.6 · Punkte-Score 10"
    assert app.score_label(none) == "kein Rang-Score · Punkte-Score 90"


def test_rank_score_explanation_shows_the_calculation():
    import app

    item = _app_item("AAA", 80, 20)
    item["brodel_score_v3"] = 90.7
    item["signal_breakdown_v3"] = {"Qualitaet": 24.1, "Momentum": 19.1, "EPS-Revisionen": 19.6,
                                   "Bewertung": 13.9, "Aktienrueckkauf": 4.9, "Insider": None}
    text = app.rank_score_explanation(item)
    assert "81.6 von 90 möglichen Punkten" in text
    assert "Insider ohne Daten" in text
    assert "**90.7**" in text
    assert app.rank_score_explanation(_app_item("B", 0, 0)) is None


def test_score_history_contains_rank_score_by_data_day():
    import app

    def stock(symbol, momentum):
        item = _app_item(symbol, 10, 10)
        item["factors_v3"] = {"profit_margin": 0.1, "return_on_equity": 0.1, "momentum_12_1": momentum, "eps_up_ratio": 0.5,
                              "share_change": 0.0, "forward_pe": 12.0}
        return item

    history = [
        {"timestamp": "2026-11-05T10:00:00Z", "items": [_app_item("AAA", 80, 20)]},  # before factors were stored
        {"timestamp": "2026-11-06T23:59:59Z", "items": [stock("AAA", 0.5), stock("BBB", 0.1)]},
    ]
    frame = app.build_score_history_frame(history)
    first = frame[frame["timestamp"] == pd.Timestamp("2026-11-05")]
    later = frame[(frame["timestamp"] == pd.Timestamp("2026-11-06")) & (frame["symbol"] == "AAA")]
    assert first["brodel_score_v3"].isna().all()
    assert later["brodel_score_v3"].iloc[0] > frame.loc[frame["symbol"] == "BBB", "brodel_score_v3"].iloc[0]


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


def test_breakdown_rows_show_points_without_old_version():
    import app

    rows = app.build_breakdown_rows(_app_item("AAA", 80, 20))
    by_name = {row["Baustein"]: row for row in rows}
    assert by_name["Kursziele & Konsens"]["Punkte-Score"] == 5
    assert by_name["Aktienrückkauf"]["Punkte-Score"] == 3
    assert all("Punkte 1.0" not in row for row in rows)  # old version is no longer shown
    assert not any("Max" in key for key in rows[0])
    assert rows[0]["Punkte-Score"] == max(row["Punkte-Score"] or 0 for row in rows)  # strongest first
    assert all(row["Rang-Score"] is None for row in rows)  # no Rang-Score yet
    assert by_name["Qualität"]["Punkte-Score"] is None


def test_breakdown_rows_show_brodel_v3():
    import app

    item = _app_item("AAA", 80, 20)
    item["signal_breakdown_v3"] = {"Qualitaet": 20.0, "Momentum": 15.0, "EPS-Revisionen": 18.0,
                                   "Bewertung": 9.0, "Aktienrueckkauf": 9.5, "Insider": None}
    item["factors_v3"] = {"profit_margin": 0.25, "forward_pe": 14.2, "momentum_12_1": 0.31}
    rows = app.build_breakdown_rows(item)
    assert rows[0]["Baustein"] == "Qualität" and rows[0]["Rang-Score"] == 20.0
    assert "Marge 25.0 %" in rows[0]["Detail"]
    by_name = {row["Baustein"]: row for row in rows}
    assert by_name["EPS-Revisionen"]["Rang-Score"] == 18.0
    assert by_name["Aktienrückkauf"]["Rang-Score"] == 9.5
    assert "+31.0 %" in by_name["Momentum"]["Detail"]
    assert by_name["Relative Stärke"]["Rang-Score"] is None


def test_help_explains_brodel_v3_with_the_real_weights():
    import app
    from brodel_v3 import BRODEL_V3_WEIGHTS

    rows = app.build_v3_help_rows()
    assert [int(row["Punkte"]) for row in rows] == list(BRODEL_V3_WEIGHTS.values())
    source = (Path(__file__).parent.parent / "app.py").read_text(encoding="utf-8")
    assert '"Rang-Score", "Punkte-Score", "Spieldepots"' in source  # help tabs
    assert "Trades: fünf Spieldepots im Vergleich" in source


def test_macro_overlay_of_old_snapshots_is_removed():
    from stock_agent import primary_score

    item = _app_item("AAA", 80, 20)
    item["brodel_score_v2"] = 14  # stored with a macro factor of 0.72
    assert primary_score(item) == 20
    assert ensure_brodel_v2(dict(item))["brodel_score_v2"] == 20


def test_new_scores_contain_no_macro_overlay():
    mock_instance = MagicMock()
    with patch.object(stock_agent.yf, "Ticker", return_value=mock_instance), \
         patch.object(stock_agent, "_get_macro_multiplier", return_value=0.5):
        mock_instance.get_info.return_value = {"quoteType": "EQUITY", "shortName": "Apple", "profitMargins": 0.3}
        res = stock_agent.build_symbol_signal_monitor("AAPL")
    assert res["brodel_score_v2"] == sum(c["score"] for c in res["signal_breakdown_v2"].values())
    assert res["factors_v3"]["profit_margin"] == 0.3


def test_score_history_frame_contains_both_versions():
    import app

    history = [{"timestamp": "2026-11-01T10:00:00Z", "items": [_app_item("AAA", 80, 20)]}]
    frame = app.build_score_history_frame(history)
    assert frame.loc[0, "brodel_score_v2"] == 20
    assert frame.loc[0, "brodel_score"] == 80


def test_brodel_check_rows_only_current_points_score():
    import app

    summary = {"mean_ic": 0.05, "n": 3, "t_stat": 1.2}
    results = {label: {"summary": summary, "summary_independent": summary} for label, _ in app.BRODEL_CHECK_VERSIONS}
    rows = app.build_brodel_check_rows(results)
    assert [row["Score"] for row in rows] == ["Punkte-Score"]
    assert rows[0]["Mittlerer Rank-IC"] == "+0.050"


def test_interactive_table_shows_v2_first_without_v1():
    html = (Path(__file__).parent.parent / "components" / "interactive_table" / "index.html").read_text(encoding="utf-8")
    assert 'let sortColumn = "Rang-Score";' in html
    columns = html[html.index("const COLUMNS = ["):html.index("];", html.index("const COLUMNS = ["))]
    assert columns.index('"Rang-Score"') < columns.index('"Punkte-Score"') < columns.index('"EPS"')
    assert '"ML-Score"' not in columns  # hidden until a model passes the out-of-sample test
    assert "Brodel" not in html
    assert '"Rang"' in columns
    assert '"Rückkauf"' in columns


def test_help_explains_brodel_v2_and_matches_price_volume_code():
    from tests.test_truth_machine_app import _rendered_help_text

    text = _rendered_help_text("render_help_tab")
    for term in ("Punkte-Score", "Aktienrückkauf", "Anteil", "Die 11 Bausteine", "zwischen −30 und 90"):
        assert term in text, term
    for removed in ("Punkte-Score alt", "alt: max", "Max alt", "was sich geändert hat", "Makro-Overlay", "Strategie-Setups"):
        assert removed not in text, removed  # only one Punkte-Score, nothing that is no longer shown
    # Preis/Volumen help now matches the code: +5 over MA20, +6 over MA50, -3 at a 7 % drop
    assert "20-Tage-Linie: **+5**" in text
    assert "50-Tage-Linie: **+6**" in text
    assert "mindestens 7 % gefallen: **−3**" in text


def test_interactive_table_tooltips_match_v2_maxima():
    import re

    import app

    html = (Path(__file__).parent.parent / "components" / "interactive_table" / "index.html").read_text(encoding="utf-8")
    for label, component in app.V2_TABLE_COLUMNS:
        match = re.search(r'key: "' + re.escape(label) + r'".*?max\. (\d+)\)', html)
        assert match, label
        assert int(match.group(1)) == BRODEL_V2_MAX_POINTS[component], label
    assert f"max. {sum(BRODEL_V2_MAX_POINTS.values())})" in html


def test_table_rows_mark_stale_and_missing_entries():
    import app
    import snapshot_store

    fresh = _app_item("AAA", 80, 20)
    stale = {**_app_item("BBB", 80, 20), "stale_from": "2026-11-04"}
    missing = _app_item("CCC", 0, 0)
    missing["signal_breakdown"]["Preis/Volumen"] = {"name": "Preis/Volumen", "score": 0, "summary": snapshot_store.MISSING_PRICE_SUMMARY}
    rows = app.build_signal_table_rows([fresh, stale, missing])
    assert "_status" not in rows[0]
    assert rows[1]["_status"] == "stale" and "2026-11-04" in rows[1]["_hint"]
    assert rows[2]["_status"] == "missing"


def test_no_brodel_in_visible_texts():
    """The system is called StockWatcher; "Brodel" only survives in internal field names."""
    import re

    source = (Path(__file__).parent.parent / "app.py").read_text(encoding="utf-8")
    strings = re.findall(r'"[^"\n]*"', source)
    assert not [s for s in strings if "Brodel" in s]


def test_start_page_is_shown_unless_the_browser_skips_it():
    import app

    fresh: dict = {}
    app.choose_start_page(None, fresh)  # browser has not answered yet
    assert fresh["page"] == app.PAGE_START and "start_pref_applied" not in fresh
    app.choose_start_page({"skip_start": False}, fresh)
    assert fresh["page"] == app.PAGE_START

    skipper: dict = {}
    app.choose_start_page({"skip_start": True}, skipper)
    assert skipper["page"] == app.PAGE_MARKET
    skipper["page"] = app.PAGE_START  # user clicks "Start" later in the same session
    app.choose_start_page({"skip_start": True}, skipper)
    assert skipper["page"] == app.PAGE_START  # applied only once


def test_visitor_prefs_component_stores_only_in_the_browser():
    html = (Path(__file__).parent.parent / "components" / "visitor_prefs" / "index.html").read_text(encoding="utf-8")
    assert "localStorage" in html and "stockwatcher.skip_start" in html
    assert "fetch(" not in html and "XMLHttpRequest" not in html


def test_breakdown_marks_insider_without_buys_as_neutral():
    import app

    item = _app_item("NVDA", 20, 20)
    item["signal_breakdown"]["Insider-Aktivitaet"] = {"name": "Insider-Aktivitaet", "score": 0, "summary": "[Finnhub] 0 Kaeufe, 4 Verkaeufe"}
    item["signal_breakdown_v3"] = {"Qualitaet": 22.0, "Momentum": 4.0, "EPS-Revisionen": 15.0,
                                   "Bewertung": 7.5, "Aktienrueckkauf": 6.0, "Insider": 5.0}
    item["factors_v3"] = {"insider_buy_usd": 0.0, "insider_source": "Finnhub/Yahoo"}
    rows = app.build_breakdown_rows(item)
    by_name = {row["Baustein"]: row for row in rows}
    insider = by_name["Insider-Aktivität"]["Detail"]
    assert "0 Käufe, 4 Verkäufe" in insider and "keine Käufe = neutral" in insider and "Verkäufe nicht" in insider
    assert "besser als 75 %" in by_name["EPS-Revisionen"]["Detail"]

    styles = {row["Baustein"]: style for row, style in zip(rows, [app._rank_points_style(pd.Series(r)) for r in rows])}
    column = list(rows[0]).index("Rang-Score")
    assert styles["Insider-Aktivität"][column] == ""  # 5 of 10 is the middle, not green
    assert "2e9e5b" in styles["Qualität"][column]  # 22 of 25
    assert "d9534f" in styles["Momentum"][column]  # 4 of 20
    assert app.v3_weight_for_label("Aktienrückkauf") == 10
    app.style_breakdown(pd.DataFrame(rows)).to_html()  # renders without error


def test_breakdown_says_when_insider_data_is_missing():
    import app

    item = _app_item("MC.PA", 20, 20)
    item["signal_breakdown_v3"] = {"Qualitaet": 22.0, "Momentum": 4.0, "EPS-Revisionen": 15.0,
                                   "Bewertung": 7.5, "Aktienrueckkauf": 6.0, "Insider": 5.0}
    item["factors_v3"] = {"insider_buy_usd": None}
    by_name = {row["Baustein"]: row for row in app.build_breakdown_rows(item)}
    assert "keine Daten für dieses Land = neutral" in by_name["Insider-Aktivität"]["Detail"]


def test_breakdown_detail_has_no_source_and_no_version_names():
    import app

    item = _app_item("SAP.DE", 20, 20)
    item["signal_breakdown"]["Insider-Aktivitaet"] = {"name": "Insider-Aktivitaet", "score": 4, "summary": "[Finnhub] 2 Kaeufe, 0 Verkaeufe"}
    item["signal_breakdown"]["Fundamentale Bewertung"] = {"name": "Fundamentale Bewertung", "score": 2, "summary": "[YF] Fundamentaldaten unauffaellig."}
    item["signal_breakdown_v3"] = {"Qualitaet": 22.0, "Momentum": 4.0, "EPS-Revisionen": 15.0,
                                   "Bewertung": 7.5, "Aktienrueckkauf": 6.0, "Insider": 7.5}
    item["factors_v3"] = {"insider_buy_usd": 20_000.0, "insider_source": "Tracefour"}
    rows = app.build_breakdown_rows(item)
    assert set(rows[0]) == {"Baustein", "Rang-Score", "Punkte-Score", "Detail"}
    text = " ".join(f"{row['Baustein']} {row['Detail']}" for row in rows)
    for gone in ("3.0", "2.0", "[Finnhub]", "[YF]", "Quelle", "Tracefour", "Kaeufe", "unauffaellig"):
        assert gone not in text, gone
    by_name = {row["Baustein"]: row for row in rows}
    assert by_name["Insider-Aktivität"]["Detail"] == "2 Käufe, 0 Verkäufe · Rang-Score 7.5 von 10: kleine Käufe, nur Käufe zählen, Verkäufe nicht"
    assert by_name["EPS-Revisionen"]["Detail"].endswith("Rang-Score 15.0 von 20: besser als 75 % der Vergleichsaktien")
    assert app.clean_detail("Aktienanzahl 12M: -2.0% - Rueckkauf (bullisch)") == "Aktienanzahl 12M: -2.0% - Rückkauf (bullisch)"


def test_quality_detail_names_the_new_figures_and_keeps_old_days_readable():
    import app

    new = app.v3_block_details({"operating_margin": 0.31, "return_on_assets": 0.12, "fcf_to_debt": 0.42})["Qualitaet"]
    assert new == "Operative Marge 31.0 %, Gesamtkapitalrendite 12.0 %, Free Cashflow 42.0 % der Schulden"
    old = app.v3_block_details({"profit_margin": 0.2, "return_on_equity": 1.4, "debt_equity": 84.0})["Qualitaet"]
    assert old.startswith("Marge 20.0 %, Eigenkapitalrendite 140.0 %")

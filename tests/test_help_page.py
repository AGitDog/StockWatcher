"""The help page: one Punkte-Score, tables that follow the code, every data source listed."""
import app
from stock_agent import BRODEL_V2_MAX_POINTS
from tests.test_truth_machine_app import _rendered_help_text


def test_points_overview_follows_the_code():
    rows = app.build_points_help_rows()
    assert len(rows) == 11
    assert sum(int(row["Max. Punkte"]) for row in rows) == sum(BRODEL_V2_MAX_POINTS.values()) == 90
    assert rows[0]["Max. Punkte"] == "15"  # largest first


def test_help_is_split_into_tabs_and_lists_all_sources():
    text = _rendered_help_text("render_help_tab")
    for term in ("Die Seiten", "Tracefour", "SIX", "AMF", "AFM", "Finnhub", "Stop-Loss", "MSCI World ETF"):
        assert term in text, term
    assert "FRED" not in text  # only fed the removed macro overlay
    assert "Die drei Tabs" not in text  # the app has five pages


def test_insider_help_names_every_routed_market():
    countries = " ".join(row["Land"] for row in app.HELP_INSIDER_SOURCE_ROWS)
    for country in ("USA", "Deutschland", "Schweiz", "Frankreich", "Niederlande", "Großbritannien", "Japan"):
        assert country in countries


def test_best_depot_names_the_winner():
    assert app.best_depot({"day": "2026-11-10", "etf": 101500.0, "bot": 100629.3, "no_stop": 100100.0, "rank": 100492.2}) == ("Punkte-Score ab 60", 100629.3)
    assert app.best_depot({}) == ("noch keine Werte", 100_000.0)


def test_start_page_text_is_current():
    from pathlib import Path

    source = (Path(app.__file__)).read_text(encoding="utf-8")
    start = source[source.index("def render_start_page"):source.index("def render_app")]
    assert "die ältere Methode" not in start and "1.375" not in start
    assert "zwei davon verkaufen per Stop-Loss" in start

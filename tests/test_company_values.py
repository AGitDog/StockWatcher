"""The company-values tab: plain tables, years as columns, nothing added beyond the fetched data."""
from pathlib import Path

import app

EXT = {
    "currency": "EUR",
    "financial_currency": "EUR",
    "main_currency": "EUR",
    "sector_de": "Technologie",
    "industry_de": "Software",
    "city": "Walldorf",
    "country": "Germany",
    "employees": 109121,
    "current_price": 238.4,
    "target_mean_price": 280.0,
    "upside_pct": 17.46,
    "implied_market_cap": 326_400_000_000,
    "trailing_pe": 41.23,
    "forward_pe": None,
    "gross_margin_ttm": 73.1,
    "operating_margin_ttm": 27.5,
    "gross_margin_history": [
        {"Jahr": 2024, "Umsatz": 34_176_000_000, "Bruttogewinn": 24_200_000_000, "Bruttomarge": 70.81},
        {"Jahr": 2023, "Umsatz": 31_207_000_000, "Bruttogewinn": 22_000_000_000, "Bruttomarge": 70.5},
    ],
    "operating_cost_history": [
        {"Jahr": 2023, "Umsatz": 31_207_000_000, "OpEx": 15_000_000_000, "FE": 6_300_000_000, "SGA": None,
         "Operativer_Gewinn": 7_000_000_000, "EBIT": 7_000_000_000, "Operative_Marge": 22.43, "OpEx_Quote": 48.07, "FE_Quote": 20.19, "SGA_Quote": None},
    ],
    "pe_trend": [{"Jahr": 2024, "EPS": 2.65, "Kurs": 235.1, "KGV": 88.7}],
    "dividend_yield_pct": 1.05,
    "dividend_rate": 2.5,
    "dividend_streak_years": 3,
    "dividend_history": [
        {"Jahr": 2025, "Dividende": 2.35, "Rendite (%)": 1.0, "Wachstum (%)": 6.8},
        {"Jahr": 2026, "Dividende": 2.5, "Rendite (%)": None, "Wachstum (%)": None},
    ],
}


def test_german_number_formats():
    assert app.fmt_amount(34_176_000_000, "EUR") == "34,18 Mrd. EUR"
    assert app.fmt_amount(-250_400_000) == "-250,4 Mio."
    assert app.fmt_amount(None) == "–"
    assert app.fmt_pct(17.46, signed=True) == "+17,5 %"
    assert app.fmt_pct(-3.0, signed=True) == "-3,0 %"
    assert app.fmt_plain(238.4, 2, "EUR") == "238,40 EUR"


def test_profile_line():
    assert app.build_company_profile_line(EXT) == "**Sektor:** Technologie · **Branche:** Software · **Sitz:** Walldorf, Germany · **Mitarbeiter:** 109.121"
    assert app.build_company_profile_line({"sector_de": "-"}) == ""


def test_income_table_has_years_as_columns_and_merges_both_histories():
    table = app.build_income_history_table(EXT)
    assert list(table.columns) == ["Kennzahl", "2023", "2024"]  # oldest left, like an annual report
    by_line = table.set_index("Kennzahl")
    assert by_line.loc["Umsatz", "2024"] == "34,18 Mrd."
    assert by_line.loc["Operativer Gewinn (EBIT)", "2023"] == "7,00 Mrd."
    assert by_line.loc["Operativer Gewinn (EBIT)", "2024"] == "–"
    assert "Vertrieb & Verwaltung (SG&A)" not in by_line.index  # no value in any year: line left out


def test_tables_only_show_fetched_figures():
    valuation = {row["Kennzahl"]: row["Wert"] for row in app.build_valuation_rows(EXT)}
    assert valuation["Abstand zum Kursziel"] == "+17,5 %" and valuation["KGV erwartet"] == "–"
    pe = app.build_pe_history_table(EXT).set_index("Kennzahl")
    assert list(pe.index) == ["Kurs zum Jahresende (EUR)", "KGV"]  # EPS is not shown, as before
    dividend = app.build_dividend_history_table(EXT).set_index("Kennzahl")
    assert dividend.loc["Wachstum zum Vorjahr", "2026"] == "–"
    assert app.build_income_history_table({}) is None


def test_tab_renders_tables_without_charts():
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_string("import app\nfrom tests.test_company_values import EXT\napp.render_company_values(EXT)\n")
    at.run(timeout=60)
    assert not at.exception
    assert len(at.dataframe) == 6
    source = Path(app.__file__).read_text(encoding="utf-8")
    body = source[source.index("def render_company_values"):source.index("def render_truth_machine_help")]
    assert "chart" not in body

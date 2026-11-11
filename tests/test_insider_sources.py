"""Insider purchases outside the USA: UK wording in Yahoo, BaFin CSV stored by hand."""
from datetime import date
from unittest.mock import MagicMock, patch

import pandas as pd

import insider_sources
from insider_sources import bafin_buy_value_eur, is_open_market_buy, normalize_company_name


def test_open_market_buys_in_us_and_uk_wording_without_buybacks():
    assert is_open_market_buy("Purchase at price 64.18 per share.")
    assert is_open_market_buy("Bought at price 17.35 per share.")
    assert not is_open_market_buy("Buy Back at price 127.42 per share.")
    assert not is_open_market_buy("Sold at price 65.48 per share.")
    assert not is_open_market_buy("Exercise of Option at price 88.43 per share.")
    assert not is_open_market_buy(None)


def test_yahoo_value_counts_uk_purchases():
    now = pd.Timestamp.now()
    frame = pd.DataFrame({
        "Text": ["Bought at price 17.35 per share.", "Buy Back at price 120 per share.", "Sold at price 17 per share."],
        "Value": [214027.0, 8366578.0, 50000.0],
        "Start Date": [now - pd.Timedelta(days=5)] * 3,
    })
    assert insider_sources.yahoo_buy_value(frame) == 214027.0


def test_company_names_match_between_yahoo_and_bafin():
    assert normalize_company_name("SAP SE") == normalize_company_name("SAP SE ") == "sap"
    assert normalize_company_name("Bayerische Motoren Werke Aktiengesellschaft") == normalize_company_name("Bayerische Motoren Werke AG")
    assert normalize_company_name("Mercedes-Benz Group AG") == "mercedes benz"
    assert normalize_company_name("Münchener Rückversicherungs-Gesellschaft AG") == "munchener ruckversicherungs gesellschaft"


BAFIN_CSV = (
    "﻿Emittent;Bafin-ID;ISIN;Meldepflichtiger;Position / Status;Art des Instruments;Art des Geschäfts;Durchschnittspreis;"
    "Aggregiertes Volumen;Mitteilungsdatum;Datum des Geschäfts;Ort des Geschäfts;Datum der Aktivierung\n"
    "SAP SE;1;DE0007164600;A, B;Vorstand;Aktie;Kauf;178,30 EUR;267.450,00 EUR;26.08.2026;26.08.2026;XETRA;26.08.2026\n"
    "SAP SE;1;DE0007164600;C, D;Vorstand;Aktie;Verkauf;178,30 EUR;99.000,00 EUR;26.08.2026;26.08.2026;XETRA;26.08.2026\n"
    "SAP SE;1;DE0007164600;E, F;Aufsichtsrat;Aktie;Sonstiges;176,67 EUR;8.824,09 EUR;14.09.2026;11.09.2026;XETRA;14.09.2026\n"
    "SAP SE;1;DE0007164600;G, H;Vorstand;Aktie;Kauf;150,00 EUR;10.000,00 EUR;01.03.2026;01.03.2026;XETRA;01.03.2026\n"
    "SAP SE;1;DE0007164600;I, J;Vorstand;Anleihe;Kauf;100,00 EUR;50.000,00 EUR;26.08.2026;26.08.2026;XETRA;26.08.2026\n"
)


def test_bafin_file_counts_recent_share_purchases(tmp_path):
    file = tmp_path / "bafin.csv"
    file.write_text(BAFIN_CSV, encoding="utf-8")
    insider_sources.load_bafin_purchases.cache_clear()
    try:
        today = date(2026, 11, 1)
        assert bafin_buy_value_eur(["SAP SE"], today=today, path=str(file)) == 267450.0  # old buy, sale, bond ignored
        assert bafin_buy_value_eur(["Unknown AG"], today=today, path=str(file)) == 0.0  # no match = no purchase
        assert bafin_buy_value_eur(["SAP SE"], today=today, path=str(tmp_path / "missing.csv")) is None
    finally:
        insider_sources.load_bafin_purchases.cache_clear()


def test_conversion_to_usd():
    insider_sources.usd_per_unit.cache_clear()
    fake = MagicMock()
    fake.history.return_value = pd.DataFrame({"Close": [1.25]})
    try:
        with patch("insider_sources.yf.Ticker", return_value=fake) as ticker:
            assert insider_sources.to_usd(1000.0, "GBP") == 1250.0
            ticker.assert_called_with("GBPUSD=X")
        assert insider_sources.to_usd(0.0, "EUR") == 0.0
        assert insider_sources.to_usd(None, "EUR") is None
        assert insider_sources.to_usd(10.0, "USD") == 10.0
    finally:
        insider_sources.usd_per_unit.cache_clear()


def test_v3_factors_use_the_source_of_each_country():
    import stock_agent

    with patch("insider_sources.to_usd", side_effect=lambda value, currency: None if value is None else value * 2), \
         patch("insider_sources.bafin_buy_value_eur", return_value=300.0):
        uk = stock_agent.collect_v3_factors("HSBA.L", {"currency": "GBp"}, None, {}, {}, {"buy_value_usd": 100.0}, False)
        de = stock_agent.collect_v3_factors("SAP.DE", {"longName": "SAP SE"}, None, {}, {}, {}, False)
        fr = stock_agent.collect_v3_factors("MC.PA", {}, None, {}, {}, {}, False)
    assert (uk["insider_buy_usd"], uk["insider_source"]) == (200.0, "Yahoo")
    assert (de["insider_buy_usd"], de["insider_source"]) == (600.0, "BaFin")
    assert (fr["insider_buy_usd"], fr["insider_source"]) == (None, None)

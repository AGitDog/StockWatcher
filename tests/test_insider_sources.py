"""Insider purchases outside the USA: every source parsed from fixtures, never from the network."""
import json
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

import insider_sources
from insider_sources import (
    afm_purchase_value, amf_purchase_value, bafin_buy_value_eur, is_open_market_buy, market_of, names_match,
    normalize_company_name, parse_afm_detail, parse_afm_search, parse_amf_notice, parse_six_items,
)

FIXTURES = Path(__file__).parent / "fixtures" / "insider"


# ── wording, names, numbers ─────────────────────────────────────────────────

@pytest.mark.parametrize("text, expected", [
    ("Purchase at price 64.18 per share.", True),          # USA
    ("Bought at price 17.35 per share.", True),            # UK, Spain, France
    ("Acquisition in the public market at price 95.20 per share.", True),  # Canada (SEDI)
    ("Buy", True),
    ("Buy Back at price 127.42 per share.", False),        # the company itself
    ("Redemption, retraction, cancelation, repurchase at price 204.11 per share.", False),
    ("Acquisition under a purchase/ownership plan at price 50 per share.", False),
    ("Exercise of options at price 88.43 per share.", False),
    ("Sold at price 65.48 per share.", False),
    ("Disposition in the public market at price 10 per share.", False),
    ("Stock Award(Grant) at price 0.00 per share.", False),
    (None, False),
])
def test_open_market_buy_wording(text, expected):
    assert is_open_market_buy(text) is expected


def test_company_names_match_across_sources():
    assert normalize_company_name("SAP SE") == "sap"
    assert normalize_company_name("Bayerische Motoren Werke Aktiengesellschaft") == normalize_company_name("Bayerische Motoren Werke AG")
    assert normalize_company_name("Publicis Groupe S.A.") == normalize_company_name("PUBLICIS GROUPE SA") == "publicis"
    assert normalize_company_name("Dassault Systèmes SE") == normalize_company_name("DASSAULT SYSTEMES") == "dassault systemes"
    assert normalize_company_name("ING Groep N.V.") == "ing"
    assert normalize_company_name("Chocoladefabriken Lindt & Sprüngli AG") == "chocoladefabriken lindt sprungli"
    assert names_match("roche", "roche")
    assert names_match("kuhne nagel international", "kuhne nagel")  # longer name with extra words
    assert not names_match("ing", "ing bank polska")  # too short to match by prefix
    assert not names_match("", "sap")


def test_number_formats():
    assert insider_sources._parse_number("267.450,00 EUR") == 267450.0
    assert insider_sources._parse_number("8.7200") == 8.72
    assert insider_sources._parse_number("1 000.0000") == 1000.0
    assert insider_sources._parse_number("10.000,00") == 10000.0
    assert insider_sources._parse_number("1,234,567") == 1234567.0
    assert insider_sources._parse_number("") is None


def test_market_of_symbol():
    assert market_of("AAPL") == "US"
    assert market_of("BRK.B") == "US"  # US share class, not an exchange
    assert market_of("HSBA.L") == "L"
    assert market_of("NOVN.SW") == "SW"


# ── Yahoo ────────────────────────────────────────────────────────────────────

def test_yahoo_value_counts_only_recent_market_purchases():
    now = pd.Timestamp.now()
    frame = pd.DataFrame({
        "Text": ["Bought at price 17.35 per share.", "Buy Back at price 120 per share.", "Sold at price 17 per share.",
                 "Acquisition in the public market at price 95 per share.", "Bought at price 10 per share."],
        "Value": [214027.0, 8366578.0, 50000.0, 9500.0, 1000.0],
        "Start Date": [now - pd.Timedelta(days=5)] * 4 + [now - pd.Timedelta(days=200)],
    })
    assert insider_sources.yahoo_buy_value(frame) == 214027.0 + 9500.0
    assert insider_sources.yahoo_buy_value(None) is None
    assert insider_sources.yahoo_buy_value(frame.iloc[0:0]) == 0.0


# ── Germany: BaFin CSV ──────────────────────────────────────────────────────

BAFIN_CSV = (
    "﻿Emittent;Bafin-ID;ISIN;Meldepflichtiger;Position / Status;Art des Instruments;Art des Geschäfts;Durchschnittspreis;"
    "Aggregiertes Volumen;Mitteilungsdatum;Datum des Geschäfts;Ort des Geschäfts;Datum der Aktivierung\n"
    "SAP SE;1;DE0007164600;A;Vorstand;Aktie;Kauf;178,30 EUR;267.450,00 EUR;26.08.2026;26.08.2026;XETRA;26.08.2026\n"
    "SAP SE;1;DE0007164600;B;Vorstand;Aktie;Verkauf;178,30 EUR;99.000,00 EUR;26.08.2026;26.08.2026;XETRA;26.08.2026\n"
    "SAP SE;1;DE0007164600;C;Aufsichtsrat;Aktie;Sonstiges;176,67 EUR;8.824,09 EUR;14.09.2026;11.09.2026;XETRA;14.09.2026\n"
    "SAP SE;1;DE0007164600;D;Vorstand;Aktie;Kauf;150,00 EUR;10.000,00 EUR;01.03.2026;01.03.2026;XETRA;01.03.2026\n"
    "SAP SE;1;DE0007164600;E;Vorstand;Anleihe;Kauf;100,00 EUR;50.000,00 EUR;26.08.2026;26.08.2026;XETRA;26.08.2026\n"
)


def test_bafin_file_counts_recent_share_purchases(tmp_path):
    file = tmp_path / "bafin.csv"
    file.write_text(BAFIN_CSV, encoding="utf-8")
    today = date(2026, 11, 1)
    assert bafin_buy_value_eur(["SAP SE"], today=today, path=str(file)) == 267450.0  # old buy, sale, bond ignored
    assert bafin_buy_value_eur(["Unknown AG"], today=today, path=str(file)) == 0.0  # no match = no purchase
    assert bafin_buy_value_eur(["SAP SE"], today=today, path=str(tmp_path / "missing.csv")) is None


# ── Switzerland: SIX ────────────────────────────────────────────────────────

def _six(**fields):
    base = {"notificationId": "N1", "correcteeId": "", "buySellIndicator": "1", "securityTypeCode": "7",
            "obligorRelatedPartyInd": "", "transactionConditions": "", "transactionAmountCHF": 100000.0,
            "transactionDate": 20261001, "ISIN": "CH0012005267", "transactionSize": 1000.0,
            "notificationSubmitter": "Novartis AG"}
    return {**base, **fields}


def test_six_fixture_from_real_records():
    items = json.loads((FIXTURES / "six_items.json").read_text(encoding="utf-8"))
    purchases = parse_six_items(items)
    assert "sfs" in purchases and "phoenix mecano" in purchases
    assert "alpine select" not in purchases  # a related legal entity, no manager's own money
    assert "galderma" not in purchases  # only sales
    assert "chocoladefabriken lindt sprungli" not in purchases  # option exercise and sale
    assert all(value > 0 for rows in purchases.values() for _, value in rows)


def test_six_filters_options_duplicates_and_corrections():
    items = [
        _six(notificationId="A"),
        _six(notificationId="B"),  # the same trade reported twice
        _six(notificationId="C", transactionConditions="Exercise & Sale", transactionAmountCHF=5.0),
        _six(notificationId="D", securityTypeCode="6", transactionAmountCHF=7.0),  # options
        _six(notificationId="E", buySellIndicator="2", transactionAmountCHF=9.0),  # sale
        _six(notificationId="F", transactionAmountCHF=50000.0, transactionSize=500.0),  # corrected by G
        _six(notificationId="G", correcteeId="F", transactionAmountCHF=40000.0, transactionSize=400.0),
        _six(notificationId="H", transactionConditions="Mitarbeitendenaktienprogramm 2026", transactionAmountCHF=3.0),
    ]
    purchases = parse_six_items(items)
    assert sorted(value for _, value in purchases["novartis"]) == [40000.0, 100000.0]


def test_six_value_uses_the_window(monkeypatch):
    monkeypatch.setattr(insider_sources, "six_purchases", lambda: {"novartis": [(date(2026, 10, 1), 1000.0), (date(2026, 1, 1), 5.0)]})
    assert insider_sources.six_buy_value_chf(["Novartis AG"], today=date(2026, 11, 1)) == 1000.0
    monkeypatch.setattr(insider_sources, "six_purchases", lambda: None)
    assert insider_sources.six_buy_value_chf(["Novartis AG"]) is None


# ── France: AMF ─────────────────────────────────────────────────────────────

def test_amf_notice_from_pdf_text():
    transactions = parse_amf_notice((FIXTURES / "amf_notice.txt").read_text(encoding="utf-8"))
    assert len(transactions) == 3  # the English copy is ignored
    first, free_shares, sale = transactions
    assert first == {"date": "2026-11-09", "nature": "acquisition", "instrument": "action", "options": False,
                     "price": 150.96, "volume": 500.0, "currency": "euro"}
    assert free_shares["options"] is True and free_shares["volume"] == 1000.0
    assert sale["nature"] == "cession"
    assert amf_purchase_value(transactions) == [(date(2026, 11, 9), 150.96 * 500.0)]


def test_amf_value_reads_cached_notices(tmp_path, monkeypatch):
    cache = tmp_path / "amf.json"
    notices = [{"numero": "1", "issuer": "CAPGEMINI SE", "path": "a.pdf", "date": "2026-11-10"},
               {"numero": "2", "issuer": "TOTALENERGIES SE", "path": "b.pdf", "date": "2026-11-10"}]
    monkeypatch.setattr(insider_sources, "amf_notices", lambda: notices)
    pdf_text = (FIXTURES / "amf_notice.txt").read_text(encoding="utf-8")
    response = MagicMock(status_code=200, content=b"%PDF-1.7 fake")
    with patch.object(insider_sources, "_get", return_value=response) as fetch, \
         patch.object(insider_sources, "_pdf_text", return_value=pdf_text):
        value = insider_sources.amf_buy_value_eur(["Capgemini SE"], today=date(2026, 11, 11), cache_path=cache)
        assert fetch.call_count == 1  # only the notice of this company
        insider_sources._DISK_CACHES.clear()
        again = insider_sources.amf_buy_value_eur(["Capgemini SE"], today=date(2026, 11, 11), cache_path=cache)
        assert fetch.call_count == 1  # second time from the file cache
    assert value == again == pytest.approx(75480.0)
    assert "1" in json.loads(cache.read_text(encoding="utf-8"))


def test_amf_without_list_is_no_data(monkeypatch):
    monkeypatch.setattr(insider_sources, "amf_notices", lambda: None)
    assert insider_sources.amf_buy_value_eur(["Capgemini SE"]) is None


# ── Netherlands: AFM ────────────────────────────────────────────────────────

def test_afm_detail_page():
    page = (FIXTURES / "afm_detail.html").read_text(encoding="utf-8")
    detail = parse_afm_detail(page)
    assert detail["issuer"] == "ING Groep N.V." and detail["date"] == "2026-10-06"
    assert len(detail["transactions"]) == 4  # the aggregated table is not counted again
    assert "Anoniem" not in json.dumps(detail)  # the person's name is not stored
    assert afm_purchase_value(detail) == [(date(2026, 10, 6), 20.5 * 10000.0)]  # no option plan, no sale
    assert parse_afm_search(page) == ["2026100612345678-AAAA-BBBB-CCCC-123456789ABC"]


def test_afm_value_skips_old_ids_and_other_issuers(tmp_path):
    detail_page = (FIXTURES / "afm_detail.html").read_text(encoding="utf-8")
    search_page = ('<a href="x/details?id=20261006AAAA-1">a</a><a href="x/details?id=20250101BBBB-2">old</a>')
    responses = {"search": MagicMock(status_code=200, text=search_page), "detail": MagicMock(status_code=200, text=detail_page)}

    def fake_get(url, **kwargs):
        return responses["detail"] if url.endswith("/details") else responses["search"]

    with patch.object(insider_sources, "_get", side_effect=fake_get) as fetch:
        value = insider_sources.afm_buy_value_eur(["ING Groep N.V."], today=date(2026, 11, 1), cache_path=tmp_path / "afm.json")
        assert fetch.call_count == 2  # one search, one detail; the 2025 id is skipped by its date
        other = insider_sources.afm_buy_value_eur(["Adyen N.V."], today=date(2026, 11, 1), cache_path=tmp_path / "afm.json")
    assert value == 205000.0
    assert other == 0.0  # the cached notice belongs to ING, not to Adyen


# ── Germany: Tracefour API ──────────────────────────────────────────────────

def _tracefour_rows():
    return json.loads((FIXTURES / "tracefour_de.json").read_text(encoding="utf-8"))["data"]


def test_tracefour_keeps_euro_purchases_once():
    rows = _tracefour_rows() + [{"filingId": "x1", "issuerName": "AUMOVIO SE", "transactionNature": "Buy",
                                 "currency": "HKD", "totalValue": 5_000_000, "transactionDate": "2026-11-09"}]
    purchases = insider_sources.parse_tracefour_filings(rows)
    assert sorted(purchases) == ["aumovio", "uzin utz"]  # Cliq Digital only sold
    assert sum(value for _, value in purchases["aumovio"]) == pytest.approx(373908.85)  # duplicate and HKD left out


def test_tracefour_value_is_fetched_once_per_run(monkeypatch):
    response = MagicMock(status_code=200)
    response.json.return_value = {"data": _tracefour_rows()}
    fetch = MagicMock(return_value=response)
    monkeypatch.setattr(insider_sources, "_get", fetch)
    insider_sources._tracefour_purchases.cache_clear()
    aumovio = insider_sources.tracefour_buy_value_eur(["AUMOVIO SE"], today=date(2026, 11, 11))
    other = insider_sources.tracefour_buy_value_eur(["SAP SE"], today=date(2026, 11, 11))
    late = insider_sources.tracefour_buy_value_eur(["Uzin Utz SE"], today=date(2027, 3, 1))
    assert aumovio == pytest.approx(373908.85) and other == 0.0 and late == 0.0  # 90-day window
    assert fetch.call_count == 1
    assert fetch.call_args.args[0] == "https://tracefour.com/v1/eu/de"


@pytest.mark.parametrize("status, payload", [(429, {}), (200, {"data": []}), (200, {"error": "x"})])
def test_tracefour_down_or_empty_is_no_data(monkeypatch, status, payload):
    response = MagicMock(status_code=status)
    response.json.return_value = payload
    monkeypatch.setattr(insider_sources, "_get", MagicMock(return_value=response))
    insider_sources._tracefour_purchases.cache_clear()
    assert insider_sources.tracefour_buy_value_eur(["SAP SE"]) is None


def test_germany_falls_back_to_the_bafin_file(monkeypatch):
    monkeypatch.setattr(insider_sources, "tracefour_buy_value_eur", lambda names: None)
    monkeypatch.setattr(insider_sources, "bafin_buy_value_eur", lambda names: 100.0)
    assert insider_sources.insider_value_usd("SAP.DE", {"currency": "EUR"}) == (pytest.approx(110.0), "BaFin")
    monkeypatch.setattr(insider_sources, "bafin_buy_value_eur", lambda names: None)
    assert insider_sources.insider_value_usd("SAP.DE", {"currency": "EUR"}) == (None, None)


# ── one entry point per stock ───────────────────────────────────────────────

def test_each_market_uses_its_source(monkeypatch):
    monkeypatch.setattr(insider_sources, "tracefour_buy_value_eur", lambda names: 100.0)
    monkeypatch.setattr(insider_sources, "bafin_buy_value_eur", lambda names: 999.0)  # only a fallback
    monkeypatch.setattr(insider_sources, "six_buy_value_chf", lambda names: 100.0)
    monkeypatch.setattr(insider_sources, "amf_buy_value_eur", lambda names: 100.0)
    monkeypatch.setattr(insider_sources, "afm_buy_value_eur", lambda names: None)  # source down
    monkeypatch.setattr(insider_sources, "_yahoo_value", lambda symbol, known: 50.0 if known is None else known)
    assert insider_sources.insider_value_usd("SAP.DE", {"currency": "EUR"}) == (pytest.approx(110.0), "Tracefour")
    assert insider_sources.insider_value_usd("NOVN.SW", {"currency": "CHF"}) == (pytest.approx(120.0), "SIX")
    assert insider_sources.insider_value_usd("CAP.PA", {"currency": "EUR"}) == (pytest.approx(110.0), "AMF")
    assert insider_sources.insider_value_usd("INGA.AS", {"currency": "EUR"}) == (pytest.approx(55.0), "Yahoo")  # fallback
    assert insider_sources.insider_value_usd("HSBA.L", {"currency": "GBp"}, 1000.0) == (pytest.approx(1300.0), "Yahoo")  # pounds
    assert insider_sources.insider_value_usd("RY.TO", {"currency": "CAD"}, 0.0) == (0.0, "Yahoo")
    assert insider_sources.insider_value_usd("7203.T", {"currency": "JPY"}) == (None, None)  # no source in Japan
    assert insider_sources.insider_value_usd("INFY.NS", {"currency": "INR"}) == (None, None)  # NSE needs bot bypass


def test_a_crashing_source_counts_as_no_data(monkeypatch):
    def broken(names):
        raise RuntimeError("format changed")

    monkeypatch.setattr(insider_sources, "tracefour_buy_value_eur", broken)
    monkeypatch.setattr(insider_sources, "bafin_buy_value_eur", broken)
    assert insider_sources.insider_value_usd("SAP.DE", {"currency": "EUR"}) == (None, None)


def test_v3_factors_use_the_module_outside_the_us():
    import stock_agent

    with patch("insider_sources.insider_value_usd", return_value=(600.0, "BaFin")) as lookup, \
         patch("finnhub_cache.get_insider_buy_value", return_value=0.0):
        de = stock_agent.collect_v3_factors("SAP.DE", {"longName": "SAP SE"}, None, {}, {}, {"buy_value_usd": 5.0}, False)
        us = stock_agent.collect_v3_factors("AAPL", {}, None, {}, {}, {}, False)
        index = stock_agent.collect_v3_factors("^GSPC", {}, None, {}, {}, {}, False)
    assert (de["insider_buy_usd"], de["insider_source"]) == (600.0, "BaFin")
    lookup.assert_called_once_with("SAP.DE", {"longName": "SAP SE"}, 5.0)
    assert (us["insider_buy_usd"], us["insider_source"]) == (0.0, "Finnhub/Yahoo")
    assert (index["insider_buy_usd"], index["insider_source"]) == (None, None)


def test_conversion_to_usd():
    real = insider_sources.usd_per_unit.real
    real.cache_clear()
    fake = MagicMock()
    fake.history.return_value = pd.DataFrame({"Close": [1.25]})
    try:
        with patch("insider_sources.yf.Ticker", return_value=fake) as ticker:
            assert real("GBP") == 1.25
            ticker.assert_called_with("GBPUSD=X")
        assert real("USD") == 1.0
    finally:
        real.cache_clear()
    assert insider_sources.to_usd(0.0, "EUR") == 0.0
    assert insider_sources.to_usd(None, "EUR") is None
    assert insider_sources.to_usd(10.0, "XXX") is None  # unknown currency: no value instead of a wrong one

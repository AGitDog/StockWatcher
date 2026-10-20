import pandas as pd
import pytest
from unittest.mock import MagicMock, patch
from stock_agent import fetch_company_extended_fundamentals


def test_fetch_company_extended_fundamentals_gross_margin_and_valuation():
    mock_ticker = MagicMock()
    mock_ticker.get_info.return_value = {
        "longName": "Test Tech Corp",
        "sector": "Technology",
        "industry": "Software",
        "country": "Germany",
        "city": "Walldorf",
        "fullTimeEmployees": 100000,
        "marketCap": 200_000_000_000,
        "currency": "EUR",
        "trailingPE": 30.5,
        "forwardPE": 25.0,
        "pegRatio": 1.8,
        "grossMargins": 0.725,
        "operatingMargins": 0.284,
        "currentPrice": 200.0,
        "targetMeanPrice": 240.0,
        "targetMedianPrice": 235.0,
        "targetHighPrice": 280.0,
        "targetLowPrice": 190.0,
        "forwardEps": 8.0,
        "numberOfAnalystOpinions": 25,
        "dividendYield": 0.015,
        "dividendRate": 3.0,
        "payoutRatio": 0.4,
    }

    income_df = pd.DataFrame(
        {
            "2022-12-31": [100_000_000_000, 70_000_000_000, 40_000_000_000, 15_000_000_000, 25_000_000_000, 30_000_000_000, 5.0],
            "2023-12-31": [110_000_000_000, 78_000_000_000, 44_000_000_000, 17_000_000_000, 27_000_000_000, 34_000_000_000, 5.5],
            "2024-12-31": [120_000_000_000, 87_000_000_000, 48_000_000_000, 19_000_000_000, 29_000_000_000, 39_000_000_000, 6.2],
        },
        index=[
            "Total Revenue",
            "Gross Profit",
            "Operating Expense",
            "Research And Development",
            "Selling General And Administration",
            "Operating Income",
            "Diluted EPS",
        ],
    )
    mock_ticker.income_stmt = income_df
    mock_ticker.history.return_value = pd.DataFrame(
        {"Close": [150.0, 180.0, 200.0]},
        index=pd.to_datetime(["2022-12-31", "2023-12-31", "2024-12-31"]),
    )
    mock_ticker.dividends = pd.Series(
        [2.0, 2.5, 3.0],
        index=pd.to_datetime(["2022-05-15", "2023-05-15", "2024-05-15"]),
    )

    with patch("yfinance.Ticker", return_value=mock_ticker):
        result = fetch_company_extended_fundamentals("TEST.DE")

    assert result["symbol"] == "TEST.DE"
    assert result["name"] == "Test Tech Corp"
    assert result["gross_margin_ttm"] == 72.5
    assert len(result["gross_margin_history"]) == 3

    h0 = result["gross_margin_history"][0]
    assert h0["Jahr"] == 2022
    assert h0["Umsatz"] == 100_000_000_000
    assert h0["Bruttogewinn"] == 70_000_000_000
    assert h0["Bruttomarge"] == 70.0

    h2 = result["gross_margin_history"][2]
    assert h2["Jahr"] == 2024
    assert h2["Umsatz"] == 120_000_000_000
    assert h2["Bruttogewinn"] == 87_000_000_000
    assert h2["Bruttomarge"] == 72.5

    # Operating Cost assertions
    assert result["operating_margin_ttm"] == 28.4
    assert len(result["operating_cost_history"]) == 3
    oh2 = result["operating_cost_history"][2]
    assert oh2["Jahr"] == 2024
    assert oh2["OpEx"] == 48_000_000_000
    assert oh2["FE"] == 19_000_000_000
    assert oh2["SGA"] == 29_000_000_000
    assert oh2["Operativer_Gewinn"] == 39_000_000_000
    assert oh2["Operative_Marge"] == 32.5
    assert oh2["OpEx_Quote"] == 40.0
    assert oh2["FE_Quote"] == 15.83
    assert oh2["SGA_Quote"] == 24.17
    assert oh2["EBIT"] == 39_000_000_000

    assert result["current_price"] == 200.0
    assert result["target_mean_price"] == 240.0
    assert result["target_median_price"] == 235.0
    # Upside: (240 - 200) / 200 = +20.0%
    assert result["upside_pct"] == 20.0
    # Implied market cap: 200 Mrd * (240 / 200) = 240 Mrd
    assert result["implied_market_cap"] == 240_000_000_000
    assert result["forward_pe"] == 25.0
    assert result["analyst_count"] == 25


def test_fetch_company_extended_fundamentals_no_gross_profit_bank_or_etf():
    mock_ticker = MagicMock()
    mock_ticker.get_info.return_value = {
        "longName": "Global Bank AG",
        "sector": "Financial Services",
        "grossMargins": None,
        "operatingMargins": None,
        "currentPrice": 50.0,
        "marketCap": 50_000_000_000,
    }
    income_df = pd.DataFrame(
        {
            "2023-12-31": [30_000_000_000, 2.0],
            "2024-12-31": [35_000_000_000, 2.5],
        },
        index=["Total Revenue", "Diluted EPS"],
    )
    mock_ticker.income_stmt = income_df
    mock_ticker.history.return_value = pd.DataFrame()
    mock_ticker.dividends = pd.Series(dtype=float)

    with patch("yfinance.Ticker", return_value=mock_ticker):
        result = fetch_company_extended_fundamentals("BANK.DE")

    assert result["symbol"] == "BANK.DE"
    assert result["gross_margin_ttm"] is None
    assert result["operating_margin_ttm"] is None
    # No Gross Profit index row, so gross profit and margin are None
    assert len(result["gross_margin_history"]) == 2
    assert result["gross_margin_history"][0]["Bruttogewinn"] is None
    assert result["gross_margin_history"][0]["Bruttomarge"] is None
    # No OpEx index rows, so operating_cost_history is empty
    assert result["operating_cost_history"] == []
    assert result["target_mean_price"] is None
    assert result["upside_pct"] is None
    assert result["implied_market_cap"] is None


def test_fetch_company_extended_fundamentals_opex_partial_sga_only():
    mock_ticker = MagicMock()
    mock_ticker.get_info.return_value = {
        "longName": "Consumer Retail SE",
        "sector": "Consumer Defensive",
        "grossMargins": 0.35,
        "operatingMargins": 0.08,
    }
    income_df = pd.DataFrame(
        {
            "2024-12-31": [50_000_000_000, 17_500_000_000, 13_500_000_000, 13_500_000_000, 4_000_000_000],
        },
        index=[
            "Operating Revenue",
            "Gross Profit",
            "Operating Expense",
            "Selling General and Administrative",
            "Operating Income",
        ],
    )
    mock_ticker.income_stmt = income_df
    mock_ticker.history.return_value = pd.DataFrame()
    mock_ticker.dividends = pd.Series(dtype=float)

    with patch("yfinance.Ticker", return_value=mock_ticker):
        result = fetch_company_extended_fundamentals("RETAIL.DE")

    assert result["operating_margin_ttm"] == 8.0
    assert len(result["operating_cost_history"]) == 1
    oh = result["operating_cost_history"][0]
    assert oh["Jahr"] == 2024
    assert oh["OpEx"] == 13_500_000_000
    assert oh["FE"] is None
    assert oh["FE_Quote"] is None
    assert oh["SGA"] == 13_500_000_000
    assert oh["SGA_Quote"] == 27.0
    assert oh["Operativer_Gewinn"] == 4_000_000_000
    assert oh["EBIT"] == 4_000_000_000
    assert oh["Operative_Marge"] == 8.0


def test_fetch_company_extended_fundamentals_ebit_calculated_fallback():
    """Verify that EBIT is calculated as Gross Profit - OpEx when Operating Income row is missing."""
    mock_ticker = MagicMock()
    mock_ticker.get_info.return_value = {
        "longName": "Fallback Industrial SE",
        "operatingMargins": 0.20,
    }
    income_df = pd.DataFrame(
        {
            "2024-12-31": [40_000_000_000, 20_000_000_000, 12_000_000_000],
        },
        index=[
            "Total Revenue",
            "Gross Profit",
            "Operating Expense",
            # Operating Income is intentionally missing
        ],
    )
    mock_ticker.income_stmt = income_df
    mock_ticker.history.return_value = pd.DataFrame()
    mock_ticker.dividends = pd.Series(dtype=float)

    with patch("yfinance.Ticker", return_value=mock_ticker):
        result = fetch_company_extended_fundamentals("IND.DE")

    assert len(result["operating_cost_history"]) == 1
    oh = result["operating_cost_history"][0]
    assert oh["Jahr"] == 2024
    assert oh["OpEx"] == 12_000_000_000
    # EBIT = Gross Profit (20 Mrd) - OpEx (12 Mrd) = 8 Mrd
    assert oh["EBIT"] == 8_000_000_000
    assert oh["Operativer_Gewinn"] == 8_000_000_000
    # Operative Marge = 8 / 40 = 20.0%
    assert oh["Operative_Marge"] == 20.0



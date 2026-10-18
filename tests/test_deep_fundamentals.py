"""Tests for the new deep fundamentals and quality score features."""

import types
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch, PropertyMock
from typing import Any

import pandas as pd
import pytest


# ---------------------------------------------------------------------------
# Helper: build a minimal yfinance-like Ticker mock
# ---------------------------------------------------------------------------

def _make_ticker_mock(
    info: dict[str, Any] | None = None,
    income_stmt: pd.DataFrame | None = None,
    balance_sheet: pd.DataFrame | None = None,
    cashflow: pd.DataFrame | None = None,
):
    """Return a MagicMock that behaves like yf.Ticker for the tested helpers."""
    mock = MagicMock()
    mock.ticker = "AAPL"

    _info = info or {}
    mock.get_info.return_value = _info

    type(mock).income_stmt = PropertyMock(return_value=income_stmt)
    type(mock).balance_sheet = PropertyMock(return_value=balance_sheet)
    type(mock).cashflow = PropertyMock(return_value=cashflow)

    return mock


# ---------------------------------------------------------------------------
# _compute_cagr
# ---------------------------------------------------------------------------

class TestComputeCagr:
    def test_positive_growth(self):
        from stock_agent import _compute_cagr
        result = _compute_cagr(100, 200, 5)
        assert result is not None
        assert round(result, 2) == 14.87  # (200/100)^(1/5) - 1 = ~14.87%

    def test_no_growth(self):
        from stock_agent import _compute_cagr
        result = _compute_cagr(100, 100, 3)
        assert result is not None
        assert abs(result) < 0.01

    def test_negative_start(self):
        from stock_agent import _compute_cagr
        result = _compute_cagr(-50, 100, 5)
        assert result is None

    def test_zero_years(self):
        from stock_agent import _compute_cagr
        result = _compute_cagr(100, 200, 0)
        assert result is None

    def test_zero_start(self):
        from stock_agent import _compute_cagr
        result = _compute_cagr(0, 200, 3)
        assert result is None


# ---------------------------------------------------------------------------
# _extract_annual_financial_data
# ---------------------------------------------------------------------------

class TestExtractAnnualFinancialData:
    def _make_income_df(self):
        cols = [pd.Timestamp("2023-12-31"), pd.Timestamp("2024-12-31")]
        data = {
            cols[0]: [100_000, 60_000, 30_000, 20_000, 2.5, 5_000],
            cols[1]: [120_000, 75_000, 38_000, 28_000, 3.2, 6_000],
        }
        return pd.DataFrame(
            data,
            index=["Total Revenue", "Gross Profit", "EBIT", "Net Income", "Diluted EPS", "Interest Expense"],
        )

    def _make_balance_df(self):
        cols = [pd.Timestamp("2023-12-31"), pd.Timestamp("2024-12-31")]
        data = {
            cols[0]: [1_000_000, 500_000, 200_000, 50_000, 300_000],
            cols[1]: [1_100_000, 480_000, 220_000, 60_000, 340_000],
        }
        return pd.DataFrame(
            data,
            index=["Ordinary Shares Number", "Stockholders Equity", "Total Debt", "Cash And Cash Equivalents", "Total Assets"],
        )

    def _make_cashflow_df(self):
        cols = [pd.Timestamp("2023-12-31"), pd.Timestamp("2024-12-31")]
        data = {
            cols[0]: [50_000, -10_000, -5_000],
            cols[1]: [60_000, -12_000, -8_000],
        }
        return pd.DataFrame(
            data,
            index=["Operating Cash Flow", "Capital Expenditure", "Repurchase Of Capital Stock"],
        )

    def test_revenue_history_extracted(self):
        from stock_agent import _extract_annual_financial_data
        ticker = _make_ticker_mock(
            income_stmt=self._make_income_df(),
            balance_sheet=self._make_balance_df(),
            cashflow=self._make_cashflow_df(),
        )
        result = _extract_annual_financial_data(ticker)

        assert len(result["revenue_history"]) == 2
        assert result["revenue_history"][0]["Umsatz"] == 100_000
        assert result["revenue_history"][1]["Umsatz"] == 120_000

    def test_eps_history_extracted(self):
        from stock_agent import _extract_annual_financial_data
        ticker = _make_ticker_mock(
            income_stmt=self._make_income_df(),
            balance_sheet=self._make_balance_df(),
            cashflow=self._make_cashflow_df(),
        )
        result = _extract_annual_financial_data(ticker)

        assert len(result["eps_history"]) == 2
        assert result["eps_history"][0]["EPS"] == 2.5
        assert result["eps_history"][1]["EPS"] == 3.2

    def test_margin_trend_calculated(self):
        from stock_agent import _extract_annual_financial_data
        ticker = _make_ticker_mock(
            income_stmt=self._make_income_df(),
            balance_sheet=self._make_balance_df(),
            cashflow=self._make_cashflow_df(),
        )
        result = _extract_annual_financial_data(ticker)

        assert len(result["margin_trend"]) == 2
        # Gross margin for 2023: 60000 / 100000 = 0.6
        assert result["margin_trend"][0]["Brutto"] == 0.6
        # Operating margin for 2023: 30000 / 100000 = 0.3
        assert result["margin_trend"][0]["Operativ"] == 0.3

    def test_cashflow_history_fcf_computed(self):
        from stock_agent import _extract_annual_financial_data
        ticker = _make_ticker_mock(
            income_stmt=self._make_income_df(),
            balance_sheet=self._make_balance_df(),
            cashflow=self._make_cashflow_df(),
        )
        result = _extract_annual_financial_data(ticker)

        assert len(result["cashflow_history"]) == 2
        # FCF = OCF + CapEx = 50000 + (-10000) = 40000
        assert result["cashflow_history"][0]["FCF"] == 40_000
        assert result["cashflow_history"][1]["FCF"] == 48_000

    def test_shares_trend_extracted(self):
        from stock_agent import _extract_annual_financial_data
        ticker = _make_ticker_mock(
            income_stmt=self._make_income_df(),
            balance_sheet=self._make_balance_df(),
            cashflow=self._make_cashflow_df(),
        )
        result = _extract_annual_financial_data(ticker)

        assert len(result["shares_trend"]) == 2
        assert result["shares_trend"][0]["Aktien"] == 1_000_000
        assert result["shares_trend"][1]["Aktien"] == 1_100_000

    def test_empty_dataframes(self):
        from stock_agent import _extract_annual_financial_data
        ticker = _make_ticker_mock(
            income_stmt=pd.DataFrame(),
            balance_sheet=pd.DataFrame(),
            cashflow=pd.DataFrame(),
        )
        result = _extract_annual_financial_data(ticker)

        assert result["revenue_history"] == []
        assert result["eps_history"] == []
        assert result["margin_trend"] == []
        assert result["cashflow_history"] == []
        assert result["shares_trend"] == []

    def test_none_dataframes(self):
        from stock_agent import _extract_annual_financial_data
        ticker = _make_ticker_mock(
            income_stmt=None,
            balance_sheet=None,
            cashflow=None,
        )
        result = _extract_annual_financial_data(ticker)

        assert result["revenue_history"] == []
        assert result["cashflow_history"] == []
        assert result["shares_trend"] == []


# ---------------------------------------------------------------------------
# _summarize_quality_score
# ---------------------------------------------------------------------------

class TestSummarizeQualityScore:
    def _make_income_df(self):
        cols = [pd.Timestamp("2022-12-31"), pd.Timestamp("2023-12-31"), pd.Timestamp("2024-12-31")]
        data = {
            cols[0]: [80_000, 48_000, 24_000, 16_000, 2.0, 3_000],
            cols[1]: [100_000, 60_000, 30_000, 20_000, 2.5, 5_000],
            cols[2]: [120_000, 75_000, 38_000, 28_000, 3.2, 6_000],
        }
        return pd.DataFrame(
            data,
            index=["Total Revenue", "Gross Profit", "EBIT", "Net Income", "Diluted EPS", "Interest Expense"],
        )

    def _make_balance_df(self):
        cols = [pd.Timestamp("2022-12-31"), pd.Timestamp("2023-12-31"), pd.Timestamp("2024-12-31")]
        data = {
            cols[0]: [1_100_000, 500_000, 200_000, 50_000, 300_000],
            cols[1]: [1_050_000, 520_000, 210_000, 55_000, 320_000],
            cols[2]: [1_000_000, 540_000, 220_000, 60_000, 340_000],
        }
        return pd.DataFrame(
            data,
            index=["Ordinary Shares Number", "Stockholders Equity", "Total Debt", "Cash And Cash Equivalents", "Total Assets"],
        )

    def _make_cashflow_df(self):
        cols = [pd.Timestamp("2022-12-31"), pd.Timestamp("2023-12-31"), pd.Timestamp("2024-12-31")]
        data = {
            cols[0]: [40_000, -8_000, -4_000],
            cols[1]: [50_000, -10_000, -5_000],
            cols[2]: [60_000, -12_000, -8_000],
        }
        return pd.DataFrame(
            data,
            index=["Operating Cash Flow", "Capital Expenditure", "Repurchase Of Capital Stock"],
        )

    def test_high_quality_company(self):
        from stock_agent import _summarize_quality_score
        info = {
            "returnOnEquity": 0.25,       # 25% ROE -> +2
            "grossMargins": 0.65,          # 65% gross margin -> +2
            "totalDebt": 100_000,
            "totalCash": 80_000,
            "ebitda": 50_000,              # ND/EBITDA = 0.4 -> +2
            "freeCashflow": 45_000,
            "netIncomeToCommon": 30_000,    # FCF/NI = 1.5 -> +1
        }
        ticker = _make_ticker_mock(
            info=info,
            income_stmt=self._make_income_df(),
            balance_sheet=self._make_balance_df(),
            cashflow=self._make_cashflow_df(),
        )
        result = _summarize_quality_score(ticker, info)

        assert result["name"] == "Unternehmensqualitaet"
        assert result["score"] > 0
        assert "ROE" in result["summary"]
        assert "Bruttomarge" in result["summary"]

    def test_low_quality_company(self):
        from stock_agent import _summarize_quality_score

        # Low ROE, low margins, high leverage
        info = {
            "returnOnEquity": 0.02,        # 2% ROE -> -2
            "grossMargins": 0.15,           # 15% gross margin -> -2
            "totalDebt": 500_000,
            "totalCash": 10_000,
            "ebitda": 80_000,               # ND/EBITDA = 6.1 -> -2
            "freeCashflow": 5_000,
            "netIncomeToCommon": 10_000,     # FCF/NI = 0.5 -> no points
        }
        # Use income_stmt with declining revenue
        cols = [pd.Timestamp("2022-12-31"), pd.Timestamp("2024-12-31")]
        income_df = pd.DataFrame(
            {cols[0]: [120_000, 18_000, 6_000, 3_000, 0.5, 10_000],
             cols[1]: [100_000, 15_000, 5_000, 2_000, 0.3, 12_000]},
            index=["Total Revenue", "Gross Profit", "EBIT", "Net Income", "Diluted EPS", "Interest Expense"],
        )
        ticker = _make_ticker_mock(
            info=info,
            income_stmt=income_df,
            balance_sheet=pd.DataFrame(),
            cashflow=pd.DataFrame(),
        )
        result = _summarize_quality_score(ticker, info)

        assert result["score"] < 0
        assert "schwach" in result["summary"] or "dünn" in result["summary"] or "hoch" in result["summary"] or "schrumpfend" in result["summary"]

    def test_missing_data_returns_neutral(self):
        from stock_agent import _summarize_quality_score
        info = {}
        ticker = _make_ticker_mock(
            info=info,
            income_stmt=None,
            balance_sheet=None,
            cashflow=None,
        )
        result = _summarize_quality_score(ticker, info)

        assert result["name"] == "Unternehmensqualitaet"
        assert result["score"] == 0
        assert "nicht ausreichend" in result["summary"]

    def test_score_clamped(self):
        from stock_agent import _summarize_quality_score
        # All positive signals at maximum
        info = {
            "returnOnEquity": 0.50,
            "grossMargins": 0.80,
            "totalDebt": 10_000,
            "totalCash": 50_000,
            "ebitda": 100_000,
            "freeCashflow": 90_000,
            "netIncomeToCommon": 50_000,
        }
        ticker = _make_ticker_mock(
            info=info,
            income_stmt=self._make_income_df(),
            balance_sheet=self._make_balance_df(),
            cashflow=self._make_cashflow_df(),
        )
        result = _summarize_quality_score(ticker, info)

        assert result["score"] <= 10
        assert result["score"] >= -4

    def test_buyback_detection(self):
        from stock_agent import _summarize_quality_score
        # Shares declining by >2%
        cols = [pd.Timestamp("2023-12-31"), pd.Timestamp("2024-12-31")]
        balance_df = pd.DataFrame(
            {cols[0]: [1_000_000, 500_000, 100_000, 50_000, 300_000],
             cols[1]: [950_000, 520_000, 110_000, 55_000, 320_000]},  # 5% decline
            index=["Ordinary Shares Number", "Stockholders Equity", "Total Debt", "Cash And Cash Equivalents", "Total Assets"],
        )
        info = {}
        ticker = _make_ticker_mock(
            info=info,
            income_stmt=pd.DataFrame(),
            balance_sheet=balance_df,
            cashflow=pd.DataFrame(),
        )
        result = _summarize_quality_score(ticker, info)
        assert "Aktienrueckkauf" in result["summary"]


# ---------------------------------------------------------------------------
# fetch_company_extended_fundamentals – new fields presence
# ---------------------------------------------------------------------------

class TestFetchCompanyExtendedFundamentalsNewFields:
    """Verify that the extended function returns all new deep fundamental fields."""

    @patch("stock_agent.yf.Ticker")
    @patch("stock_agent.generate_german_company_summary", return_value="Test-Zusammenfassung")
    def test_new_fields_present_in_result(self, mock_summary, mock_ticker_cls):
        from stock_agent import fetch_company_extended_fundamentals
        # Clear lru_cache
        fetch_company_extended_fundamentals.cache_clear()

        # Setup mock
        ticker_instance = MagicMock()
        mock_ticker_cls.return_value = ticker_instance

        ticker_instance.get_info.return_value = {
            "longName": "Test Corp",
            "sector": "Technology",
            "industry": "Software",
            "country": "US",
            "city": "Cupertino",
            "currency": "USD",
            "marketCap": 1_000_000_000,
            "trailingPE": 25.0,
            "forwardPE": 20.0,
            "pegRatio": 1.5,
            "grossMargins": 0.65,
            "operatingMargins": 0.30,
            "profitMargins": 0.22,
            "returnOnEquity": 0.35,
            "returnOnAssets": 0.15,
            "totalDebt": 200_000_000,
            "totalCash": 100_000_000,
            "ebitda": 300_000_000,
            "currentRatio": 1.8,
            "quickRatio": 1.3,
            "operatingCashflow": 250_000_000,
            "freeCashflow": 200_000_000,
            "netIncomeToCommon": 180_000_000,
            "enterpriseToEbitda": 15.0,
            "enterpriseToRevenue": 5.0,
            "priceToBook": 8.0,
            "dividendYield": 0.015,
            "dividendRate": 1.5,
            "payoutRatio": 0.3,
            "sharesOutstanding": 5_000_000_000,
        }

        # Income statement
        cols = [pd.Timestamp("2023-12-31"), pd.Timestamp("2024-12-31")]
        income_df = pd.DataFrame(
            {cols[0]: [500_000_000, 325_000_000, 150_000_000, 110_000_000, 5.0, 10_000_000],
             cols[1]: [600_000_000, 390_000_000, 180_000_000, 132_000_000, 6.0, 12_000_000]},
            index=["Total Revenue", "Gross Profit", "EBIT", "Net Income", "Diluted EPS", "Interest Expense"],
        )
        type(ticker_instance).income_stmt = PropertyMock(return_value=income_df)

        # Balance sheet
        bs_df = pd.DataFrame(
            {cols[0]: [5_000_000_000, 400_000_000, 200_000_000, 100_000_000, 800_000_000],
             cols[1]: [4_800_000_000, 450_000_000, 180_000_000, 120_000_000, 850_000_000]},
            index=["Ordinary Shares Number", "Stockholders Equity", "Total Debt", "Cash And Cash Equivalents", "Total Assets"],
        )
        type(ticker_instance).balance_sheet = PropertyMock(return_value=bs_df)

        # Cashflow
        cf_df = pd.DataFrame(
            {cols[0]: [250_000_000, -50_000_000, -30_000_000],
             cols[1]: [300_000_000, -60_000_000, -40_000_000]},
            index=["Operating Cash Flow", "Capital Expenditure", "Repurchase Of Capital Stock"],
        )
        type(ticker_instance).cashflow = PropertyMock(return_value=cf_df)

        # Dividends (empty for simplicity)
        ticker_instance.dividends = pd.Series(dtype=float)

        # No history needed for pe_trend in this test
        ticker_instance.history.return_value = pd.DataFrame()

        result = fetch_company_extended_fundamentals("TEST")

        # Verify existing fields still present
        assert result["symbol"] == "TEST"
        assert result["name"] == "Test Corp"
        assert result["summary_de"] == "Test-Zusammenfassung"
        assert result["trailing_pe"] == 25.0

        # Verify NEW growth fields
        assert "revenue_history" in result
        assert "eps_history" in result
        assert "revenue_cagr_5y" in result
        assert "eps_cagr_5y" in result
        assert "fcf_cagr_5y" in result

        # Verify NEW profitability fields
        assert "gross_margin" in result
        assert result["gross_margin"] == 0.65
        assert "operating_margin" in result
        assert "net_margin" in result
        assert "margin_trend" in result
        assert "roe" in result
        assert result["roe"] == 0.35
        assert "roa" in result
        assert "roic" in result

        # Verify NEW balance sheet fields
        assert "net_debt" in result
        assert "net_debt_to_ebitda" in result
        assert "current_ratio" in result
        assert result["current_ratio"] == 1.8
        assert "quick_ratio" in result
        assert "interest_coverage" in result
        assert "debt_trend" in result

        # Verify NEW cashflow fields
        assert "operating_cashflow" in result
        assert "free_cashflow" in result
        assert "fcf_margin" in result
        assert "fcf_to_net_income" in result
        assert "capex_ratio" in result
        assert "cashflow_history" in result

        # Verify NEW shareholder return fields
        assert "buyback_yield" in result
        assert "shares_outstanding_trend" in result
        assert "total_payout_ratio" in result
        assert "dividend_cagr_5y" in result

        # Verify NEW valuation fields
        assert "ev_to_ebitda" in result
        assert result["ev_to_ebitda"] == 15.0
        assert "ev_to_revenue" in result
        assert "price_to_book" in result
        assert "earnings_yield" in result
        assert "pe_corridor" in result

        # Clean up cache
        fetch_company_extended_fundamentals.cache_clear()


# ---------------------------------------------------------------------------
# Quality signal integration in build_symbol_signal_monitor
# ---------------------------------------------------------------------------

class TestQualitySignalIntegration:
    """Ensure the quality signal is included as the 11th component."""

    @patch("stock_agent.yf.Ticker")
    @patch("stock_agent.resolve_symbol")
    @patch("stock_agent._apply_macro_overlay", side_effect=lambda x: x)
    def test_quality_signal_in_breakdown(self, mock_macro, mock_resolve, mock_ticker_cls):
        from stock_agent import build_symbol_signal_monitor

        mock_resolve.return_value = {"symbol": "TEST", "resolved": True, "note": "OK"}

        ticker_instance = MagicMock()
        mock_ticker_cls.return_value = ticker_instance
        ticker_instance.ticker = "TEST"

        ticker_instance.get_info.return_value = {
            "longName": "Test Corp",
            "quoteType": "EQUITY",
            "sector": "Technology",
            "industry": "Software",
        }
        ticker_instance.history.return_value = pd.DataFrame({
            "Close": [100.0] * 130,
            "Volume": [1_000_000] * 130,
            "High": [101.0] * 130,
            "Low": [99.0] * 130,
        }, index=pd.date_range("2024-01-01", periods=130))

        # Mock all the data-heavy attributes
        type(ticker_instance).income_stmt = PropertyMock(return_value=pd.DataFrame())
        type(ticker_instance).balance_sheet = PropertyMock(return_value=pd.DataFrame())
        type(ticker_instance).cashflow = PropertyMock(return_value=pd.DataFrame())
        ticker_instance.get_earnings_estimate.return_value = pd.DataFrame()
        ticker_instance.get_upgrades_downgrades.return_value = pd.DataFrame()
        ticker_instance.get_insider_purchases.return_value = pd.DataFrame()
        ticker_instance.get_insider_transactions.return_value = pd.DataFrame()
        ticker_instance.get_news.return_value = []
        ticker_instance.get_calendar.return_value = pd.DataFrame()

        result = build_symbol_signal_monitor("TEST", {})

        breakdown = result.get("signal_breakdown", {})
        assert "Unternehmensqualitaet" in breakdown
        assert breakdown["Unternehmensqualitaet"]["name"] == "Unternehmensqualitaet"
        # 11 total components
        assert len(breakdown) == 11


def test_deep_fundamentals_alias():
    from stock_agent import fetch_company_deep_fundamentals, fetch_company_extended_fundamentals
    assert fetch_company_deep_fundamentals is fetch_company_extended_fundamentals


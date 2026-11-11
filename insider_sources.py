"""Insider purchases outside the USA, from sources that may be used automatically.

- UK (.L): Yahoo's insider table, where purchases read "Bought at price ...".
- Germany (.DE): the BaFin "Directors' Dealings" CSV. BaFin's robots.txt forbids automated
  access, so the file is downloaded by hand in the browser and stored at ``BAFIN_CSV_PATH``.
  Without the file German stocks have no insider data, which the Rang-Score treats as neutral.

All values are converted to USD, because the Rang-Score threshold is 100,000 USD.
"""
from __future__ import annotations

import csv
import re
import unicodedata
from datetime import date, datetime, timedelta
from functools import lru_cache
from pathlib import Path

import pandas as pd
import yfinance as yf

BAFIN_CSV_PATH = Path(__file__).parent / "insider_data" / "bafin.csv"
INSIDER_WINDOW_DAYS = 90

_COMPANY_SUFFIXES = re.compile(
    r"\b(aktiengesellschaft|se|ag|kgaa|gmbh|co|kg|ug|nv|n v|sa|plc|inc|corp|corporation|holding|holdings|group|und|and|vz|st|i|ii)\b"
)


def is_open_market_buy(text: object) -> bool:
    """A purchase at the market: US wording "Purchase at price", UK wording "Bought at price".

    Company buybacks ("Buy Back at price"), awards, options and sales do not count.
    """
    value = str(text or "").strip().lower()
    if "buy back" in value or "buyback" in value:
        return False
    return value.startswith(("purchase", "bought", "buy"))


@lru_cache(maxsize=16)
def usd_per_unit(currency: str | None) -> float | None:
    """USD for one unit of ``currency`` (pence and other minor units are not accepted here)."""
    code = str(currency or "").upper()
    if code in ("", "USD"):
        return 1.0
    try:
        closes = yf.Ticker(f"{code}USD=X").history(period="5d")["Close"].dropna()
        return float(closes.iloc[-1]) if not closes.empty else None
    except Exception:
        return None


def to_usd(value: float | None, currency: str | None) -> float | None:
    if value is None:
        return None
    if value == 0:
        return 0.0
    rate = usd_per_unit(currency)
    return value * rate if rate else None


def normalize_company_name(name: object) -> str:
    """Comparable company name: lower case, no accents, no legal form ("SAP SE" -> "sap")."""
    text = unicodedata.normalize("NFKD", str(name or "")).encode("ascii", "ignore").decode("ascii").lower()
    text = re.sub(r"[^a-z0-9 ]+", " ", text.replace("&", " "))
    text = _COMPANY_SUFFIXES.sub(" ", text)
    return " ".join(text.split())


def _parse_german_number(text: str) -> float | None:
    """'267.450,00 EUR' -> 267450.0"""
    match = re.search(r"-?[\d.]+(?:,\d+)?", str(text or ""))
    if not match:
        return None
    try:
        return float(match.group(0).replace(".", "").replace(",", "."))
    except ValueError:
        return None


def _parse_german_date(text: str) -> date | None:
    try:
        return datetime.strptime(str(text or "").strip()[:10], "%d.%m.%Y").date()
    except ValueError:
        return None


@lru_cache(maxsize=4)
def load_bafin_purchases(path: str = str(BAFIN_CSV_PATH)) -> dict[str, list[tuple[date, float]]] | None:
    """Share purchases per normalised issuer name: [(trade date, value in EUR)]. None without file."""
    file = Path(path)
    if not file.exists():
        return None
    purchases: dict[str, list[tuple[date, float]]] = {}
    with file.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle, delimiter=";"):
            if str(row.get("Art des Geschäfts", "")).strip().lower() != "kauf":
                continue
            if str(row.get("Art des Instruments", "")).strip().lower() != "aktie":
                continue
            volume = str(row.get("Aggregiertes Volumen", ""))
            if "EUR" not in volume:
                continue  # other currencies are rare; skipping them only loses a bonus
            value = _parse_german_number(volume)
            day = _parse_german_date(row.get("Datum des Geschäfts", ""))
            if value is None or value <= 0 or day is None:
                continue
            purchases.setdefault(normalize_company_name(row.get("Emittent")), []).append((day, value))
    return purchases


def bafin_buy_value_eur(company_names: list[object], today: date | None = None,
                        days: int = INSIDER_WINDOW_DAYS, path: str = str(BAFIN_CSV_PATH)) -> float | None:
    """EUR value of insider share purchases of the last ``days`` days.

    None without a BaFin file. A company without a match counts as "no purchases" (0.0), which the
    Rang-Score rates neutral anyway, so a name mismatch can only lose a bonus, never cost points.
    """
    purchases = load_bafin_purchases(path)
    if purchases is None:
        return None
    today = today or date.today()
    start = today - timedelta(days=days)
    keys = {normalize_company_name(name) for name in company_names if name}
    keys.discard("")
    total = 0.0
    for key in keys:
        total += sum(value for day, value in purchases.get(key, []) if start <= day <= today)
    return total


def yahoo_buy_value(transactions: pd.DataFrame | None, days: int = INSIDER_WINDOW_DAYS) -> float | None:
    """Value of open-market purchases of the last ``days`` days in the currency of Yahoo's table.

    None means the table could not be loaded; an empty table means no purchases.
    """
    if transactions is None:
        return None
    if transactions.empty or not {"Text", "Value", "Start Date"} <= set(transactions.columns):
        return 0.0
    dates = pd.to_datetime(transactions["Start Date"], errors="coerce")
    recent = dates >= pd.Timestamp.now() - pd.Timedelta(days=days)
    bought = transactions["Text"].map(is_open_market_buy)
    return float(pd.to_numeric(transactions.loc[recent & bought, "Value"], errors="coerce").sum())

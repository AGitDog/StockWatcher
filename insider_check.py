"""Weekly live check of every insider data source.

Each source is asked for real data and the answer is parsed with the same code the nightly run
uses. A source that no longer answers, or whose format changed so that the parser finds nothing,
fails the check, so GitHub sends a mail before the Rang-Score silently loses its insider data.

Run: ``python insider_check.py`` (exit code 1 if a source is broken). The latest snapshot is
also checked: every market with a source should have insider data for some of its stocks.
"""
from __future__ import annotations

import csv
import gzip
import json
import os
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable

import insider_sources as sources

HISTORY_DIR = Path(__file__).parent / "signal_history" / "meine_watchlist"
BAFIN_MAX_AGE_DAYS = 21
# markets that have an automatic source: the snapshot must show it for at least one stock
EXPECTED_SOURCES = {"L": "Yahoo", "TO": "Yahoo", "SW": "SIX", "PA": "AMF", "AS": "AFM", "DE": "Tracefour"}


@dataclass
class Check:
    name: str
    ok: bool
    detail: str
    hard: bool = True  # a failed hard check fails the run; soft ones only warn


def _run(name: str, probe: Callable[[], tuple[bool, str]], hard: bool = True) -> Check:
    try:
        ok, detail = probe()
    except Exception as exc:  # a crash is a failed check, not a failed script
        ok, detail = False, f"{type(exc).__name__}: {exc}"
    return Check(name, ok, detail, hard)


def probe_tracefour() -> tuple[bool, str]:
    response = sources._get(sources.TRACEFOUR_DE_URL, headers={"Accept": "application/json"})
    if response.status_code != 200:
        return False, f"HTTP {response.status_code}"
    rows = response.json().get("data") or []
    needed = {"issuerName", "transactionNature", "currency", "totalValue", "transactionDate"}
    if not rows or not needed <= set(rows[0]):
        return False, f"{len(rows)} Meldungen, Felder fehlen: {sorted(needed - set(rows[0] if rows else {}))}"
    purchases = sources.parse_tracefour_filings(rows)
    return len(rows) >= 20 and bool(purchases), f"{len(rows)} Meldungen, {len(purchases)} Firmen mit Käufen"


def probe_six() -> tuple[bool, str]:
    response = sources._get(sources.SIX_URL, params={"fromDate": (date.today() - timedelta(days=60)).strftime("%Y%m%d"),
                                                     "pageSize": 3000}, timeout=60)
    if response.status_code != 200:
        return False, f"HTTP {response.status_code}"
    items = response.json().get("itemList") or []
    needed = {"ISIN", "buySellIndicator", "securityTypeCode", "transactionAmountCHF", "transactionDate", "notificationSubmitter"}
    if not items or not needed <= set(items[0]):
        return False, f"{len(items)} Meldungen, Felder fehlen: {sorted(needed - set(items[0] if items else {}))}"
    purchases = sources.parse_six_items(items)
    return len(items) >= 20, f"{len(items)} Meldungen in 60 Tagen, {len(purchases)} Firmen mit Käufen"


def probe_amf() -> tuple[bool, str]:
    notices = sources.amf_notices()
    if not notices:
        return False, "keine Meldungsliste"
    for notice in notices[:5]:
        response = sources._get(sources.AMF_DOCUMENT_URL + notice["path"], timeout=60)
        if response.status_code != 200 or not response.content.startswith(b"%PDF"):
            continue
        transactions = sources.parse_amf_notice(sources._pdf_text(response.content))
        if transactions and all(t["nature"] and t["instrument"] and t["price"] for t in transactions):
            return True, f"{len(notices)} Meldungen in 100 Tagen, PDF {notice['numero']} gelesen ({transactions[0]['nature']})"
    return False, f"{len(notices)} Meldungen, aber keines der 5 neuesten PDFs ließ sich auslesen (Format geändert?)"


def probe_afm() -> tuple[bool, str]:
    response = sources._get(sources.AFM_SEARCH_URL, params={"KeyWords": "ING Groep N.V."}, timeout=60)
    if response.status_code != 200:
        return False, f"HTTP {response.status_code}"
    ids = sources.parse_afm_search(response.text)
    if not ids:
        return False, "Suche liefert keine Meldungen (Format geändert?)"
    detail = sources.parse_afm_detail(sources._get(sources.AFM_SEARCH_URL + "/details", params={"id": ids[0]}).text)
    ok = bool(detail["issuer"] and detail["date"] and detail["transactions"] and detail["transactions"][0]["kind"])
    return ok, f"{len(ids)} Treffer für ING, Detail: {detail['issuer']} {detail['date']} {len(detail['transactions'])} Geschäfte"


def probe_yahoo() -> tuple[bool, str]:
    import yfinance as yf

    found = []
    for symbol in ("HSBA.L", "RY.TO", "SAN.MC"):
        table = yf.Ticker(symbol).get_insider_transactions()
        if table is not None and not table.empty and {"Text", "Value", "Start Date"} <= set(table.columns):
            found.append(f"{symbol} {len(table)}")
    return len(found) >= 2, "Tabellen: " + (", ".join(found) or "keine")


def probe_finnhub() -> tuple[bool, str]:
    import finnhub_cache

    if not finnhub_cache.get_finnhub_key():
        return True, "kein FINNHUB_API_KEY gesetzt, übersprungen"
    value = finnhub_cache.get_insider_buy_value("AAPL")
    return value is not None, "AAPL beantwortet" if value is not None else "keine Antwort für AAPL"


def probe_fx() -> tuple[bool, str]:
    sources.usd_per_unit.cache_clear()
    rates = {code: sources.usd_per_unit(code) for code in ("EUR", "GBP", "CHF", "CAD")}
    ok = all(rate and 0.3 < rate < 3 for rate in rates.values())
    return ok, ", ".join(f"{code} {rate:.3f}" if rate else f"{code} fehlt" for code, rate in rates.items())


def bafin_file_age(path: Path = sources.BAFIN_CSV_PATH, today: date | None = None) -> tuple[bool, str]:
    """Soft check: the hand-made BaFin file should be younger than three weeks."""
    if not path.exists():
        return True, "keine Datei (nur Ersatz, falls Tracefour ausfällt)"
    latest = None
    with path.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle, delimiter=";"):
            try:
                day = datetime.strptime(str(row.get("Mitteilungsdatum", ""))[:10], "%d.%m.%Y").date()
            except ValueError:
                continue
            latest = max(latest, day) if latest else day
    if latest is None:
        return False, "Datei ohne lesbare Meldungen"
    age = ((today or date.today()) - latest).days
    return age <= BAFIN_MAX_AGE_DAYS, f"neueste Meldung {latest.isoformat()} ({age} Tage alt)"


def snapshot_coverage(items: list[dict]) -> tuple[bool, str]:
    """Every market with a source shows it for at least one stock in the latest snapshot."""
    if not any("insider_source" in (item.get("factors_v3") or {}) for item in items):
        return True, "Snapshot noch ohne Quellenangabe (vor dem ersten Lauf mit neuem Code)"
    covered: dict[str, int] = {}
    total: dict[str, int] = {}
    for item in items:
        market = sources.market_of(item.get("symbol", ""))
        if market not in EXPECTED_SOURCES:
            continue
        total[market] = total.get(market, 0) + 1
        if (item.get("factors_v3") or {}).get("insider_source"):
            covered[market] = covered.get(market, 0) + 1
    missing = [market for market in total if not covered.get(market)]
    detail = ", ".join(f"{market} {covered.get(market, 0)}/{count}" for market, count in sorted(total.items()))
    return not missing, detail + (f" | ohne Daten: {', '.join(missing)}" if missing else "")


def latest_snapshot_items(directory: Path = HISTORY_DIR) -> list[dict]:
    files = sorted(directory.glob("*.json.gz"))
    if not files:
        return []
    data = json.load(gzip.open(files[-1], "rt", encoding="utf-8"))
    snapshot = data[0] if isinstance(data, list) else data
    return snapshot.get("items", []) if isinstance(snapshot, dict) else []


def run_checks() -> list[Check]:
    return [
        _run("Tracefour Deutschland", probe_tracefour),
        _run("SIX Schweiz", probe_six),
        _run("AMF Frankreich", probe_amf),
        _run("AFM Niederlande", probe_afm),
        _run("Yahoo (UK, Kanada, Spanien)", probe_yahoo),
        _run("Finnhub USA", probe_finnhub),
        _run("Wechselkurse", probe_fx),
        _run("BaFin-Datei", bafin_file_age, hard=False),
        _run("Abdeckung im letzten Snapshot", lambda: snapshot_coverage(latest_snapshot_items())),
    ]


def report(checks: list[Check]) -> str:
    lines = ["| Quelle | Ergebnis | Detail |", "|---|---|---|"]
    for check in checks:
        mark = "✅" if check.ok else ("❌" if check.hard else "⚠️")
        lines.append(f"| {check.name} | {mark} | {check.detail} |")
    return "\n".join(lines)


def main() -> int:
    checks = run_checks()
    text = report(checks)
    print(text)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as handle:
            handle.write("## Insider-Quellen\n\n" + text + "\n")
    return 1 if any(not check.ok and check.hard for check in checks) else 0


if __name__ == "__main__":
    sys.exit(main())

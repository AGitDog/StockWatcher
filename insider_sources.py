"""Insider purchases outside the USA, from sources that may be used automatically.

Only sources whose robots.txt allows the access are fetched automatically:

| Market | Source |
|---|---|
| UK, Canada, Spain, Australia, Italy, Finland, Belgium | Yahoo insider table |
| Switzerland | SIX Exchange Regulation, management transactions (JSON) |
| France | AMF BDIF, directors' dealings (JSON list + PDF per notice) |
| Netherlands | AFM register MAR 19 (HTML search + detail page) |
| Germany | BaFin CSV, downloaded by hand (BaFin's robots.txt forbids automated access) |

Japan and India have no usable free source: Japan publishes no director purchases, and the NSE
only answers with outdated data unless its bot protection is bypassed, which we do not do.

All values are converted to USD, because the Rang-Score threshold is 100,000 USD. Every fetch
fails soft: a broken source gives ``None`` (no data), which the Rang-Score rates neutral.
"""
from __future__ import annotations

import csv
import html as html_lib
import io
import json
import re
import threading
import time
import unicodedata
from datetime import date, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable

import pandas as pd
import requests
import yfinance as yf

DATA_DIR = Path(__file__).parent / "insider_data"
BAFIN_CSV_PATH = DATA_DIR / "bafin.csv"
AMF_CACHE_PATH = DATA_DIR / "amf_cache.json"
AFM_CACHE_PATH = DATA_DIR / "afm_cache.json"
INSIDER_WINDOW_DAYS = 90
REQUEST_PAUSE_SECONDS = 0.3  # be polite to the regulators' servers
USER_AGENT = "Mozilla/5.0 (compatible; StockWatcher research script)"
_BULK_LOCK = threading.Lock()  # the nightly run fetches stocks in threads; bulk lists load once
_CACHE_LOCK = threading.Lock()  # guards the on-disk caches of parsed notices
_DISK_CACHES: dict[str, dict] = {}

SIX_URL = "https://www.ser-ag.com/sheldon/management_transactions/v1/overview.json"
AMF_LIST_URL = "https://bdif.amf-france.org/back/api/v1/informations"
AMF_DOCUMENT_URL = "https://bdif.amf-france.org/back/api/v1/documents/"
AFM_SEARCH_URL = "https://www.afm.nl/nl-nl/sector/registers/meldingenregisters/transacties-leidinggevenden-mar19-"

YAHOO_MARKETS = {"L", "TO", "V", "MC", "AX", "MI", "HE", "BR", "ST", "CO", "OL", "VI", "LS", "IR"}
MINOR_UNITS = {"GBp": ("GBP", 100), "GBX": ("GBP", 100), "ILA": ("ILS", 100), "ZAc": ("ZAR", 100)}
NO_SOURCE_MARKETS = {"T": "Japan", "NS": "Indien", "BO": "Indien"}

_COMPANY_SUFFIXES = re.compile(
    r"\b(aktiengesellschaft|se|ag|kgaa|gmbh|co|kg|ug|nv|n v|sa|s a|plc|inc|corp|corporation|ltd|limited|"
    r"holding|holdings|group|groupe|groep|und|and|et|vz|st|i|ii)\b"
)
_EXCLUDED_CONDITIONS = re.compile(
    r"exer|vest|rsu|option|employee|mitarbeit|ausübung|ausubung|zuteilung|dividend|grant|award|plan d|lti|psu",
    re.IGNORECASE,
)


# ── shared helpers ───────────────────────────────────────────────────────────

def is_open_market_buy(text: object) -> bool:
    """A purchase at the market in the wording of Yahoo's insider table.

    US "Purchase at price", UK/EU "Bought at price", Canada (SEDI) "Acquisition in the public market".
    Company buybacks, awards, option exercises, plan purchases and sales do not count.
    """
    value = str(text or "").strip().lower()
    if "buy back" in value or "buyback" in value:
        return False
    if value.startswith("acquisition in the public market"):
        return True
    return value.startswith(("purchase", "bought", "buy"))


def normalize_company_name(name: object) -> str:
    """Comparable company name: lower case, no accents, no legal form ("SAP SE" -> "sap")."""
    text = unicodedata.normalize("NFKD", str(name or "")).encode("ascii", "ignore").decode("ascii").lower()
    text = re.sub(r"[^a-z0-9 ]+", " ", text.replace("&", " "))
    text = _COMPANY_SUFFIXES.sub(" ", text)
    return " ".join(text.split())


def names_match(a: str, b: str) -> bool:
    """Normalised names are equal, or one is the other plus extra words ("roche" / "roche"),
    as long as the shorter name is distinctive enough (at least 5 letters)."""
    if not a or not b:
        return False
    if a == b:
        return True
    short, long_ = sorted((a, b), key=len)
    return len(short) >= 5 and (long_.startswith(short + " ") or long_.endswith(" " + short))


def _keys(company_names: list[object]) -> set[str]:
    return {key for key in (normalize_company_name(name) for name in company_names if name) if key}


def _matching(table: dict[str, list[tuple[date, float]]], company_names: list[object]) -> list[tuple[date, float]]:
    keys = _keys(company_names)
    rows: list[tuple[date, float]] = []
    for issuer, purchases in table.items():
        if any(names_match(issuer, key) for key in keys):
            rows.extend(purchases)
    return rows


def _window_sum(rows: list[tuple[date, float]], today: date | None, days: int) -> float:
    today = today or date.today()
    start = today - timedelta(days=days)
    return float(sum(value for day, value in rows if start <= day <= today))


def _get(url: str, **kwargs: Any) -> requests.Response:
    time.sleep(REQUEST_PAUSE_SECONDS)
    headers = {"User-Agent": USER_AGENT, **kwargs.pop("headers", {})}
    return requests.get(url, headers=headers, timeout=kwargs.pop("timeout", 30), **kwargs)


@lru_cache(maxsize=16)
def usd_per_unit(currency: str | None) -> float | None:
    """USD for one unit of a main currency (GBP, EUR, CHF ...)."""
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


def _parse_number(text: object) -> float | None:
    """Numbers in German/French/Dutch ('267.450,00') and English ('8.7200') notation."""
    raw = re.sub(r"[^\d.,\-]", "", str(text or ""))
    if not raw or not re.search(r"\d", raw):
        return None
    if "," in raw and "." in raw:
        raw = raw.replace(".", "").replace(",", ".") if raw.rfind(",") > raw.rfind(".") else raw.replace(",", "")
    elif "," in raw:
        raw = raw.replace(".", "").replace(",", ".") if re.search(r",\d{1,2}$", raw) else raw.replace(",", "")
    try:
        return float(raw)
    except ValueError:
        return None


def _load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_json(path: Path, data: dict) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    except Exception:
        pass  # a read-only checkout only loses the cache


def _cache_get(path: Path, key: str) -> Any:
    with _CACHE_LOCK:
        cache = _DISK_CACHES.setdefault(str(path), _load_json(path))
        return cache.get(key)


def _cache_put(path: Path, key: str, value: dict, keep_from: str) -> None:
    """Store one parsed notice and write the file, dropping notices older than ``keep_from``."""
    with _CACHE_LOCK:
        cache = _DISK_CACHES.setdefault(str(path), _load_json(path))
        cache[key] = value
        for old in [k for k, v in cache.items() if (v.get("date") or "") < keep_from]:
            del cache[old]
        _save_json(path, cache)


# ── Yahoo ────────────────────────────────────────────────────────────────────

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


def _yahoo_value(symbol: str, known_value: float | None) -> float | None:
    if known_value is not None:
        return known_value
    try:
        return yahoo_buy_value(yf.Ticker(symbol).get_insider_transactions())
    except Exception:
        return None


# ── Germany: BaFin CSV stored by hand ───────────────────────────────────────

def _parse_german_date(text: object) -> date | None:
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
            value = _parse_number(volume)
            day = _parse_german_date(row.get("Datum des Geschäfts", ""))
            if value is None or value <= 0 or day is None:
                continue
            purchases.setdefault(normalize_company_name(row.get("Emittent")), []).append((day, value))
    return purchases


def bafin_buy_value_eur(company_names: list[object], today: date | None = None,
                        days: int = INSIDER_WINDOW_DAYS, path: str = str(BAFIN_CSV_PATH)) -> float | None:
    """EUR value of insider share purchases. None without a BaFin file; no match counts as 0."""
    purchases = load_bafin_purchases(path)
    if purchases is None:
        return None
    return _window_sum(_matching(purchases, company_names), today, days)


# ── Switzerland: SIX management transactions ───────────────────────────────

def parse_six_items(items: list[dict]) -> dict[str, list[tuple[date, float]]]:
    """Share purchases per issuer from SIX records: [(trade date, CHF)].

    Kept: buy indicator 1, security type 7 (shares), a natural person (not a related legal entity),
    no option exercise / vesting / employee plan in the conditions, corrected notices replaced.
    """
    corrected = {str(item.get("correcteeId")) for item in items if item.get("correcteeId")}
    seen: set[tuple] = set()
    purchases: dict[str, list[tuple[date, float]]] = {}
    for item in items:
        if str(item.get("notificationId")) in corrected:
            continue  # a later notice corrected this one
        if str(item.get("buySellIndicator")) != "1" or str(item.get("securityTypeCode")) != "7":
            continue
        if str(item.get("obligorRelatedPartyInd") or "").upper() == "L":
            continue  # a related company, usually a corporate deal rather than a manager's own money
        if _EXCLUDED_CONDITIONS.search(str(item.get("transactionConditions") or "")):
            continue
        amount = item.get("transactionAmountCHF")
        try:
            day = datetime.strptime(str(item.get("transactionDate")), "%Y%m%d").date()
            amount = float(amount)
        except (TypeError, ValueError):
            continue
        key = (item.get("ISIN"), day, amount, item.get("transactionSize"))
        if amount <= 0 or key in seen:
            continue  # the same trade reported twice
        seen.add(key)
        purchases.setdefault(normalize_company_name(item.get("notificationSubmitter")), []).append((day, amount))
    return purchases


def six_purchases(days: int = INSIDER_WINDOW_DAYS + 10) -> dict[str, list[tuple[date, float]]] | None:
    """All Swiss management purchases of the last ``days`` days, fetched once per run."""
    with _BULK_LOCK:
        return _six_purchases(days)


@lru_cache(maxsize=1)
def _six_purchases(days: int) -> dict[str, list[tuple[date, float]]] | None:
    start = (date.today() - timedelta(days=days)).strftime("%Y%m%d")
    items: list[dict] = []
    try:
        for page in range(10):
            response = _get(SIX_URL, params={"fromDate": start, "pageSize": 3000, "pageNumber": page}, timeout=60)
            if response.status_code != 200:
                return None
            data = response.json()
            batch = data.get("itemList") or []
            items.extend(batch)
            if not batch or len(items) >= int(data.get("totalCount") or 0):
                break
    except Exception:
        return None
    return parse_six_items(items)


def six_buy_value_chf(company_names: list[object], today: date | None = None) -> float | None:
    purchases = six_purchases()
    if purchases is None:
        return None
    return _window_sum(_matching(purchases, company_names), today, INSIDER_WINDOW_DAYS)


# ── France: AMF BDIF ────────────────────────────────────────────────────────

_FRENCH_MONTHS = {"janvier": 1, "fevrier": 2, "mars": 3, "avril": 4, "mai": 5, "juin": 6, "juillet": 7,
                  "aout": 8, "septembre": 9, "octobre": 10, "novembre": 11, "decembre": 12}


def _plain(text: str) -> str:
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")


def _french_date(text: str) -> date | None:
    match = re.search(r"(\d{1,2})\s+([a-z]+)\s+(\d{4})", _plain(text).lower())
    if not match or match.group(2) not in _FRENCH_MONTHS:
        return None
    try:
        return date(int(match.group(3)), _FRENCH_MONTHS[match.group(2)], int(match.group(1)))
    except ValueError:
        return None


def parse_amf_notice(text: str) -> list[dict]:
    """Transactions of one AMF notice (French part of the PDF text).

    Returns [{"date", "nature", "instrument", "options", "price", "volume", "currency"}].
    """
    plain = _plain(text)
    french = re.split(r"\n\s*Individual notification", plain, maxsplit=1)[0]
    blocks = re.split(r"DETAIL DE LA TRANSACTION", french)[1:]
    transactions = []
    for block in blocks:
        def field(label: str) -> str:
            match = re.search(label + r"\s*:\s*(.+)", block)
            return match.group(1).strip() if match else ""

        aggregated = block.split("INFORMATIONS AGREGEES", 1)[-1]
        price_match = re.search(r"PRIX\s*:\s*([\d.,\s]+)\s*([A-Za-z]+)", aggregated)
        volume_match = re.search(r"VOLUME\s*:\s*([\d.,\s]+)", aggregated)
        options = re.search(r"ACTIONS GRATUITES OU DE PERFORMANCES\s*:\s*(OUI|NON)", block)
        transactions.append({
            "date": (_french_date(field("DATE DE LA TRANSACTION")) or date.min).isoformat(),
            "nature": field("NATURE DE LA TRANSACTION").lower(),
            "instrument": field("DESCRIPTION DE L.?INSTRUMENT FINANCIER").lower(),
            "options": (options.group(1) == "OUI") if options else False,
            "price": _parse_number(price_match.group(1)) if price_match else None,
            "volume": _parse_number(volume_match.group(1)) if volume_match else None,
            "currency": (price_match.group(2) if price_match else "").lower(),
        })
    return transactions


def amf_purchase_value(transactions: list[dict]) -> list[tuple[date, float]]:
    """EUR value of plain share acquisitions (no options, no free shares)."""
    rows = []
    for item in transactions:
        if item.get("nature") != "acquisition" or item.get("options"):
            continue
        if not str(item.get("instrument", "")).startswith("action"):
            continue
        if item.get("currency") not in ("euro", "eur", "euros") or not item.get("price") or not item.get("volume"):
            continue
        try:
            day = date.fromisoformat(item["date"])
        except (KeyError, ValueError):
            continue
        rows.append((day, float(item["price"]) * float(item["volume"])))
    return rows


def amf_notices(days: int = INSIDER_WINDOW_DAYS + 10) -> list[dict] | None:
    """Directors' dealings notices of the last ``days`` days: [{"numero", "issuer", "path", "date"}]."""
    with _BULK_LOCK:
        return _amf_notices(days)


@lru_cache(maxsize=1)
def _amf_notices(days: int) -> list[dict] | None:
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    notices: list[dict] = []
    try:
        for start in range(0, 5000, 200):
            response = _get(AMF_LIST_URL, params={"TypesInformation": "DD", "From": start, "Size": 200}, timeout=60)
            if response.status_code != 200:
                return None
            results = response.json().get("result") or []
            for result in results:
                documents = [doc for doc in result.get("documents") or [] if str(doc.get("path", "")).endswith(".pdf")]
                issuers = [s.get("raisonSociale") for s in result.get("societes") or [] if s.get("raisonSociale")]
                if documents and issuers:
                    notices.append({"numero": result.get("numero"), "issuer": issuers[0], "path": documents[0]["path"],
                                    "date": str(result.get("dateInformation", ""))[:10]})
            if not results or str(results[-1].get("dateInformation", ""))[:10] < cutoff:
                break
    except Exception:
        return None
    return [notice for notice in notices if notice["date"] >= cutoff]


def _pdf_text(content: bytes) -> str:
    from pypdf import PdfReader

    return "\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(content)).pages)


def amf_buy_value_eur(company_names: list[object], today: date | None = None,
                      cache_path: Path = AMF_CACHE_PATH) -> float | None:
    """EUR value of French directors' share purchases. Parsed notices are cached on disk."""
    notices = amf_notices()
    if notices is None:
        return None
    keys = _keys(company_names)
    relevant = [n for n in notices if any(names_match(normalize_company_name(n["issuer"]), key) for key in keys)]
    keep_from = (date.today() - timedelta(days=INSIDER_WINDOW_DAYS + 30)).isoformat()
    rows: list[tuple[date, float]] = []
    for notice in relevant:
        numero = str(notice["numero"])
        parsed = _cache_get(cache_path, numero)
        if parsed is None:
            try:
                response = _get(AMF_DOCUMENT_URL + notice["path"], timeout=60)
                if response.status_code != 200 or not response.content.startswith(b"%PDF"):
                    continue
                parsed = {"date": notice["date"], "transactions": parse_amf_notice(_pdf_text(response.content))}
            except Exception:
                continue
            _cache_put(cache_path, numero, parsed, keep_from)
        rows.extend(amf_purchase_value(parsed["transactions"]))
    return _window_sum(rows, today, INSIDER_WINDOW_DAYS)


# ── Netherlands: AFM register MAR 19 ────────────────────────────────────────

def parse_afm_search(page: str) -> list[str]:
    """Detail ids of a search result page (newest first, at most 50)."""
    ids = re.findall(r"details\?id=([0-9A-Fa-f\-]+)", page)
    return list(dict.fromkeys(ids))


def parse_afm_detail(page: str) -> dict:
    """Issuer, trade date and transactions of one AFM notice.

    Transactions: [{"kind", "nature", "options", "price", "volume", "unit"}]; "Aankoop" is a purchase.
    """
    def text(fragment: str) -> str:
        return " ".join(html_lib.unescape(re.sub(r"<[^>]+>", " ", fragment)).split())

    # header fields: <span class="..label">Label</span> <span class="..value"><span>Value</span></span>
    fields = {
        text(label): text(value)
        for label, value in re.findall(
            r'detail-list__label">(.*?)</span>\s*<span class="cc-em--detail-list__value">(.*?)</span>\s*</div>', page, flags=re.S)
    }
    trade_date = None
    months = {"mrt": "mar", "mei": "may", "okt": "oct"}
    raw_date = " ".join(months.get(part, part) for part in fields.get("Transactiedatum", "").lower().split())
    for fmt in ("%d %b %Y", "%d-%m-%Y", "%Y-%m-%d"):
        try:
            trade_date = datetime.strptime(raw_date, fmt).date()
            break
        except ValueError:
            continue

    # only the table of single transactions; the aggregated table below repeats them
    section = page.split(">Transacties<", 1)[-1].split("Geaggregeerde informatie", 1)[0]
    transactions = []
    for row in re.findall(r"<tr>(.*?)</tr>", section, flags=re.S):
        cells = dict(
            (text(label), text(value))
            for label, value in re.findall(r'<td>\s*<span class="cc-mobile-title">(.*?)</span>(.*?)</td>', row, flags=re.S)
        )
        if not cells:
            continue  # the header row has <th> cells only
        transactions.append({
            "instrument": cells.get("Type instrument", "").lower(),
            "nature": cells.get("Aard transactie", "").lower(),
            "kind": cells.get("Soort transactie", "").lower(),
            "options": cells.get("Aandelenoptie programma", "").lower() == "ja",
            "price": _parse_number(cells.get("Prijs")),
            "volume": _parse_number(cells.get("Aantal")),
            "unit": cells.get("Eenheid", "").upper(),
        })
    return {"issuer": fields.get("Uitgevende instelling", ""), "date": trade_date.isoformat() if trade_date else None,
            "transactions": transactions}


def afm_purchase_value(detail: dict) -> list[tuple[date, float]]:
    """EUR value of plain share purchases of one notice."""
    if not detail.get("date"):
        return []
    day = date.fromisoformat(detail["date"])
    rows = []
    for item in detail.get("transactions") or []:
        if item.get("kind") not in ("koop", "aankoop") or item.get("options"):
            continue
        if "aandeel" not in str(item.get("instrument")) or item.get("unit") not in ("EUR", ""):  # "" = EUR not repeated
            continue
        if item.get("price") and item.get("volume"):
            rows.append((day, float(item["price"]) * float(item["volume"])))
    return rows


def afm_buy_value_eur(company_names: list[object], today: date | None = None,
                      cache_path: Path = AFM_CACHE_PATH) -> float | None:
    """EUR value of Dutch managers' share purchases. Details are cached on disk."""
    keys = sorted(_keys(company_names), key=len)
    search_name = next((str(name) for name in company_names if name), "")
    if not keys or not search_name:
        return None
    try:
        # the full name, because a short key like "ing" matches almost every notice
        response = _get(AFM_SEARCH_URL, params={"KeyWords": search_name}, timeout=60)
        if response.status_code != 200:
            return None
        ids = parse_afm_search(response.text)
    except Exception:
        return None
    cutoff = ((today or date.today()) - timedelta(days=INSIDER_WINDOW_DAYS)).isoformat()
    keep_from = (date.today() - timedelta(days=INSIDER_WINDOW_DAYS + 30)).isoformat()
    rows: list[tuple[date, float]] = []
    for detail_id in ids:
        if detail_id[:8].isdigit() and f"{detail_id[:4]}-{detail_id[4:6]}-{detail_id[6:8]}" < cutoff:
            continue  # the id starts with the notice date
        detail = _cache_get(cache_path, detail_id)
        if detail is None:
            try:
                detail_page = _get(AFM_SEARCH_URL + "/details", params={"id": detail_id}, timeout=60)
                if detail_page.status_code != 200:
                    continue
                detail = parse_afm_detail(detail_page.text)
            except Exception:
                continue
            _cache_put(cache_path, detail_id, detail, keep_from)
        if any(names_match(normalize_company_name(detail.get("issuer")), key) for key in keys):
            rows.extend(afm_purchase_value(detail))
    return _window_sum(rows, today, INSIDER_WINDOW_DAYS)


# ── one entry point per stock ───────────────────────────────────────────────

def market_of(symbol: str) -> str:
    """Yahoo suffix ("L", "DE" ...) or "US" for symbols without one."""
    text = str(symbol or "").upper()
    if "." not in text or text.startswith("^"):
        return "US"
    suffix = text.rsplit(".", 1)[1]
    return "US" if suffix in ("A", "B") else suffix  # BRK.B is a US share class


def insider_value_usd(symbol: str, info: dict, yahoo_value: float | None = None) -> tuple[float | None, str | None]:
    """Insider purchases of the last 90 days in USD and the source used, for non-US stocks.

    ``yahoo_value`` is the value already read from Yahoo's table (currency of the table).
    Returns (None, None) where no source exists.
    """
    market = market_of(symbol)
    names = [info.get("longName"), info.get("shortName")]
    quote_currency = str(info.get("currency") or "")
    main_currency = MINOR_UNITS.get(quote_currency, (quote_currency, 1))[0] or None
    sources: dict[str, tuple[str, Callable[[], float | None], str | None]] = {
        "DE": ("BaFin", lambda: bafin_buy_value_eur(names), "EUR"),
        "SW": ("SIX", lambda: six_buy_value_chf(names), "CHF"),
        "PA": ("AMF", lambda: amf_buy_value_eur(names), "EUR"),
        "AS": ("AFM", lambda: afm_buy_value_eur(names), "EUR"),
    }
    if market in sources:
        name, fetch, currency = sources[market]
        try:
            value = fetch()
        except Exception:
            value = None
        if value is not None:
            return to_usd(value, currency), name
    if market in YAHOO_MARKETS or market in ("PA", "AS", "SW"):  # Yahoo as fallback where it has data
        value = _yahoo_value(symbol, yahoo_value)
        if value is not None:
            return to_usd(value, main_currency), "Yahoo"
    return None, None

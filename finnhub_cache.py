import json
import threading
import time
from collections import deque

import requests
from pathlib import Path
from typing import Any

from config_loader import get_secret

CACHE_DIR = Path("cache")
CACHE_FILE = CACHE_DIR / "finnhub_targets.json"
CACHE_TTL = 24 * 60 * 60  # 24 hours in seconds

# The free plan allows 60 calls per minute. Without a brake, parallel runs exceeded it and
# some stocks got Finnhub data while others silently fell back to Yahoo.
MAX_CALLS_PER_MINUTE = 55
_call_times: deque[float] = deque()
_rate_lock = threading.Lock()


def wait_for_rate_limit(clock=time.monotonic, sleep=time.sleep, limit: int = MAX_CALLS_PER_MINUTE) -> None:
    """Block until another call fits into the last 60 seconds."""
    while True:
        with _rate_lock:
            now = clock()
            while _call_times and now - _call_times[0] >= 60:
                _call_times.popleft()
            if len(_call_times) < limit:
                _call_times.append(now)
                return
            wait = 60 - (now - _call_times[0]) + 0.05
        sleep(wait)


def _get(url: str, **kwargs):
    wait_for_rate_limit()
    return requests.get(url, **kwargs)

def get_finnhub_key() -> str:
    """Holt den Finnhub API Key aus Streamlit secrets, Umgebungsvariablen oder .env."""
    api_key = get_secret("finnhub", "api_key")
    if api_key:
        return str(api_key)
    return ""


def _load_cache() -> dict[str, Any]:
    if not CACHE_FILE.exists():
        return {}
    try:
        content = CACHE_FILE.read_text(encoding="utf-8")
        return json.loads(content)
    except Exception:
        return {}

def _save_cache(cache_data: dict[str, Any]) -> None:
    CACHE_DIR.mkdir(exist_ok=True, parents=True)
    try:
        CACHE_FILE.write_text(json.dumps(cache_data, indent=2), encoding="utf-8")
    except Exception:
        pass

def get_recommendations(symbol: str) -> list[dict[str, Any]]:
    """Analyst recommendation trends from Finnhub, cached for 24 hours.

    Price targets are not fetched: the free plan answers them with 403. They come from Yahoo.
    Returns [] when the key is missing or the call fails.
    """
    api_key = get_finnhub_key()
    if not api_key:
        return []

    cache_data = _load_cache()
    now = time.time()
    
    # Check cache validity
    symbol_data = cache_data.get(symbol)
    if symbol_data and (now - symbol_data.get("timestamp", 0)) < CACHE_TTL:
        return symbol_data.get("recommendation", [])

    recommendation = []
    try:
        rec_url = f"https://finnhub.io/api/v1/stock/recommendation?symbol={symbol}&token={api_key}"
        res_rec = _get(rec_url, timeout=10)
        if res_rec.status_code == 200:
            recommendation = res_rec.json()
            
    except Exception as e:
        print(f"Finnhub API Error for {symbol}: {e}")
        return []

    if recommendation:
        cache_data[symbol] = {"timestamp": now, "recommendation": recommendation}
        _save_cache(cache_data)
    return recommendation
def get_insider_buy_value(symbol: str, days: int = 90) -> float | None:
    """Value in USD of open-market purchases (Form 4 code P) of the last ``days`` days.

    Returns None when the API gives no answer, so a failed call is not read as "no purchases".
    """
    api_key = get_finnhub_key()
    if not api_key:
        return None
    start = time.strftime("%Y-%m-%d", time.gmtime(time.time() - days * 86400))
    try:
        res = _get(
            "https://finnhub.io/api/v1/stock/insider-transactions",
            params={"symbol": symbol, "from": start, "token": api_key},
            timeout=10,
        )
        if res.status_code != 200:
            return None
        rows = res.json().get("data") or []
    except Exception:
        return None
    return float(sum(
        abs(row.get("change") or 0) * (row.get("transactionPrice") or 0)
        for row in rows
        if row.get("transactionCode") == "P"
    ))


def get_insider_sentiment(symbol: str) -> list[dict[str, Any]]:
    """
    Holt Insider Sentiment von Finnhub.
    Returns: list of sentiment dicts (empty if no data or error).
    """
    api_key = get_finnhub_key()
    if not api_key:
        return []

    cache_data = _load_cache()
    now = time.time()
    
    symbol_data = cache_data.get(symbol)
    if symbol_data and "insider" in symbol_data and (now - symbol_data.get("timestamp_insider", 0)) < 12 * 60 * 60:
        return symbol_data.get("insider", [])

    insider_data = []
    try:
        url = f"https://finnhub.io/api/v1/stock/insider-sentiment?symbol={symbol}&from=2024-01-01&to=2030-01-01&token={api_key}"
        res = _get(url, timeout=10)
        if res.status_code == 200:
            data = res.json()
            if "data" in data:
                insider_data = data["data"]
    except Exception as e:
        print(f"Finnhub Insider API Error for {symbol}: {e}")
        return []

    if symbol not in cache_data:
        cache_data[symbol] = {}
        
    cache_data[symbol]["timestamp_insider"] = now
    cache_data[symbol]["insider"] = insider_data
    _save_cache(cache_data)
        
    return insider_data

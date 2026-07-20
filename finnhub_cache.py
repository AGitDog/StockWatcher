import os
import json
import time
import requests
from pathlib import Path
from typing import Any

CACHE_DIR = Path("cache")
CACHE_FILE = CACHE_DIR / "finnhub_targets.json"
CACHE_TTL = 24 * 60 * 60  # 24 hours in seconds

def get_finnhub_key() -> str:
    """Holt den Finnhub API Key aus Umgebungsvariablen oder secrets.toml."""
    # 1. Try environment variable (useful for GitHub Actions)
    api_key = os.environ.get("FINNHUB_API_KEY")
    if api_key:
        return api_key

    # 2. Try Streamlit secrets.toml
    secrets_path = Path(".streamlit/secrets.toml")
    if secrets_path.exists():
        try:
            content = secrets_path.read_text(encoding="utf-8")
            for line in content.splitlines():
                if line.startswith("api_key") and "=" in line:
                    return line.split("=")[1].strip().strip('"').strip("'")
        except Exception:
            pass

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

def get_analyst_data(symbol: str) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    """
    Holt Price Targets und Recommendation Trends von Finnhub.
    Nutzt einen lokalen 24-Stunden-Cache, um API-Limits zu schonen.
    
    Returns:
        (price_target_dict, recommendation_list)
        If API key is missing or an error occurs, returns (None, []).
    """
    api_key = get_finnhub_key()
    if not api_key:
        return None, []

    cache_data = _load_cache()
    now = time.time()
    
    # Check cache validity
    symbol_data = cache_data.get(symbol)
    if symbol_data and (now - symbol_data.get("timestamp", 0)) < CACHE_TTL:
        return symbol_data.get("price_target"), symbol_data.get("recommendation", [])

    # Need to fetch fresh data
    price_target = None
    recommendation = []
    
    try:
        # Fetch Price Target
        target_url = f"https://finnhub.io/api/v1/stock/price-target?symbol={symbol}&token={api_key}"
        res_target = requests.get(target_url, timeout=10)
        if res_target.status_code == 200:
            price_target = res_target.json()
            
        # Fetch Recommendation Trends
        rec_url = f"https://finnhub.io/api/v1/stock/recommendation?symbol={symbol}&token={api_key}"
        res_rec = requests.get(rec_url, timeout=10)
        if res_rec.status_code == 200:
            recommendation = res_rec.json()
            
    except Exception as e:
        print(f"Finnhub API Error for {symbol}: {e}")
        # Even on error, if we have stale cache, we might want to return it, but for now return None.
        return None, []

    # Save to cache
    if price_target is not None or recommendation:
        cache_data[symbol] = {
            "timestamp": now,
            "price_target": price_target,
            "recommendation": recommendation
        }
        _save_cache(cache_data)
        
    return price_target, recommendation
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
        res = requests.get(url, timeout=10)
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

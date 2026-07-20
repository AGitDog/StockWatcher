import os
import json
import time
import requests
from pathlib import Path
from typing import Any

CACHE_DIR = Path("cache")
CACHE_FILE = CACHE_DIR / "alphavantage_fundamentals.json"
CACHE_TTL = 30 * 24 * 60 * 60  # 30 days in seconds

def get_av_key() -> str:
    """Holt den Alpha Vantage API Key aus Umgebungsvariablen oder secrets.toml."""
    # 1. Try environment variable
    api_key = os.environ.get("ALPHAVANTAGE_API_KEY")
    if api_key:
        return api_key

    # 2. Try Streamlit secrets.toml
    secrets_path = Path(".streamlit/secrets.toml")
    if secrets_path.exists():
        try:
            content = secrets_path.read_text(encoding="utf-8")
            for line in content.splitlines():
                # Format could be in [alphavantage] section
                if line.strip().startswith("api_key") and "=" in line:
                    # In a simple parser, if we have multiple sections this is risky.
                    # But we'll just check if the line above had [alphavantage]
                    pass
            
            # Safer parsing:
            in_av_section = False
            for line in content.splitlines():
                line = line.strip()
                if line.startswith("[alphavantage]"):
                    in_av_section = True
                    continue
                elif line.startswith("[") and line.endswith("]"):
                    in_av_section = False
                    continue
                
                if in_av_section and line.startswith("api_key") and "=" in line:
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

def get_fundamentals(symbol: str) -> dict[str, Any] | None:
    """
    Holt Fundamentaldaten (OVERVIEW) von Alpha Vantage.
    Nutzt einen lokalen 30-Tage-Cache.
    
    Da Alpha Vantage nur 5 Calls/Minute im Free-Tier erlaubt, 
    ist Caching hier extrem wichtig. Bei Rate-Limits wird None zurueckgegeben,
    damit das System auf yfinance zurueckfallen kann, ohne zu blockieren.
    """
    api_key = get_av_key()
    if not api_key:
        return None

    cache_data = _load_cache()
    now = time.time()
    
    symbol_data = cache_data.get(symbol)
    if symbol_data and (now - symbol_data.get("timestamp", 0)) < CACHE_TTL:
        return symbol_data.get("data")

    # Fetch fresh data
    try:
        url = f"https://www.alphavantage.co/query?function=OVERVIEW&symbol={symbol}&apikey={api_key}"
        res = requests.get(url, timeout=10)
        
        if res.status_code == 200:
            data = res.json()
            
            # Alpha Vantage liefert bei Rate-Limit oder Invalid Key oft ein dict mit "Information" oder "Error Message"
            if "Information" in data and "rate limit" in data["Information"].lower():
                print(f"Alpha Vantage Rate Limit erreicht für {symbol}.")
                return None
            if "Error Message" in data:
                print(f"Alpha Vantage Fehler für {symbol}: {data['Error Message']}")
                return None
                
            # Valid data should have basic fields like Symbol
            if data and data.get("Symbol"):
                cache_data[symbol] = {
                    "timestamp": now,
                    "data": data
                }
                _save_cache(cache_data)
                
                # Sleep briefly to avoid hitting the 5/min limit too aggressively if we do batch processing
                # But to avoid stalling the app for 12 seconds per ticker, we rely on the caller/fallback.
                # The first 5 tickers will be fast, the 6th will hit the limit and fallback to yfinance immediately.
                return data
                
    except Exception as e:
        print(f"Alpha Vantage API Error for {symbol}: {e}")

    return None

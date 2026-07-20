import os
import json
import time
import requests
from pathlib import Path
from typing import Any

CACHE_DIR = Path("cache")
CACHE_FILE = CACHE_DIR / "fred_macro.json"
CACHE_TTL = 24 * 60 * 60  # 24 hours in seconds

def get_fred_key() -> str:
    """Holt den FRED API Key aus Umgebungsvariablen oder secrets.toml."""
    api_key = os.environ.get("FRED_API_KEY")
    if api_key:
        return api_key

    secrets_path = Path(".streamlit/secrets.toml")
    if secrets_path.exists():
        try:
            content = secrets_path.read_text(encoding="utf-8")
            in_fred_section = False
            for line in content.splitlines():
                line = line.strip()
                if line.startswith("[fred]"):
                    in_fred_section = True
                    continue
                elif line.startswith("[") and line.endswith("]"):
                    in_fred_section = False
                    continue
                
                if in_fred_section and line.startswith("api_key") and "=" in line:
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

def get_yield_curve_spread() -> float | None:
    """
    Holt den letzten Wert von T10Y2Y (10-Year Minus 2-Year Treasury) von FRED.
    Wenn negativ, ist die Kurve invertiert.
    
    Returns:
        float Spread oder None bei Fehler/fehlendem Key.
    """
    api_key = get_fred_key()
    if not api_key:
        return None

    cache_data = _load_cache()
    now = time.time()
    
    # Check cache validity
    spread_data = cache_data.get("T10Y2Y")
    if spread_data and (now - spread_data.get("timestamp", 0)) < CACHE_TTL:
        return spread_data.get("value")

    try:
        url = f"https://api.stlouisfed.org/fred/series/observations?series_id=T10Y2Y&api_key={api_key}&file_type=json&sort_order=desc&limit=1"
        res = requests.get(url, timeout=10)
        
        if res.status_code == 200:
            data = res.json()
            observations = data.get("observations", [])
            if observations:
                latest_value_str = observations[0].get("value")
                if latest_value_str and latest_value_str != ".":
                    value = float(latest_value_str)
                    
                    cache_data["T10Y2Y"] = {
                        "timestamp": now,
                        "value": value
                    }
                    _save_cache(cache_data)
                    return value
    except Exception as e:
        print(f"FRED API Error: {e}")

    return None

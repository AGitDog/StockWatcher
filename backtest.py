import json
import logging
from pathlib import Path
from datetime import datetime
import pandas as pd
import yfinance as yf
from stock_agent import DEFAULT_WATCHLIST_DIR

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

HISTORY_DIR = Path("signal_history")

def load_snapshots() -> list[tuple[datetime, list[dict]]]:
    snapshots = []
    if not HISTORY_DIR.exists():
        return snapshots
        
    for file_path in HISTORY_DIR.glob("*.json"):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                
            mtime = file_path.stat().st_mtime
            dt = datetime.fromtimestamp(mtime)
            
            if isinstance(data, list):
                snapshots.append((dt, data))
        except Exception as e:
            logging.error(f"Fehler beim Laden von {file_path}: {e}")
            
    return snapshots

def fetch_forward_return(symbol: str, start_date: datetime, days: int = 30) -> float | None:
    try:
        end_date = start_date + pd.Timedelta(days=days + 10) 
        ticker = yf.Ticker(symbol)
        hist = ticker.history(start=start_date.strftime("%Y-%m-%d"), end=end_date.strftime("%Y-%m-%d"))
        
        if hist.empty or len(hist) < 2:
            return None
            
        start_price = float(hist["Close"].iloc[0])
        target_date = start_date + pd.Timedelta(days=days)
        
        target_date_tz = target_date.tz_localize(hist.index.tz) if hist.index.tz else target_date
        
        closest_idx = hist.index.get_indexer([target_date_tz], method='nearest')[0]
        if closest_idx == -1:
            return None
            
        end_price = float(hist["Close"].iloc[closest_idx])
        return ((end_price / start_price) - 1.0) * 100.0
        
    except Exception as e:
        logging.debug(f"Konnte Historie für {symbol} nicht laden: {e}")
        return None

def run_backtest(days: int = 30):
    logging.info(f"Starte Backtest ({days} Tage Forward-Rendite)...")
    snapshots = load_snapshots()
    if not snapshots:
        logging.warning("Keine Snapshots im signal_history Ordner gefunden.")
        return

    records = []
    
    for snapshot_date, items in snapshots:
        if (datetime.now() - snapshot_date).days < (days - 5): 
            logging.info(f"Überspringe Snapshot vom {snapshot_date.date()} (zu neu für {days}-Tage Rendite).")
            continue
            
        for item in items:
            symbol = item.get("symbol")
            if not symbol:
                continue
                
            total_score = item.get("brodel_score", 0)
            breakdown = item.get("signal_breakdown", {})
            
            fwd_ret = fetch_forward_return(symbol, snapshot_date, days=days)
            if fwd_ret is not None:
                record = {
                    "Datum": snapshot_date.date(),
                    "Symbol": symbol,
                    "Total_Score": total_score,
                    "Forward_Return": fwd_ret
                }
                for comp_name, comp_data in breakdown.items():
                    record[comp_name] = comp_data.get("score", 0)
                    
                records.append(record)

    if not records:
        logging.warning("Nicht genug historische Daten für Backtest (Snapshots zu neu?).")
        return
        
    df = pd.DataFrame(records)
    logging.info(f"Backtest mit {len(df)} Datenpunkten abgeschlossen.")
    
    corr = df.corr(numeric_only=True)["Forward_Return"].sort_values(ascending=False)
    
    print(f"\n--- BACKTEST ERGEBNISSE ({days} Tage) ---")
    print("Korrelation der Komponenten mit der tatsächlichen Performance:")
    print(corr.to_string())
    print("-" * 40)
    
if __name__ == "__main__":
    run_backtest(30)

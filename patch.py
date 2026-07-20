import re

with open("stock_agent.py", "r", encoding="utf-8") as f:
    content = f.read()

tech_func = """
def _summarize_technical_indicators(history: pd.DataFrame | None) -> dict[str, Any]:
    if history is None or history.empty or len(history) < 26:
        return {"name": "Technische Indikatoren", "score": 0, "summary": "Nicht genug Kursdaten fuer Technische Indikatoren."}

    close = pd.to_numeric(history.get("Close"), errors="coerce")
    if close is None or close.isna().all():
        return {"name": "Technische Indikatoren", "score": 0, "summary": "Kursdaten nicht lesbar."}

    # RSI
    delta = close.diff()
    up, down = delta.copy(), delta.copy()
    up[up < 0] = 0
    down[down > 0] = 0
    roll_up = up.ewm(span=14).mean()
    roll_down = down.abs().ewm(span=14).mean()
    rs = roll_up / roll_down
    rsi = 100.0 - (100.0 / (1.0 + rs))
    current_rsi = float(rsi.iloc[-1]) if not pd.isna(rsi.iloc[-1]) else 50.0

    # MACD
    exp1 = close.ewm(span=12, adjust=False).mean()
    exp2 = close.ewm(span=26, adjust=False).mean()
    macd = exp1 - exp2
    signal = macd.ewm(span=9, adjust=False).mean()
    current_macd = float(macd.iloc[-1]) if not pd.isna(macd.iloc[-1]) else 0.0
    current_signal = float(signal.iloc[-1]) if not pd.isna(signal.iloc[-1]) else 0.0

    # Bollinger Bands
    ma20 = close.rolling(window=20).mean()
    std20 = close.rolling(window=20).std()
    upper_band = ma20 + (std20 * 2)
    lower_band = ma20 - (std20 * 2)
    current_close = float(close.iloc[-1])
    current_upper = float(upper_band.iloc[-1]) if not pd.isna(upper_band.iloc[-1]) else float('inf')
    current_lower = float(lower_band.iloc[-1]) if not pd.isna(lower_band.iloc[-1]) else 0.0

    score = 0
    parts = []

    # Evaluate RSI
    if current_rsi < 30:
        score += 4
        parts.append(f"RSI: {current_rsi:.1f} (Ueberverkauft)")
    elif current_rsi > 70:
        score -= 4
        parts.append(f"RSI: {current_rsi:.1f} (Ueberkauft)")
    else:
        parts.append(f"RSI: {current_rsi:.1f}")

    # Evaluate MACD
    if current_macd > current_signal:
        score += 3
        parts.append("MACD: Bullisch")
    else:
        score -= 1
        parts.append("MACD: Baerisch")

    # Evaluate Bollinger
    if current_close < current_lower:
        score += 3
        parts.append("Bollinger: Unteres Band")
    elif current_close > current_upper:
        score -= 3
        parts.append("Bollinger: Oberes Band")

    score = max(-8, min(10, score))
    summary = " | ".join(parts)
    return {"name": "Technische Indikatoren", "score": score, "summary": summary}


def _apply_macro_overlay(score: int) -> int:
    try:
        spy = _safe_dataframe(lambda: yf.Ticker("SPY").history(period="1y"))
        vix = _safe_dataframe(lambda: yf.Ticker("^VIX").history(period="1mo"))
        
        multiplier = 1.0
        
        if spy is not None and not spy.empty and len(spy) >= 200:
            spy_close = float(spy["Close"].iloc[-1])
            spy_ma200 = float(spy["Close"].tail(200).mean())
            if spy_close > spy_ma200:
                multiplier *= 1.1
            else:
                multiplier *= 0.8
                
        if vix is not None and not vix.empty:
            vix_close = float(vix["Close"].iloc[-1])
            if vix_close > 25:
                multiplier *= 0.9
                
        return int(round(score * multiplier))
    except Exception:
        return score
"""

# Insert the functions right before `def build_symbol_signal_monitor`
content = content.replace("def build_symbol_signal_monitor", tech_func + "\n\ndef build_symbol_signal_monitor")

# Update build_symbol_signal_monitor
old_monitor = '''    relative_strength_signal = _summarize_relative_strength(history, symbol)
    fundamental_signal = _summarize_fundamentals(info)

    signal_components = [
        eps_revision_signal,
        price_target_signal,
        price_volume_signal,
        news_signal,
        event_signal,
        insider_signal,
        short_interest_signal,
        relative_strength_signal,
        fundamental_signal,
    ]

    brodel_score = max(0, min(sum(component["score"] for component in signal_components), 100))'''

new_monitor = '''    relative_strength_signal = _summarize_relative_strength(history, symbol)
    fundamental_signal = _summarize_fundamentals(info)
    technical_signal = _summarize_technical_indicators(history)

    signal_components = [
        eps_revision_signal,
        price_target_signal,
        price_volume_signal,
        news_signal,
        event_signal,
        insider_signal,
        short_interest_signal,
        relative_strength_signal,
        fundamental_signal,
        technical_signal,
    ]

    raw_score = sum(component["score"] for component in signal_components)
    macro_adjusted_score = _apply_macro_overlay(raw_score)
    brodel_score = max(-30, min(macro_adjusted_score, 100))'''

content = content.replace(old_monitor, new_monitor)

# EPS
content = content.replace("score = min(18, 6 + net_revisions * 3)", "score = min(15, 6 + net_revisions * 3)")
content = content.replace("elif net_revisions < 0:\n        score = 0", "elif net_revisions < 0:\n        score = max(-5, net_revisions)")

# Price/Volume
content = content.replace("vol_score = 5", "vol_score = 3")
content = content.replace("total_score = max(-10, min(15, base_score + vol_score))", "total_score = max(-10, min(10, base_score + vol_score))")

# Fundamentals
content = content.replace("if fcf_yield > 5:\n            score += 3", "if fcf_yield > 5:\n            score += 2")
content = content.replace("if debt_equity < 50:\n            score += 3", "if debt_equity < 50:\n            score += 2")
content = content.replace("if peg_ratio < 1.0:\n            score += 3", "if peg_ratio < 1.0:\n            score += 2")
content = content.replace("if forward_pe < 15:\n            score += 3", "if forward_pe < 15:\n            score += 2")

# Short Interest
content = content.replace("if short_pct_display >= 20:\n                score = 6", "if short_pct_display >= 20:\n                score = 5")
content = content.replace("if short_pct_display >= 10:\n                score = 4", "if short_pct_display >= 10:\n                score = 3")
content = content.replace("if short_pct_display >= 5:\n                score = 2", "if short_pct_display >= 5:\n                score = 1")
content = content.replace("if short_ratio >= 5 and score < 6:\n                score = max(score, 5)", "if short_ratio >= 5 and score < 5:\n                score = max(score, 4)")
content = content.replace("elif short_ratio >= 3 and score < 4:\n                score = max(score, 3)", "elif short_ratio >= 3 and score < 3:\n                score = max(score, 2)")

# Event
content = content.replace("if nearest <= 7:\n        score = 8", "if nearest <= 7:\n        score = 5")
content = content.replace("elif nearest <= 14:\n        score = 5", "elif nearest <= 14:\n        score = 3")
content = content.replace("elif nearest <= 30:\n        score = 2", "elif nearest <= 30:\n        score = 1")

# Relative Strength (was 8 max, now we want 5 max, but code says 5 max already? Let's check: 5, 3, 1.)
# Wait, Relative Strength is already 5 max in code!
# Let's verify sum: 15 (EPS) + 15 (Targets) + 15 (News) + 10 (Tech) + 10 (Fund) + 10 (Insider) + 10 (P/V) + 5 (Rel) + 5 (Event) + 5 (Short) = 100.
# So Relative Strength stays 5 max.

with open("stock_agent.py", "w", encoding="utf-8") as f:
    f.write(content)

print("Patch applied.")

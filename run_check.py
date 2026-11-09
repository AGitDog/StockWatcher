"""Decide whether the nightly chain still has to run (light: no pandas, no yfinance).

    python run_check.py            prints "true" or "false"

The chain is started twice per weekday: a main start after the US close and a backup start the
next morning, because GitHub delays scheduled runs by hours or skips them. The backup only runs
when the bot has not decided for that trading day yet.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

STATE_FILE = Path("bot_depot/state.json")
SNAPSHOT_DAY_SHIFT_HOURS = 9  # same as stock_agent.SNAPSHOT_DAY_SHIFT_HOURS (checked by a test)


def trading_day(now: datetime) -> str:
    return (now - timedelta(hours=SNAPSHOT_DAY_SHIFT_HOURS)).date().isoformat()


def needs_run(now: datetime | None = None, state_path: Path = STATE_FILE) -> bool:
    now = now or datetime.now(timezone.utc)
    if 9 <= now.hour < 21:
        return False  # far too late: exchanges trade again, prices would be half a day
    day = trading_day(now)
    if datetime.fromisoformat(day).weekday() >= 5:
        return False  # the morning backup after Friday counts for Friday; nothing for Sat/Sun
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return True
    portfolios = state.get("portfolios", {}).values()
    return not portfolios or any(p.get("last_decision") != day for p in portfolios)


if __name__ == "__main__":
    print("true" if needs_run() else "false")
    sys.exit(0)

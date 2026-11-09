"""The backup start of the nightly chain runs only when the trading day is not done yet."""
import json
from datetime import datetime, timezone

import run_check
import stock_agent


def _at(text):
    return datetime.fromisoformat(text).replace(tzinfo=timezone.utc)


def _state(tmp_path, day):
    path = tmp_path / "state.json"
    path.write_text(json.dumps({"portfolios": {"bot": {"last_decision": day}, "rank": {"last_decision": day}}}), encoding="utf-8")
    return path


def test_same_day_rule_as_stock_agent():
    assert run_check.SNAPSHOT_DAY_SHIFT_HOURS == stock_agent.SNAPSHOT_DAY_SHIFT_HOURS


def test_backup_skips_a_finished_day(tmp_path):
    path = _state(tmp_path, "2026-11-09")
    assert run_check.needs_run(_at("2026-11-10T03:35:00"), path) is False
    assert run_check.needs_run(_at("2026-11-09T21:35:00"), path) is False


def test_backup_runs_when_the_main_start_was_skipped(tmp_path):
    path = _state(tmp_path, "2026-11-06")
    assert run_check.needs_run(_at("2026-11-10T03:35:00"), path) is True
    assert run_check.needs_run(_at("2026-11-09T21:35:00"), path) is True


def test_no_run_during_trading_hours_or_for_weekends(tmp_path):
    path = _state(tmp_path, "2026-11-06")
    assert run_check.needs_run(_at("2026-11-10T12:00:00"), path) is False  # prices would be half a day
    assert run_check.needs_run(_at("2026-11-08T03:35:00"), path) is False  # Saturday's trading day


def test_saturday_backup_still_counts_for_friday(tmp_path):
    path = _state(tmp_path, "2026-11-05")
    assert run_check.needs_run(_at("2026-11-07T03:35:00"), path) is True


def test_missing_state_means_run(tmp_path):
    assert run_check.needs_run(_at("2026-11-09T21:35:00"), tmp_path / "none.json") is True

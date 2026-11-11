"""The Sunday check itself: retries, last week's runs, the app probe, report and workflow (offline)."""
import gzip
import json
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock

import system_check
from system_check import Check, last_week, pipeline_problems, probe_app_url, report, run_probe, week_bot, week_snapshots

ROOT = Path(__file__).parent.parent


def test_a_probe_gets_a_second_try_and_a_crash_is_a_failure():
    answers = iter([(False, "HTTP 503"), (True, "ok")])
    pauses = []
    check = run_probe("Yahoo", "Kurse", lambda: next(answers), sleep=pauses.append, pause=5)
    assert check.ok and pauses == [5]

    def broken():
        raise KeyError("Total Revenue")

    check = run_probe("Yahoo", "GuV", broken, sleep=lambda _: None)
    assert not check.ok and "KeyError" in check.detail


def test_last_week_is_the_complete_week_before():
    sunday = date(2026, 11, 15)
    assert last_week(sunday) == [date(2026, 11, d) for d in range(9, 14)]
    assert last_week(date(2026, 11, 11)) == [date(2026, 11, d) for d in range(2, 7)]  # Wednesday: the week before


def _write_snapshot(directory: Path, day: str, fresh: int, stale: int, symbols=("AAPL", "SAP.DE", "7203.T", "MSFT", "JPM")):
    items = []
    for index in range(fresh + stale):
        symbol = symbols[index % len(symbols)]
        has_data = index < fresh
        items.append({"symbol": symbol, "signal_breakdown": {"Preis/Volumen": {"summary": "ok" if has_data else "Nicht genug Kursdaten fuer Preis/Volumen-Signal."}}})
    directory.mkdir(parents=True, exist_ok=True)
    with gzip.open(directory / f"{day}.json.gz", "wt", encoding="utf-8") as handle:
        json.dump([{"timestamp": f"{day}T23:59:59Z", "items": items}], handle)


def test_week_snapshots_tolerates_one_bad_day(tmp_path, monkeypatch):
    monkeypatch.setattr("stock_agent.run_group", lambda symbol: "asia")
    monkeypatch.setattr("stock_agent.RUN_GROUPS", ("asia",))
    for day in ("2026-11-09", "2026-11-10", "2026-11-11", "2026-11-12"):
        _write_snapshot(tmp_path, day, fresh=10, stale=0)
    ok, detail = week_snapshots(date(2026, 11, 15), tmp_path)
    assert ok and "4 von 5" in detail and "13.11. fehlt" in detail
    _write_snapshot(tmp_path, "2026-11-12", fresh=2, stale=8)  # throttled by Yahoo
    ok, detail = week_snapshots(date(2026, 11, 15), tmp_path)
    assert not ok and "12.11. 20% frisch" in detail


def test_week_bot_needs_a_value_per_day(tmp_path):
    state = tmp_path / "state.json"
    state.write_text(json.dumps({"equity": [{"day": f"2026-11-{d:02d}"} for d in (9, 10, 11, 12, 13)]}), encoding="utf-8")
    assert week_bot(date(2026, 11, 15), state)[0]
    state.write_text(json.dumps({"equity": [{"day": "2026-11-13"}]}), encoding="utf-8")
    ok, detail = week_bot(date(2026, 11, 15), state)
    assert not ok and "09.11." in detail
    assert not week_bot(date(2026, 11, 15), tmp_path / "missing.json")[0]


def test_pipeline_problems_name_what_is_missing(monkeypatch):
    monkeypatch.setattr("snapshot_store.is_fresh_measurement", lambda item: True)
    good = {"factors_v3": {"profit_margin": 0.2, "forward_pe": 20, "momentum_12_1": 0.1, "eps_up_ratio": 0.5}, "signal_breakdown_v2": {"x": {}}}
    assert pipeline_problems(good) == []
    thin = {"factors_v3": {"momentum_12_1": 0.1}, "signal_breakdown_v2": {}}
    problems = pipeline_problems(thin)
    assert any("nur 1 Rang-Score-Bausteine" in p for p in problems) and "kein Punkte-Score" in problems


def test_app_probe_accepts_the_streamlit_login_redirect():
    def answer(status, location=""):
        return MagicMock(return_value=MagicMock(status_code=status, headers={"Location": location}))

    assert probe_app_url(get=answer(303, "https://share.streamlit.io/-/auth/app?redirect_uri=x"))[0]
    assert probe_app_url(get=answer(200))[0]
    assert not probe_app_url(get=answer(404))[0]
    assert not probe_app_url(get=answer(503))[0]


def test_report_and_exit_code(monkeypatch):
    checks = [Check("Yahoo", "Kurse", True, "ok"), Check("Gemini", "News", False, "Limit", hard=False)]
    assert "1 Warnungen" in report(checks) and "| Gemini | News | ⚠️ |" in report(checks)
    monkeypatch.setattr(system_check, "run_checks", lambda: checks)
    assert system_check.main([]) == 0
    monkeypatch.setattr(system_check, "run_checks", lambda: checks + [Check("Finnhub", "API", False, "HTTP 401")])
    assert system_check.main([]) == 1


def test_every_source_has_a_probe():
    names = " ".join(f"{area} {name}" for area, name, _, _ in system_check.LIVE_PROBES + system_check.OFFLINE_CHECKS)
    for source in ("Yahoo", "Finnhub", "Alpha Vantage", "Gemini", "Indizes", "Tracefour", "SIX", "AMF", "AFM",
                   "Nachtlauf", "App", "Snapshots", "Paper-Bot", "Insider-Abdeckung"):
        assert source in names, source
    assert len(system_check.PAGE_MARKERS) == len(__import__("app").PAGES)


def test_sunday_workflow_replaces_the_monday_check():
    workflow = (ROOT / ".github" / "workflows" / "weekly_check.yml").read_text(encoding="utf-8")
    assert "cron: '0 10 * * 0'" in workflow  # Sunday
    assert "python -m pytest tests/" in workflow and "python system_check.py" in workflow
    assert "issues: write" in workflow and "gh issue create" in workflow
    assert "FRED" not in workflow
    assert not (ROOT / ".github" / "workflows" / "insider_sources_check.yml").exists()
    for name in ("update_signals.yml", "daily_run.yml"):
        assert "FRED" not in (ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")

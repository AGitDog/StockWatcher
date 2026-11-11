"""The weekly live check: a broken source must fail the run, a missing BaFin file must not."""
from datetime import date

import insider_check
from insider_check import Check, bafin_file_age, report, snapshot_coverage


def test_a_crashing_probe_is_a_failed_check_not_a_crash():
    def broken():
        raise ValueError("format changed")

    check = insider_check._run("SIX", broken)
    assert not check.ok and "ValueError" in check.detail


def test_exit_code_fails_only_on_hard_checks(monkeypatch):
    monkeypatch.setattr(insider_check, "run_checks", lambda: [Check("A", True, "ok"), Check("BaFin", False, "alt", hard=False)])
    assert insider_check.main() == 0
    monkeypatch.setattr(insider_check, "run_checks", lambda: [Check("A", False, "HTTP 500")])
    assert insider_check.main() == 1


def test_report_marks_results():
    text = report([Check("SIX", True, "320 Meldungen"), Check("AMF", False, "kaputt"), Check("BaFin", False, "alt", hard=False)])
    assert "| SIX | ✅ |" in text and "| AMF | ❌ |" in text and "| BaFin | ⚠️ |" in text


def test_bafin_file_age(tmp_path):
    file = tmp_path / "bafin.csv"
    assert bafin_file_age(file)[0]  # no file is fine
    file.write_text("Emittent;Mitteilungsdatum\nSAP SE;01.11.2026\n", encoding="utf-8")
    assert bafin_file_age(file, today=date(2026, 11, 10))[0]
    ok, detail = bafin_file_age(file, today=date(2026, 12, 15))
    assert not ok and "44 Tage" in detail


def test_snapshot_coverage_finds_a_market_that_lost_its_source():
    items = [
        {"symbol": "HSBA.L", "factors_v3": {"insider_source": "Yahoo"}},
        {"symbol": "NOVN.SW", "factors_v3": {"insider_source": None}},
        {"symbol": "UBSG.SW", "factors_v3": {"insider_source": None}},
        {"symbol": "7203.T", "factors_v3": {"insider_source": None}},  # Japan has no source, not expected
    ]
    ok, detail = snapshot_coverage(items)
    assert not ok and "SW 0/2" in detail and "ohne Daten: SW" in detail
    items[1]["factors_v3"]["insider_source"] = "SIX"
    assert snapshot_coverage(items)[0]
    assert snapshot_coverage([{"symbol": "HSBA.L", "factors_v3": {}}])[0]  # snapshot from before the change


def test_workflow_runs_the_check_weekly():
    from pathlib import Path

    workflow = (Path(__file__).parent.parent / ".github" / "workflows" / "weekly_check.yml").read_text(encoding="utf-8")
    assert "cron:" in workflow and "python system_check.py" in workflow  # the insider probes run in the Sunday check
    nightly = (Path(__file__).parent.parent / ".github" / "workflows" / "update_signals.yml").read_text(encoding="utf-8")
    assert nightly.count("insider_data/") == 2  # the caches are committed by the group jobs and the bot job


def test_tracefour_probe_reads_the_live_format(monkeypatch):
    import json
    from pathlib import Path
    from unittest.mock import MagicMock

    rows = json.loads((Path(__file__).parent / "fixtures" / "insider" / "tracefour_de.json").read_text(encoding="utf-8"))["data"]
    response = MagicMock(status_code=200)
    response.json.return_value = {"data": rows * 4}
    monkeypatch.setattr(insider_check.sources, "_get", MagicMock(return_value=response))
    ok, detail = insider_check.probe_tracefour()
    assert ok and "2 Firmen mit Käufen" in detail
    response.json.return_value = {"data": [{"issuer": "renamed field"}]}
    assert not insider_check.probe_tracefour()[0]
    assert "DE" in insider_check.EXPECTED_SOURCES

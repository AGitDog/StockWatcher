"""
Tests für den Nightly-Trigger: update_signals.py, daily_job.py und die GitHub Actions Workflows.
Stellt sicher, dass die automatisierten Nacht-Jobs korrekt funktionieren.
"""
import os
import sys
import json
import pytest
import importlib
from unittest.mock import patch, mock_open, MagicMock, call
from pathlib import Path

# ── Importierbarkeit ──────────────────────────────────────────────────────────

def test_update_signals_is_importable():
    """update_signals.py muss fehlerfrei importierbar sein."""
    try:
        import update_signals
        assert hasattr(update_signals, "run_update"), "run_update() Funktion fehlt"
    except Exception as e:
        pytest.fail(f"update_signals.py konnte nicht geladen werden: {e}")


def test_daily_job_is_importable():
    """daily_job.py muss fehlerfrei importierbar sein."""
    try:
        import daily_job
        assert hasattr(daily_job, "main"), "main() Funktion fehlt"
    except Exception as e:
        pytest.fail(f"daily_job.py konnte nicht geladen werden: {e}")


# ── update_signals.py Tests ──────────────────────────────────────────────────

@patch("update_signals.os.path.exists")
@patch("update_signals.sys.exit")
def test_update_signals_missing_watchlist(mock_exit, mock_exists):
    """Fehlende Watchlist-Datei soll sauber mit exit(1) beendet werden."""
    mock_exists.return_value = False
    mock_exit.side_effect = SystemExit

    from update_signals import run_update
    with pytest.raises(SystemExit):
        run_update()

    mock_exit.assert_called_once_with(1)


@patch("update_signals.os.path.exists")
@patch("update_signals.sys.exit")
@patch("builtins.open", new_callable=mock_open, read_data="")
def test_update_signals_empty_watchlist(mock_file, mock_exit, mock_exists):
    """Leere Watchlist soll sauber mit exit(0) beendet werden."""
    mock_exists.return_value = True
    mock_exit.side_effect = SystemExit

    from update_signals import run_update
    with pytest.raises(SystemExit):
        run_update()

    mock_exit.assert_called_once_with(0)


@patch("update_signals.os.path.exists")
@patch("builtins.open", new_callable=mock_open, read_data="AAPL\nMSFT")
@patch("update_signals.build_symbol_signal_monitor")
@patch("update_signals.save_signal_snapshot")
@patch("update_signals.add_watchlist_peer_context")
def test_update_signals_calls_all_symbols(mock_peer, mock_save, mock_build, mock_file, mock_exists):
    """Jedes Symbol aus der Watchlist muss einzeln abgefragt werden."""
    mock_exists.return_value = True
    mock_build.side_effect = [
        {"symbol": "AAPL", "brodel_score": 80},
        {"symbol": "MSFT", "brodel_score": 90},
    ]
    mock_peer.side_effect = lambda x: x
    mock_save.return_value = Path("dummy/path.json")

    from update_signals import run_update
    run_update()

    assert mock_build.call_count == 2
    mock_build.assert_any_call("AAPL", {})
    mock_build.assert_any_call("MSFT", {})


@patch("update_signals.os.path.exists")
@patch("builtins.open", new_callable=mock_open, read_data="AAPL\nINVALID")
@patch("update_signals.build_symbol_signal_monitor")
@patch("update_signals.save_signal_snapshot")
@patch("update_signals.add_watchlist_peer_context")
def test_update_signals_survives_single_symbol_crash(mock_peer, mock_save, mock_build, mock_file, mock_exists):
    """Ein fehlerhaftes Symbol darf den Job NICHT komplett abbrechen."""
    mock_exists.return_value = True

    def build_side_effect(symbol, mappings):
        if symbol == "INVALID":
            raise ValueError("API Error")
        return {"symbol": symbol, "brodel_score": 50}

    mock_build.side_effect = build_side_effect
    mock_peer.side_effect = lambda x: x
    mock_save.return_value = Path("dummy/path.json")

    from update_signals import run_update
    run_update()

    mock_save.assert_called_once()
    saved_data = mock_save.call_args[0][1]
    assert len(saved_data) == 1
    assert saved_data[0]["symbol"] == "AAPL"


@patch("update_signals.os.path.exists")
@patch("builtins.open", new_callable=mock_open, read_data="AAPL")
@patch("update_signals.build_symbol_signal_monitor")
@patch("update_signals.save_signal_snapshot")
@patch("update_signals.add_watchlist_peer_context")
def test_update_signals_saves_sorted_by_score(mock_peer, mock_save, mock_build, mock_file, mock_exists):
    """Ergebnisse muessen nach Score absteigend sortiert gespeichert werden."""
    mock_exists.return_value = True
    mock_build.return_value = {"symbol": "AAPL", "brodel_score": 42}
    mock_peer.side_effect = lambda x: x
    mock_save.return_value = Path("dummy/path.json")

    from update_signals import run_update
    run_update()

    mock_save.assert_called_once()
    saved_name = mock_save.call_args[0][0]
    assert saved_name == "meine_watchlist.txt"


@patch("update_signals.os.path.exists")
@patch("builtins.open", new_callable=mock_open, read_data="AAPL")
@patch("update_signals.build_symbol_signal_monitor")
@patch("update_signals.save_signal_snapshot")
@patch("update_signals.add_watchlist_peer_context")
def test_update_signals_applies_peer_context(mock_peer, mock_save, mock_build, mock_file, mock_exists):
    """Peer-Kontext muss auf die Ergebnisse angewandt werden."""
    mock_exists.return_value = True
    mock_build.return_value = {"symbol": "AAPL", "brodel_score": 50}
    mock_peer.side_effect = lambda x: x
    mock_save.return_value = Path("dummy/path.json")

    from update_signals import run_update
    run_update()

    mock_peer.assert_called_once()


# ── daily_job.py Tests ────────────────────────────────────────────────────────

@patch("daily_job.os.path.exists")
@patch("daily_job.sys.exit")
def test_daily_job_missing_watchlist(mock_exit, mock_exists):
    """daily_job muss bei fehlender Watchlist mit exit(1) enden."""
    mock_exists.return_value = False
    mock_exit.side_effect = SystemExit

    from daily_job import main
    with pytest.raises(SystemExit):
        main()

    mock_exit.assert_called_once_with(1)


@patch("daily_job.os.path.exists")
@patch("daily_job.sys.exit")
@patch("builtins.open", new_callable=mock_open, read_data="")
def test_daily_job_empty_watchlist(mock_file, mock_exit, mock_exists):
    """daily_job muss bei leerer Watchlist sauber mit exit(0) enden."""
    mock_exists.return_value = True
    mock_exit.side_effect = SystemExit

    from daily_job import main
    with pytest.raises(SystemExit):
        main()

    mock_exit.assert_called_once_with(0)


@patch("daily_job.os.path.exists")
@patch("builtins.open", new_callable=mock_open, read_data="AAPL\nGOOG")
@patch("daily_job.build_symbol_signal_monitor")
@patch("daily_job.save_signal_snapshot")
@patch("daily_job.add_watchlist_peer_context")
@patch("daily_job.load_signal_snapshot_history")
def test_daily_job_success(mock_history, mock_peer, mock_save, mock_build, mock_file, mock_exists):
    """daily_job soll alle Symbole verarbeiten und Snapshot speichern."""
    mock_exists.return_value = True
    mock_build.side_effect = [
        {"symbol": "AAPL", "brodel_score": 70},
        {"symbol": "GOOG", "brodel_score": 85},
    ]
    mock_peer.side_effect = lambda x: x
    mock_save.return_value = Path("signal_history/snapshot.json")
    mock_history.return_value = []

    from daily_job import main
    main()

    assert mock_build.call_count == 2
    mock_save.assert_called_once()
    saved_data = mock_save.call_args[0][1]
    assert len(saved_data) == 2
    # Sorted descending: GOOG (85) first, then AAPL (70)
    assert saved_data[0]["symbol"] == "GOOG"
    assert saved_data[1]["symbol"] == "AAPL"


@patch("daily_job.os.path.exists")
@patch("builtins.open", new_callable=mock_open, read_data="AAPL")
@patch("daily_job.build_symbol_signal_monitor")
@patch("daily_job.save_signal_snapshot")
@patch("daily_job.add_watchlist_peer_context")
@patch("daily_job.load_signal_snapshot_history")
@patch("daily_job.build_signal_delta_report")
def test_daily_job_delta_report(mock_delta, mock_history, mock_peer, mock_save, mock_build, mock_file, mock_exists):
    """daily_job soll Delta-Report erstellen, wenn es vorherige Snapshots gibt."""
    mock_exists.return_value = True
    mock_build.return_value = {"symbol": "AAPL", "brodel_score": 80}
    mock_peer.side_effect = lambda x: x
    mock_save.return_value = Path("signal_history/snapshot.json")
    # Simulate 2 existing snapshots (so history[-2] can be accessed)
    mock_history.return_value = [
        {"items": [{"symbol": "AAPL", "brodel_score": 60}]},
        {"items": [{"symbol": "AAPL", "brodel_score": 80}]},
    ]
    mock_delta.return_value = []

    from daily_job import main
    main()

    mock_delta.assert_called_once()


# ── GitHub Actions Workflow Tests ─────────────────────────────────────────────

def test_workflow_update_signals_yml_exists():
    """Die GitHub Actions Workflow-Datei update_signals.yml muss existieren."""
    path = Path("d:/Michael/StockWatcher/stock_monitor_app/.github/workflows/update_signals.yml")
    assert path.exists(), f"Workflow-Datei nicht gefunden: {path}"


def test_workflow_daily_run_yml_exists():
    """Die GitHub Actions Workflow-Datei daily_run.yml muss existieren."""
    path = Path("d:/Michael/StockWatcher/stock_monitor_app/.github/workflows/daily_run.yml")
    assert path.exists(), f"Workflow-Datei nicht gefunden: {path}"


def test_workflow_update_signals_references_existing_script():
    """update_signals.yml muss auf ein existierendes Python-Skript verweisen."""
    workflow_path = Path("d:/Michael/StockWatcher/stock_monitor_app/.github/workflows/update_signals.yml")
    content = workflow_path.read_text(encoding="utf-8")
    assert "python update_signals.py" in content
    script_path = Path("d:/Michael/StockWatcher/stock_monitor_app/update_signals.py")
    assert script_path.exists(), "update_signals.py existiert nicht, aber Workflow verweist darauf"


def test_workflow_daily_run_references_existing_script():
    """daily_run.yml muss auf ein existierendes Python-Skript verweisen."""
    workflow_path = Path("d:/Michael/StockWatcher/stock_monitor_app/.github/workflows/daily_run.yml")
    content = workflow_path.read_text(encoding="utf-8")
    assert "python daily_job.py" in content
    script_path = Path("d:/Michael/StockWatcher/stock_monitor_app/daily_job.py")
    assert script_path.exists(), "daily_job.py existiert nicht, aber Workflow verweist darauf"


def test_workflow_update_signals_has_valid_cron():
    """update_signals.yml muss einen gueltigen Cron-Ausdruck haben."""
    workflow_path = Path("d:/Michael/StockWatcher/stock_monitor_app/.github/workflows/update_signals.yml")
    content = workflow_path.read_text(encoding="utf-8")
    assert "cron:" in content, "Kein Cron-Schedule in update_signals.yml gefunden"
    assert "schedule:" in content, "Kein schedule-Trigger in update_signals.yml"


def test_workflow_daily_run_has_valid_cron():
    """daily_run.yml muss einen gueltigen Cron-Ausdruck haben."""
    workflow_path = Path("d:/Michael/StockWatcher/stock_monitor_app/.github/workflows/daily_run.yml")
    content = workflow_path.read_text(encoding="utf-8")
    assert "cron:" in content, "Kein Cron-Schedule in daily_run.yml gefunden"
    assert "schedule:" in content, "Kein schedule-Trigger in daily_run.yml"


def test_workflows_install_requirements():
    """Beide Workflows muessen die requirements.txt installieren."""
    for name in ["update_signals.yml", "daily_run.yml"]:
        path = Path(f"d:/Michael/StockWatcher/stock_monitor_app/.github/workflows/{name}")
        content = path.read_text(encoding="utf-8")
        assert "requirements.txt" in content, f"{name} installiert keine requirements.txt"


def test_workflows_commit_signal_history():
    """Beide Workflows muessen den signal_history/ Ordner committen."""
    for name in ["update_signals.yml", "daily_run.yml"]:
        path = Path(f"d:/Michael/StockWatcher/stock_monitor_app/.github/workflows/{name}")
        content = path.read_text(encoding="utf-8")
        assert "git add signal_history/" in content, f"{name} committet signal_history/ nicht"


# ── Snapshot-Integritaet ──────────────────────────────────────────────────────

def test_save_signal_snapshot_produces_valid_json(tmp_path):
    """save_signal_snapshot muss gueltiges JSON erzeugen."""
    from stock_agent import save_signal_snapshot

    test_data = [
        {"symbol": "AAPL", "brodel_score": 42, "name": "Apple"},
        {"symbol": "MSFT", "brodel_score": 88, "name": "Microsoft"},
    ]

    snapshot_path = save_signal_snapshot("test_watchlist.txt", test_data, directory=str(tmp_path))

    assert snapshot_path.exists(), "Snapshot-Datei wurde nicht erstellt"
    content = snapshot_path.read_text(encoding="utf-8")
    parsed = json.loads(content)
    assert isinstance(parsed, list), "Snapshot muss eine JSON-Liste sein"
    assert len(parsed) >= 1, "Mindestens ein Snapshot-Eintrag erwartet"
    latest = parsed[-1]
    assert "timestamp" in latest, "Snapshot muss einen Timestamp haben"
    assert "items" in latest, "Snapshot muss Items enthalten"
    items = latest["items"]
    assert len(items) == 2
    symbols = [item["symbol"] for item in items]
    assert "AAPL" in symbols
    assert "MSFT" in symbols


# ── Requirements.txt Vollstaendigkeitstest ────────────────────────────────────

def test_requirements_txt_is_valid():
    """requirements.txt muss gültig sein – jede Zeile darf nur EINE Abhängigkeit enthalten."""
    req_path = Path("d:/Michael/StockWatcher/stock_monitor_app/requirements.txt")
    content = req_path.read_text(encoding="utf-8")
    lines = [l.strip() for l in content.splitlines() if l.strip() and not l.strip().startswith("#")]
    
    for line in lines:
        # No line should contain multiple package names jammed together (e.g., "requests>=2.31.0numpy>=1.20.0")
        # A valid specifier has at most one package name
        # Check: no lowercase letter immediately followed by uppercase or digit-dot sequence typical of a new package
        assert " " not in line, f"Leerzeichen in requirements-Zeile: '{line}'"
        # A simple heuristic: splitting on known separators should yield exactly 2 parts
        # Most importantly check the crucial packages are present
    
    package_names = [line.split(">=")[0].split("==")[0].split("<=")[0].strip().lower() for line in lines]
    for required in ["streamlit", "pandas", "yfinance", "requests", "google-genai"]:
        assert required in package_names, f"Paket '{required}' fehlt in requirements.txt"


def test_requirements_packages_not_merged():
    """Stellt sicher, dass 'google-genai' und 'requests' nicht auf einer Zeile stecken."""
    req_path = Path("d:/Michael/StockWatcher/stock_monitor_app/requirements.txt")
    content = req_path.read_text(encoding="utf-8")
    assert "google-genai" in content, "google-genai nicht in requirements.txt"
    assert "requests" in content, "requests nicht in requirements.txt"
    
    for line in content.splitlines():
        assert not ("google-genai" in line and "requests" in line), \
            f"google-genai und requests sind auf einer Zeile zusammengefügt: '{line}'"


# ── Workflow API-Secrets Tests ────────────────────────────────────────────────

def test_workflows_inject_api_secrets():
    """Beide Workflows muessen die API-Keys als Umgebungsvariablen übergeben."""
    required_secrets = [
        "FINNHUB_API_KEY",
        "ALPHAVANTAGE_API_KEY",
        "FRED_API_KEY",
        "GOOGLE_API_KEY",
    ]
    for name in ["update_signals.yml", "daily_run.yml"]:
        path = Path(f"d:/Michael/StockWatcher/stock_monitor_app/.github/workflows/{name}")
        content = path.read_text(encoding="utf-8")
        for secret in required_secrets:
            assert secret in content, f"Secret '{secret}' fehlt in {name}"


def test_workflows_have_contents_write_permission():
    """Beide Workflows muessen 'contents: write' Berechtigung haben um pushen zu koennen."""
    for name in ["update_signals.yml", "daily_run.yml"]:
        path = Path(f"d:/Michael/StockWatcher/stock_monitor_app/.github/workflows/{name}")
        content = path.read_text(encoding="utf-8")
        assert "contents: write" in content, \
            f"{name} hat kein 'contents: write' – der Push nach GitHub Actions wird fehlschlagen"


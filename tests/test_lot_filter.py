"""Tokyo stocks whose 100-share lot costs more than one depot position are left out of the nightly scan."""
import json
from datetime import date
from unittest.mock import patch, mock_open

import pandas as pd
import pytest

import lot_filter
import paper_bot

LIMIT = 4_999.0


def test_lot_cost_in_euro():
    assert lot_filter.lot_cost_eur(8_600.0, 172.0) == pytest.approx(5_000.0)
    assert lot_filter.lot_cost_eur(None, 172.0) is None and lot_filter.lot_cost_eur(100.0, None) is None


def test_list_keeps_only_tokyo_lots_above_the_budget(tmp_path):
    path = tmp_path / "list.json"
    prices = {"9983.T": 86_000.0, "7203.T": 3_000.0, "7974.T": 9_000.0, "AAPL": 9_999.0}
    data = lot_filter.update_exclusions(list(prices), prices, 172.0, lambda s: {}, LIMIT, date(2026, 11, 25), path)
    assert data["symbols"] == {"7974.T": 5233, "9983.T": 50000}  # Toyota 1.744 € stays, AAPL is no Tokyo stock
    assert json.loads(path.read_text(encoding="utf-8"))["day"] == "2026-11-25"
    assert lot_filter.excluded_symbols(path) == {"7974.T", "9983.T"}


def test_listed_stock_comes_back_after_a_split(tmp_path):
    path = tmp_path / "list.json"
    lot_filter.update_exclusions(["7974.T"], {"7974.T": 9_000.0}, 172.0, lambda s: {}, LIMIT, date(2026, 11, 24), path)
    asked = []

    def refresh(symbols):
        asked.extend(symbols)
        return {"7974.T": 1_800.0}  # 1:5 split

    data = lot_filter.update_exclusions(["7974.T"], {}, 172.0, refresh, LIMIT, date(2026, 11, 25), path)
    assert asked == ["7974.T"] and data["symbols"] == {}


def test_failed_refresh_or_missing_rate_keeps_the_list(tmp_path):
    path = tmp_path / "list.json"
    lot_filter.update_exclusions(["9983.T"], {"9983.T": 86_000.0}, 172.0, lambda s: {}, LIMIT, date(2026, 11, 24), path)

    def broken(symbols):
        raise ConnectionError("Yahoo down")

    assert lot_filter.update_exclusions(["9983.T"], {}, 172.0, broken, LIMIT, date(2026, 11, 25), path)["symbols"] == {"9983.T": 50000}
    assert lot_filter.update_exclusions(["9983.T"], {}, None, broken, LIMIT, date(2026, 11, 26), path)["day"] == "2026-11-25"


def test_drop_excluded_and_missing_file(tmp_path):
    path = tmp_path / "list.json"
    assert lot_filter.drop_excluded(["9983.T", "AAPL"], str, path) == (["9983.T", "AAPL"], [])
    path.write_text(json.dumps({"symbols": {"9983.T": 50000}}), encoding="utf-8")
    assert lot_filter.drop_excluded(["9983.T", "AAPL"], str, path) == (["AAPL"], ["9983.T"])


def test_nightly_refresh_reads_snapshot_prices_and_yahoo_rate(monkeypatch, tmp_path):
    snapshot = {"timestamp": "2026-11-24T22:00:00Z", "items": [
        {"symbol": "9983.T", "last_close": 86_000.0, "signal_breakdown": {"Preis/Volumen": {"summary": "Kurs 86000.00, 5T 1.0%"}}},
        {"symbol": "7203.T", "signal_breakdown": {"Preis/Volumen": {"summary": "Kurs 3000.00, 5T 1.0%"}}},
    ]}
    monkeypatch.setattr("stock_agent.load_signal_snapshot_history", lambda name: [snapshot])
    rate = pd.DataFrame({"Close": [172.0]}, index=pd.to_datetime(["2026-11-24"]))
    monkeypatch.setattr(paper_bot, "download_bars", lambda symbols, start: {"EURJPY=X": rate} if symbols == ["EURJPY=X"] else {})
    data = lot_filter.refresh_for_watchlist.real(["9983.T", "7203.T"], date(2026, 11, 25), tmp_path / "list.json")
    assert data["symbols"] == {"9983.T": 50000} and data["eur_jpy"] == 172.0


@patch("update_signals.os.path.exists", return_value=True)
@patch("update_signals.open", new_callable=mock_open, read_data="AAPL\n9983.T\n7203.T", create=True)
@patch("update_signals.build_symbol_signal_monitor")
@patch("update_signals.save_signal_snapshot")
@patch("update_signals.add_watchlist_peer_context", side_effect=lambda items: items)
def test_nightly_run_does_not_scan_listed_stocks(mock_peer, mock_save, mock_build, mock_file, mock_exists):
    lot_filter.EXCLUSION_FILE.write_text(json.dumps({"symbols": {"9983.T": 50000}}), encoding="utf-8")
    mock_build.side_effect = lambda symbol, mappings: {"symbol": symbol, "brodel_score": 10}
    from update_signals import run_update

    run_update()
    assert sorted(call.args[0] for call in mock_build.call_args_list) == ["7203.T", "AAPL"]


def test_paper_bot_reads_the_price_of_older_snapshots_from_the_text():
    assert paper_bot.item_price({"last_close": 1234.5}) == 1234.5
    assert paper_bot.item_price({"signal_breakdown": {"Preis/Volumen": {"summary": "Kurs 52230.00, 5T -2.1%, Volumen 1.0x"}}}) == 52230.0
    assert paper_bot.item_price({"signal_breakdown": {"Preis/Volumen": {"summary": "Nicht genug Kursdaten"}}}) is None


def test_paper_bot_skips_lots_it_cannot_afford_and_buys_the_next_one():
    state = paper_bot.new_state(pd.Timestamp("2026-11-02T22:45:00Z").to_pydatetime())
    pf, cfg = state["portfolios"]["rank"], state["config"]
    rate = pd.DataFrame({"Close": [172.0]}, index=pd.to_datetime(["2026-11-02"]))
    cands = [{"symbol": "9983.T", "score": 90, "sector": "A", "price": 86_000.0},
             {"symbol": "7203.T", "score": 80, "sector": "B", "price": 3_000.0},
             {"symbol": "SAP.DE", "score": 70, "sector": "C", "price": None}]
    skipped = []
    placed = paper_bot.place_orders(pf, cands, date(2026, 11, 2), cfg, max_new=2, fx={"EURJPY=X": rate}, skipped=skipped)
    assert [o["symbol"] for o in placed] == ["7203.T", "SAP.DE"] and skipped == ["9983.T"]
    # without a rate the order is tried, as before
    pf2 = paper_bot.new_state(pd.Timestamp("2026-11-02T22:45:00Z").to_pydatetime())["portfolios"]["rank"]
    assert [o["symbol"] for o in paper_bot.place_orders(pf2, cands[:1], date(2026, 11, 2), cfg, fx={})] == ["9983.T"]


def test_snapshot_entries_carry_the_last_close():
    import stock_agent

    source = open(stock_agent.__file__, encoding="utf-8").read()
    assert '"last_close": _get_current_price(info, history)' in source

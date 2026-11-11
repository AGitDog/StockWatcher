"""Paper bot: buy >= 60 at the next open, trailing stop 15 % (10 % after +25 %), cooldown, no-stop twin, ETF."""
from datetime import date, datetime, timezone

import pandas as pd
import pytest

import paper_bot as bot
import snapshot_store

PV_OK = {"Preis/Volumen": {"name": "Preis/Volumen", "score": 5, "summary": "Kurs ueber MA20."}}


def _item(symbol, score, **extra):
    return {"symbol": symbol, "name": symbol, "brodel_score": score, "brodel_score_v2": score,
            "signal_breakdown": PV_OK, **extra}


def _snapshot(day, items):
    return {"timestamp": f"{day}T22:40:00Z", "items": items}


def _bars(rows):
    """rows: list of (day, open, low, close)."""
    index = pd.to_datetime([r[0] for r in rows])
    return pd.DataFrame({"Open": [r[1] for r in rows], "High": [max(r[1], r[3]) for r in rows],
                         "Low": [r[2] for r in rows], "Close": [r[3] for r in rows]}, index=index)


def _at(day, hour=22):
    return datetime.fromisoformat(f"{day}T{hour:02d}:45:00").replace(tzinfo=timezone.utc)


def _state(**cfg):
    return bot.new_state(_at("2026-11-02"), cfg)


def test_currency_and_eur_conversion():
    assert bot.currency_of("AAPL") == ("USD", 1)
    assert bot.currency_of("SAP.DE") == ("EUR", 1)
    assert bot.currency_of("BRBY.L") == ("GBP", 100)
    assert bot.currency_of("7203.T") == ("JPY", 1)
    fx = {"EURUSD=X": _bars([("2026-11-02", 1.1, 1.1, 1.1)]), "EURGBP=X": _bars([("2026-11-02", 0.85, 0.85, 0.85)])}
    day = date(2026, 11, 3)
    assert bot.to_eur(110.0, "AAPL", day, fx) == pytest.approx(100.0)
    assert bot.to_eur(8500.0, "BRBY.L", day, fx) == pytest.approx(100.0)  # pence
    assert bot.to_eur(50.0, "SAP.DE", day, fx) == 50.0
    assert bot.to_eur(1000.0, "7203.T", day, fx) is None  # no rate -> no guess


def test_decision_cutoff_skips_incomplete_us_bars():
    assert bot.decision_cutoff(_at("2026-11-05", 22)) == date(2026, 11, 5)
    assert bot.decision_cutoff(_at("2026-11-06", 3)) == date(2026, 11, 5)  # delayed US run
    assert bot.decision_cutoff(_at("2026-11-05", 14)) == date(2026, 11, 4)  # US still trading


def test_candidates_only_fresh_entries_at_threshold_best_first():
    stale = _item("OLD", 70, stale_from="2026-11-01")
    missing = _item("NODATA", 70)
    missing["signal_breakdown"] = {"Preis/Volumen": {"name": "Preis/Volumen", "score": 0, "summary": snapshot_store.MISSING_PRICE_SUMMARY}}
    snap = _snapshot("2026-11-02", [_item("B", 61), _item("A", 65), _item("C", 59), stale, missing])
    assert [c["symbol"] for c in bot.buy_candidates(snap, 60)] == ["A", "B"]


def test_buy_next_open_then_trailing_stop_sells():
    state = _state()
    snap = _snapshot("2026-11-02", [_item("SAP.DE", 62)])
    bot.step(state, snap, {}, {}, _at("2026-11-02"))
    pf = state["portfolios"]["bot"]
    assert pf["pending"][0]["symbol"] == "SAP.DE" and pf["cash"] == 95_000

    bars = {"SAP.DE": _bars([
        ("2026-11-03", 100, 98, 104),   # filled at the open 100, stop 85 -> trails to 104*0.85
        ("2026-11-04", 104, 101, 110),  # stop 93.5
        ("2026-11-05", 109, 92, 95),    # low touches 93.5 -> sold at 93.5 minus 0.5 % slippage
    ])}
    bot.step(state, None, bars, {}, _at("2026-11-05"))
    assert pf["positions"] == [] and pf["pending"] == []
    sale = [t for t in pf["trades"] if t["side"] == "Verkauf"][0]
    fill = 93.5 * 0.995
    assert sale["price"] == pytest.approx(fill, abs=1e-4) and sale["day"] == "2026-11-05"
    shares = (5000 - 1) // 100
    assert sale["shares"] == shares
    assert pf["cash"] == pytest.approx(100_000 - (shares * 100 + 1) + shares * fill - 1)

    twin = state["portfolios"]["no_stop"]
    assert len(twin["positions"]) == 1 and twin["positions"][0]["last_price"] == 95


def test_slippage_never_below_day_low():
    state = _state()
    bot.step(state, _snapshot("2026-11-02", [_item("SAP.DE", 62)]), {}, {}, _at("2026-11-02"))
    # stop 85 after the fill; low 84.9 touches it, 85 * 0.995 = 84.575 would be below the low
    bars = {"SAP.DE": _bars([("2026-11-03", 100, 99, 100), ("2026-11-04", 90, 84.9, 88)])}
    bot.step(state, None, bars, {}, _at("2026-11-04"))
    sale = [t for t in state["portfolios"]["bot"]["trades"] if t["side"] == "Verkauf"][0]
    assert sale["price"] == pytest.approx(84.9)


def test_gap_below_stop_sells_at_open():
    state = _state()
    bot.step(state, _snapshot("2026-11-02", [_item("SAP.DE", 62)]), {}, {}, _at("2026-11-02"))
    bars = {"SAP.DE": _bars([("2026-11-03", 100, 99, 100), ("2026-11-04", 70, 60, 65)])}
    bot.step(state, None, bars, {}, _at("2026-11-04"))
    sale = [t for t in state["portfolios"]["bot"]["trades"] if t["side"] == "Verkauf"][0]
    assert sale["price"] == 70 and "Kurslücke" in sale["reason"]


def test_stop_tightens_to_ten_percent_after_25_percent_gain_and_never_drops():
    cfg = bot.DEFAULT_CONFIG
    pf = {"use_stop": True, "cash": 0.0, "trades": [], "cooldown": {}}
    position = {"symbol": "SAP.DE", "entry_price": 100.0, "high_close": 100.0, "stop": 85.0, "shares": 10,
                "cost_eur": 1001.0, "last_price": 100.0, "last_day": "2026-11-03", "entry_day": "2026-11-03"}
    bars = bot._bars_after(_bars([("2026-11-04", 110, 109, 124), ("2026-11-05", 124, 120, 130), ("2026-11-06", 129, 118, 120)]),
                           date(2026, 11, 3), date(2026, 11, 6))
    assert bot.process_position(pf, position, bars, {}, cfg)
    assert position["high_close"] == 130
    assert position["stop"] == pytest.approx(117.0)  # 130 * 0.90, not lowered by the 120 close


def test_cooldown_blocks_rebuy_for_28_days():
    state = _state()
    pf = state["portfolios"]["bot"]
    pf["cooldown"]["SAP.DE"] = "2026-11-05"
    cands = [{"symbol": "SAP.DE", "name": "SAP", "score": 65}]
    assert bot.place_orders(pf, cands, date(2026, 11, 20), state["config"]) == []
    assert [o["symbol"] for o in bot.place_orders(pf, cands, date(2026, 12, 3), state["config"])] == ["SAP.DE"]


def test_max_twenty_positions_and_budget():
    state = _state()
    items = [_item(f"S{i:02d}.DE", 60 + i % 5) for i in range(30)]
    bot.step(state, _snapshot("2026-11-02", items), {}, {}, _at("2026-11-02"))
    pf = state["portfolios"]["bot"]
    assert len(pf["pending"]) == 20 and pf["cash"] == 0
    # second run on the same day places nothing new
    bot.step(state, _snapshot("2026-11-02", items), {}, {}, _at("2026-11-02", 23))
    assert len(pf["pending"]) == 20


def test_order_expires_without_prices():
    state = _state()
    bot.step(state, _snapshot("2026-11-02", [_item("GONE.DE", 70)]), {}, {}, _at("2026-11-02"))
    bot.step(state, None, {}, {}, _at("2026-11-12"))
    pf = state["portfolios"]["bot"]
    assert pf["pending"] == [] and pf["cash"] == 100_000
    assert pf["trades"][-1]["side"] == "Storniert"


def test_etf_benchmark_and_equity_curve():
    state = _state()
    bars = {bot.ETF_SYMBOL: _bars([("2026-11-02", 99, 98, 99), ("2026-11-03", 100, 99, 101), ("2026-11-04", 101, 100, 105)])}
    bot.step(state, None, bars, {}, _at("2026-11-04"))
    assert state["etf"]["bought_on"] == "2026-11-03"  # first open after the start day
    assert state["etf"]["last_value"] == pytest.approx((100_000 - 1) / 100 * 105)
    assert state["equity"][-1]["bot"] == 100_000


def test_run_end_to_end_with_state_file(tmp_path):
    path = tmp_path / "state.json"
    calls = []

    def loader(symbols, start):
        calls.append(sorted(symbols))
        return {"AAPL": _bars([("2026-11-03", 110, 108, 112)]), "EURUSD=X": _bars([("2026-11-03", 1.1, 1.1, 1.1)])}

    bot.run(_at("2026-11-02"), path, loader, snapshot=_snapshot("2026-11-02", [_item("AAPL", 63)]))
    summary = bot.run(_at("2026-11-03"), path, loader, snapshot=_snapshot("2026-11-03", []))
    state = bot.load_state(path)
    position = state["portfolios"]["bot"]["positions"][0]
    assert position["symbol"] == "AAPL" and position["entry_price"] == 110
    assert position["shares"] == int((5000 - 1) // 100)  # 110 USD = 100 EUR
    assert "AAPL" in calls[-1] and "EURUSD=X" in calls[-1]
    assert summary["equity"]["bot"] == pytest.approx(100_000 - 1 + (112 - 110) / 1.1 * position["shares"], abs=0.02)
    assert "AAPL" in bot.status_text(state)


def test_workflow_runs_bot_after_last_group_and_commits_state():
    from pathlib import Path

    content = (Path(__file__).resolve().parent.parent / ".github/workflows/update_signals.yml").read_text(encoding="utf-8")
    assert "python paper_bot.py run" in content
    assert "needs: [check, update-signals]" in content
    assert "if: always() && needs.check.outputs.run == 'true'" in content  # runs even after a failed group
    assert "git add -A signal_history/ bot_depot/" in content


def _sample_state():
    state = _state()
    bot.step(state, _snapshot("2026-11-02", [_item("SAP.DE", 62), _item("ALV.DE", 61)]), {}, {}, _at("2026-11-02"))
    bars = {"SAP.DE": _bars([("2026-11-03", 100, 99, 104), ("2026-11-04", 104, 103, 131)]),
            "ALV.DE": _bars([("2026-11-03", 50, 40, 41)]),
            bot.ETF_SYMBOL: _bars([("2026-11-03", 100, 99, 100), ("2026-11-04", 100, 99, 101)])}
    bot.step(state, None, bars, {}, _at("2026-11-04"))
    return state


def test_app_bot_rows():
    import app

    state = _sample_state()
    rows = app.build_bot_position_rows(state["portfolios"]["bot"], state["config"])
    assert [r["Symbol"] for r in rows] == ["SAP.DE"]
    assert rows[0]["Plus/Minus %"] == 31.0
    assert rows[0]["Stop-Abstand"] == "10 %"  # +31 % > +25 %
    assert rows[0]["Stop-Loss"] == pytest.approx(117.9)
    trades = app.build_bot_trade_rows(state["portfolios"]["bot"])
    assert trades[0]["Art"] == "Verkauf" and trades[0]["Symbol"] == "ALV.DE"  # newest first
    no_stop = app.build_bot_position_rows(state["portfolios"]["no_stop"], state["config"])
    assert "Stop-Loss" not in no_stop[0] and len(no_stop) == 2
    frame = app.build_bot_equity_frame(state)
    assert list(frame.columns) == list(app.BOT_SERIES.values())


def test_bot_tab_renders(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest

    path = tmp_path / "state.json"
    bot.save_state(_sample_state(), path)
    monkeypatch.setenv("BOT_TEST_STATE", str(path))

    def script():
        import json
        import os
        from pathlib import Path

        import app
        import paper_bot

        state_path = Path(os.environ["BOT_TEST_STATE"])
        original = paper_bot.load_state
        paper_bot.load_state = lambda *a, **k: json.loads(state_path.read_text(encoding="utf-8"))
        try:
            app.render_bot_tab()
        finally:
            paper_bot.load_state = original

    at = AppTest.from_function(script, default_timeout=60)
    at.run()
    assert not at.exception
    import app
    assert any("Trades" in s.value for s in at.subheader)
    assert len(at.metric) == len(app.BOT_SERIES)


def _ranked(symbol, score, **extra):
    return _item(symbol, 40, brodel_score_v3=score, sector=extra.pop("sector", "Tech"), **extra)


def test_rank_candidates_take_best_two_percent_and_skip_results_week():
    items = [_ranked(f"S{i:03d}", float(i)) for i in range(200)]
    items[199]["next_earnings"] = "2026-11-05"  # best stock reports in 3 days
    cands = bot.rank_candidates(_snapshot("2026-11-02", items), bot.DEFAULT_CONFIG, date(2026, 11, 2))
    assert [c["symbol"] for c in cands] == ["S198", "S197", "S196"]  # top 4 of 200, the best one blocked


def test_rank_depot_limits_daily_buys_and_sector():
    state = _state()
    items = [_ranked(f"T{i:02d}.DE", 90 - i, sector="Tech") for i in range(4)]
    items += [_ranked(f"F{i:02d}.DE", 70 - i, sector="Fin") for i in range(4)]
    items += [_ranked(f"X{i:03d}.DE", 1.0, sector="Rest") for i in range(392)]
    pf = state["portfolios"]["rank"]
    cands = bot.rank_candidates(_snapshot("2026-11-02", items), state["config"], date(2026, 11, 2))
    assert len(cands) == 8
    placed = bot.place_orders(pf, cands, date(2026, 11, 2), state["config"], max_new=5, sector_limit=2)
    assert [o["symbol"] for o in placed] == ["T00.DE", "T01.DE", "F00.DE", "F01.DE"]


def test_rank_depot_trades_alongside_threshold_depot():
    state = _state()
    items = [_ranked(f"R{i:03d}.DE", 50.0 + i * 0.1) for i in range(100)]
    items[0]["brodel_score_v2"] = 65
    bot.step(state, _snapshot("2026-11-02", items), {}, {}, _at("2026-11-02"))
    assert [o["symbol"] for o in state["portfolios"]["bot"]["pending"]] == ["R000.DE"]
    assert [o["symbol"] for o in state["portfolios"]["rank"]["pending"]] == ["R099.DE", "R098.DE"]
    assert state["portfolios"]["rank"]["cash"] == 90_000


def test_no_orders_when_too_little_fresh_data():
    state = _state()
    items = [_item("A.DE", 70)] + [_item(f"S{i}.DE", 10, stale_from="2026-11-01") for i in range(3)]
    summary = bot.step(state, _snapshot("2026-11-02", items), {}, {}, _at("2026-11-02"))
    assert state["portfolios"]["bot"]["pending"] == []
    assert summary["coverage"]["fresh"] == 0.25


def test_rank_depot_waits_until_brodel_v3_is_available():
    state = _state()
    bot.step(state, _snapshot("2026-11-02", [_item("A.DE", 70)]), {}, {}, _at("2026-11-02"))
    assert state["portfolios"]["rank"]["pending"] == []
    assert len(state["portfolios"]["bot"]["pending"]) == 1


def test_london_stamp_duty_and_japan_lots():
    state = _state()
    pf = state["portfolios"]["bot"]
    cfg = state["config"]
    fx = {"EURGBP=X": _bars([("2026-11-02", 1.0, 1.0, 1.0)]), "EURJPY=X": _bars([("2026-11-02", 100.0, 100.0, 100.0)])}
    day = date(2026, 11, 3)
    london = bot.fill_pending(pf, {"symbol": "LSEG.L", "score": 60, "reserved": 5000.0},
                              [(day, pd.Series({"Open": 10000.0, "Low": 9900.0, "Close": 10000.0}))], fx, cfg)
    assert london["shares"] == 49  # 100 EUR + 0.5 % duty each
    assert london["cost_eur"] == pytest.approx(49 * 100.5 + 1)
    japan = bot.fill_pending(pf, {"symbol": "7203.T", "score": 60, "reserved": 5000.0},
                             [(day, pd.Series({"Open": 3000.0, "Low": 2900.0, "Close": 3000.0}))], fx, cfg)
    assert japan["shares"] == 100
    costly = bot.fill_pending(pf, {"symbol": "9983.T", "score": 60, "reserved": 5000.0},
                              [(day, pd.Series({"Open": 60000.0, "Low": 59000.0, "Close": 60000.0}))], fx, cfg)
    assert costly is None and pf["trades"][-1]["side"] == "Storniert"
    assert "9983.T" in pf["cooldown"]


def test_etf_starts_with_the_first_orders():
    state = bot.new_state(_at("2026-11-06", 2))  # delayed run of the 5th
    assert state["started"] == "2026-11-05"


# ── Rang-Score depots with regime pause and score exit (11.11.2026) ─────────

def _etf_bars(start, days, step):
    """Daily ETF closes starting at 100 and moving by ``step`` per day."""
    dates = pd.bdate_range(start, periods=days)
    closes = [100.0 + step * i for i in range(days)]
    return _bars([(d.date().isoformat(), c, c, c) for d, c in zip(dates, closes)])


def test_market_above_average_needs_full_history():
    rising = _etf_bars("2025-10-01", 260, 0.1)
    assert bot.market_above_average(rising, date(2026, 11, 2), 200)["above"]
    falling = _etf_bars("2025-10-01", 260, -0.1)
    regime = bot.market_above_average(falling, date(2026, 11, 2), 200)
    assert not regime["above"] and regime["close"] < regime["average"]
    assert bot.market_above_average(rising.iloc[:150], date(2026, 11, 2), 200) is None
    assert bot.market_above_average(None, date(2026, 11, 2), 200) is None


def test_regime_depot_pauses_buys_below_the_200_day_line_and_keeps_stops():
    state = _state()
    items = [_ranked(f"R{i:03d}.DE", 50.0 + i * 0.1) for i in range(100)]
    falling = {bot.ETF_SYMBOL: _etf_bars("2025-10-01", 280, -0.1)}
    summary = bot.step(state, _snapshot("2026-11-02", items), falling, {}, _at("2026-11-02"))
    assert summary["regime"]["above"] is False and summary["rank_regime_paused"]
    assert state["portfolios"]["rank_regime"]["pending"] == []
    assert [o["symbol"] for o in state["portfolios"]["rank"]["pending"]] == ["R099.DE", "R098.DE"]
    assert [o["symbol"] for o in state["portfolios"]["rank_exit"]["pending"]] == ["R099.DE", "R098.DE"]

    rising = {bot.ETF_SYMBOL: _etf_bars("2025-10-01", 281, 0.1)}
    bot.step(state, _snapshot("2026-11-03", items), rising, {}, _at("2026-11-03"))
    assert "rank_regime_paused" not in bot.step(state, _snapshot("2026-11-04", items), rising, {}, _at("2026-11-04"))
    assert [o["symbol"] for o in state["portfolios"]["rank_regime"]["pending"]][:2] == ["R099.DE", "R098.DE"]


def test_regime_depot_without_etf_history_buys_like_the_rank_depot():
    state = _state()
    items = [_ranked(f"R{i:03d}.DE", 50.0 + i * 0.1) for i in range(100)]
    summary = bot.step(state, _snapshot("2026-11-02", items), {}, {}, _at("2026-11-02"))
    assert summary["regime"] is None
    assert len(state["portfolios"]["rank_regime"]["pending"]) == 2


def test_score_exit_sells_after_five_weak_days_at_the_next_open():
    state = _state()
    items = [_ranked(f"R{i:03d}.DE", 50.0 + i * 0.1) for i in range(100)]
    bot.step(state, _snapshot("2026-11-02", items), {}, {}, _at("2026-11-02"))
    pf = state["portfolios"]["rank_exit"]
    bars = {"R099.DE": _bars([("2026-11-03", 100, 99, 101)]), "R098.DE": _bars([("2026-11-03", 50, 49, 51)])}
    bot.step(state, None, bars, {}, _at("2026-11-03"))
    assert {p["symbol"] for p in pf["positions"]} == {"R099.DE", "R098.DE"}

    weak = [_ranked("R099.DE", 20.0), _ranked("R098.DE", 80.0)] + [_ranked(f"X{i:03d}.DE", 50.0) for i in range(98)]
    days = ["2026-11-04", "2026-11-05", "2026-11-06", "2026-11-09", "2026-11-10"]
    for n, day in enumerate(days, start=1):
        bars = {s: _bars([(day, 100, 99, 100)]) for s in ("R099.DE", "R098.DE")}
        bot.step(state, _snapshot(day, weak), bars, {}, _at(day))
        weak_pos = next(p for p in pf["positions"] if p["symbol"] == "R099.DE")
        assert weak_pos["weak_days"] == n and weak_pos["last_score"] == 20.0
    assert weak_pos["exit_day"] == "2026-11-10"
    assert next(p for p in pf["positions"] if p["symbol"] == "R098.DE")["weak_days"] == 0

    bars = {s: _bars([("2026-11-11", 97, 96, 99)]) for s in ("R099.DE", "R098.DE")}
    bot.step(state, None, bars, {}, _at("2026-11-11"))
    assert [p["symbol"] for p in pf["positions"]] == ["R098.DE"]
    sale = [t for t in pf["trades"] if t["side"] == "Verkauf"][0]
    assert sale["symbol"] == "R099.DE" and sale["price"] == 97 and "5 Tage unter 40" in sale["reason"]
    assert "weak_days" not in state["portfolios"]["rank"]["positions"][0]  # only the exit depot counts


def test_score_exit_count_resets_on_a_good_day_and_holds_without_data():
    pf = {"positions": [{"symbol": "A.DE"}], "cooldown": {}, "trades": []}
    cfg = {"exit_score": 40, "exit_days": 5}
    for day in range(3):
        bot.update_weak_days(pf, _snapshot("2026-11-02", [_ranked("A.DE", 10.0)]), cfg, date(2026, 11, 2 + day))
    assert pf["positions"][0]["weak_days"] == 3
    bot.update_weak_days(pf, _snapshot("2026-11-05", [_ranked("B.DE", 10.0)]), cfg, date(2026, 11, 5))  # no score for A
    assert pf["positions"][0]["weak_days"] == 3
    bot.update_weak_days(pf, _snapshot("2026-11-06", [_ranked("A.DE", 45.0)]), cfg, date(2026, 11, 6))
    assert pf["positions"][0]["weak_days"] == 0 and "exit_day" not in pf["positions"][0]


def test_old_state_gets_the_new_depots_with_fresh_capital(tmp_path):
    state = _state()
    for key in ("rank_regime", "rank_exit"):
        del state["portfolios"][key]
    del state["config"]["exit_days"]
    bot.save_state(state, tmp_path / "state.json")
    loaded = bot.load_state(tmp_path / "state.json")
    assert bot.ensure_portfolios(loaded, _at("2026-11-11")) == ["rank_regime", "rank_exit"]
    added = loaded["portfolios"]["rank_regime"]
    assert added["cash"] == 100_000 and added["started"] == "2026-11-11" and added["regime_filter"] is True
    assert loaded["config"]["exit_days"] == 5
    assert bot.ensure_portfolios(loaded, _at("2026-11-11")) == []


def test_run_loads_enough_etf_history_for_the_average(tmp_path):
    seen = {}

    def loader(symbols, start):
        seen["symbols"], seen["start"] = symbols, start
        return {}

    bot.run(now=_at("2026-11-11"), state_path=tmp_path / "state.json", loader=loader, snapshot=_snapshot("2026-11-11", []))
    assert bot.ETF_SYMBOL in seen["symbols"]
    assert (date(2026, 11, 11) - seen["start"]).days >= 290

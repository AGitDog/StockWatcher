from datetime import datetime, timezone
import os
from pathlib import Path

import pandas as pd
import streamlit as st

from stock_agent import (
    build_watchlist_alerts,
    build_signal_delta_report,
    build_symbol_signal_monitor,
    build_symbol_summary,
    fetch_company_extended_fundamentals,
    parse_watchlist_text,
    parse_symbol_mappings,
    add_watchlist_peer_context,
    BRODEL_V1_MAX_POINTS,
    BRODEL_V2_MAX_POINTS,
    BUYBACK_COMPONENT_NAME,
    ensure_brodel_v2,
    primary_score,
    summarize_index_entries,
    get_supported_indices,
    list_watchlist_files,
    load_signal_snapshot_history,
    load_watchlist_file,
    save_signal_snapshot,
    save_watchlist_file,
)
from strategies import build_strategy_signals
from backtest_engine import (
    BacktestEngine,
    ScoreRangeBacktestResult,
    run_backtest_on_snapshots,
    run_score_range_backtest,
)
from ml_weights import load_trained_weights, train_on_snapshots
from backtest_engine.engine import load_snapshots, snapshots_with_datetimes
import snapshot_store
from factor_lab import BacktestConfig, build_truth_report, snapshot_score_ic
from factor_lab.data import download_close_prices, filter_single_currency, load_universe
from factor_lab.factors import FACTOR_DESCRIPTIONS
import streamlit.components.v1 as components


st.set_page_config(layout="wide")


INTERACTIVE_TABLE_DIR = Path(__file__).parent / "components" / "interactive_table"
if INTERACTIVE_TABLE_DIR.exists() and (INTERACTIVE_TABLE_DIR / "index.html").exists():
    _interactive_table_func = components.declare_component("interactive_table", path=str(INTERACTIVE_TABLE_DIR))
else:
    _interactive_table_func = None


def render_interactive_signals_table(rows: list[dict], selected_symbol: str = None, key: str = "main_signals_table") -> str | None:
    """Renders the custom interactive signals table without checkboxes, supporting row clicks and instant filtering."""
    if _interactive_table_func is not None:
        try:
            return _interactive_table_func(
                rows=rows,
                selected_symbol=selected_symbol,
                key=key,
                default=selected_symbol,
            )
        except Exception:
            pass
    # Fallback to standard dataframe without selection checkboxes if component cannot be loaded
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    return None


DEFAULT_WATCHLIST_NAME = "meine_watchlist.txt"


@st.cache_data(show_spinner=False, ttl=3600, persist="disk")
def get_symbol_summary(entry: str, symbol_mappings: dict):
    return build_symbol_summary(entry, symbol_mappings)


@st.cache_data(show_spinner=False, ttl=3600, persist="disk")
def get_symbol_signal_monitor(entry: str, symbol_mappings: dict):
    return build_symbol_signal_monitor(entry, symbol_mappings)


@st.cache_data(show_spinner=False, ttl=3600, persist="disk")
def get_extended_fundamentals(symbol: str):
    return fetch_company_extended_fundamentals(symbol)


def load_mapping_text() -> str:
    mapping_path = "stock_mappings.txt"
    if not os.path.exists(mapping_path):
        return ""
    with open(mapping_path, "r", encoding="utf-8") as mapping_file:
        return mapping_file.read()


def load_default_watchlist_text() -> tuple[str, str]:
    watchlist_files = list_watchlist_files()
    preferred_name = DEFAULT_WATCHLIST_NAME if DEFAULT_WATCHLIST_NAME in watchlist_files else (watchlist_files[0] if watchlist_files else DEFAULT_WATCHLIST_NAME)
    loaded_text = load_watchlist_file(preferred_name) if watchlist_files else ""
    return preferred_name, loaded_text


def build_score_history_frame(history: list[dict[str, object]]) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for snapshot in history:
        timestamp = snapshot.get("timestamp")
        items = snapshot.get("items", []) if isinstance(snapshot, dict) else []
        for item in items:
            if not snapshot_store.is_fresh_measurement(item):
                continue  # failed fetch or carried over from an earlier day, no measurement
            rows.append(
                {
                    "timestamp": timestamp,
                    "symbol": item.get("symbol"),
                    "name": item.get("name"),
                    "brodel_score_v2": ensure_brodel_v2(dict(item)).get("brodel_score_v2", 0),
                    "brodel_score": item.get("brodel_score", 0),
                }
            )

    if not rows:
        return pd.DataFrame(columns=["timestamp", "symbol", "name", "brodel_score_v2", "brodel_score"])

    frame = pd.DataFrame(rows)
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], errors="coerce")
    return frame.sort_values(["timestamp", "symbol"])


V2_TABLE_COLUMNS = [
    ("EPS", "EPS-Revisionen"),
    ("Kursziel", "Kursziele & Konsens"),
    ("P/V", "Preis/Volumen"),
    ("News", "News-Sentiment"),
    ("Event", "Event-Druck"),
    ("Insider", "Insider-Aktivitaet"),
    ("Short", "Short Interest"),
    ("Rel.St.", "Relative Staerke"),
    ("Fundam.", "Fundamentale Bewertung"),
    ("Tech.", "Technische Indikatoren"),
    ("Rückkauf", BUYBACK_COMPONENT_NAME),
]


def prepare_signal_items(items: list[dict]) -> list[dict]:
    """Make sure every item carries Brodel 2.0 and sort by it (best first)."""
    prepared = [ensure_brodel_v2(dict(item)) for item in items if isinstance(item, dict)]
    return sorted(prepared, key=primary_score, reverse=True)


def build_signal_table_rows(signal_items: list[dict]) -> list[dict]:
    """Rows for the main table: Brodel 2.0 and its points first, Brodel 1.0 as the last column."""
    rows = []
    for item in signal_items:
        peer_context = item.get("peer_context", {})
        breakdown_v2 = item.get("signal_breakdown_v2", {})
        row = {
            "Symbol": item["symbol"],
            "Name": item["name"],
            "Sektor": peer_context.get("sector", "Unbekannt"),
            "Brodel 2.0": primary_score(item),
        }
        for label, component_name in V2_TABLE_COLUMNS:
            row[label] = breakdown_v2.get(component_name, {}).get("score", 0)
        row["Vs. Sektor"] = peer_context.get("score_vs_sector", 0)
        row["Rang"] = f"{peer_context.get('sector_rank', 1)}/{peer_context.get('sector_count', 1)}"
        row["Brodel 1.0"] = item.get("brodel_score", 0)
        rows.append(row)
    return rows


def breakdown_table_height(row_count: int) -> int:
    """Pixel height that shows every row of st.dataframe without an inner scrollbar."""
    return 38 + 35 * max(row_count, 1)


def build_breakdown_rows(item: dict) -> list[dict]:
    """Component table of the detail view with the points of both versions."""
    breakdown_v1 = item.get("signal_breakdown", {}) or {}
    breakdown_v2 = item.get("signal_breakdown_v2", {}) or {}
    rows = []
    for name, max_v2 in BRODEL_V2_MAX_POINTS.items():
        component_v2 = breakdown_v2.get(name, {})
        component_v1 = breakdown_v1.get(name, {})
        rows.append({
            "Komponente": name,
            "Punkte 2.0": component_v2.get("score", 0),
            "Max 2.0": max_v2,
            "Punkte 1.0": component_v1.get("score", 0) if name in BRODEL_V1_MAX_POINTS else None,
            "Max 1.0": BRODEL_V1_MAX_POINTS.get(name),
            "Detail": component_v2.get("summary") or component_v1.get("summary", ""),
        })
    return rows


def execute_signal_calculation(mapping_text: str = ""):
    """Berechnet die Fruehsignale fuer alle Eintraege der Hintergrund-Watchlist und speichert einen Tages-Snapshot."""
    if "watchlist_text" not in st.session_state or not st.session_state.get("watchlist_text", "").strip():
        default_name, default_text = load_default_watchlist_text()
        st.session_state.watchlist_text = default_text
        st.session_state.active_watchlist_name = default_name

    watchlist_content = st.session_state.get("watchlist_text", "").strip()
    if not watchlist_content:
        default_name, default_text = load_default_watchlist_text()
        watchlist_content = default_text.strip()
        st.session_state.watchlist_text = default_text
        st.session_state.active_watchlist_name = default_name

    if not watchlist_content:
        st.warning("Die Watchlist-Datei `watchlists/meine_watchlist.txt` ist leer oder nicht vorhanden.")
        return

    with st.spinner("Berechne Fruehsignale & Tages-Snapshot..."):
        entries = parse_watchlist_text(st.session_state.watchlist_text)
        symbol_mappings = parse_symbol_mappings(mapping_text or load_mapping_text())
        
        if not entries:
            st.warning("Es wurden keine gueltigen Symbole gefunden.")
            return
            
        progress_bar = st.progress(0, text="Lade Signale...")
        raw_results = []
        
        for i, entry in enumerate(entries):
            progress_bar.progress((i) / len(entries), text=f"Lade Signale für {entry} ({i}/{len(entries)})...")
            item = get_symbol_signal_monitor(entry, symbol_mappings)
            raw_results.append(item)
        
        progress_bar.progress(1.0, text="Berechnung Peer-Kontext...")
        
        enriched_results = add_watchlist_peer_context(raw_results)
        strategy_results = build_strategy_signals(enriched_results)
        
        trainer = load_trained_weights()
        for item in strategy_results:
            item["ml_score"] = round(trainer.predict_score(item), 2)
        
        st.session_state.signal_monitor_items = prepare_signal_items(strategy_results)
        watchlist_name = st.session_state.get("active_watchlist_name", DEFAULT_WATCHLIST_NAME)
        st.session_state.signal_monitor_watchlist_name = watchlist_name
        save_signal_snapshot(watchlist_name, st.session_state.signal_monitor_items)
        progress_bar.empty()
        st.success("Frühsignale erfolgreich berechnet und als Tages-Snapshot gespeichert!")


def render_watchlist_signal_monitor(mapping_text: str):
    st.subheader("🔥 Signal Monitor")

    with st.expander("ℹ️ Über diesen StockWatcher – Mission & Prinzipien", expanded=False):
        ec1, ec2 = st.columns(2)
        with ec1:
            st.markdown("##### 🎯 Was dieser Monitor leistet")
            st.markdown(
                "- **Systematische Früherkennung:** Scannt Aktien kontinuierlich nach 11 objektiven Frühindikatoren (Brodel-Score 2.0).\n"
                "- **Akkumulation & Smart Money:** Erkennt anziehendes Volumen, relative Stärke gegen die Benchmark und Insider-Käufe.\n"
                "- **Fundamentale Dynamik:** Verbindet Gewinnschätzungen und Analysten-Kursziele mit operativer Ertragskraft (Bruttomarge, EBIT, OpEx)."
            )
        with ec2:
            st.markdown("##### ⛔ Was dieser Monitor NICHT ist")
            st.markdown(
                "- **Keine Anlageberatung:** Keine Handlungsaufforderungen oder Kauf-/Verkaufsempfehlungen im Sinne des WpHG.\n"
                "- **Kein Hype-Trading:** Keine spekulativen Social-Media-Gerüchte; rein quantitative Datenbasis.\n"
                "- **Keine Glaskugel:** Marktentwicklungen unterliegen Risiken; Signale dienen der qualifizierten Vorselektion."
            )

    active_name = st.session_state.get("active_watchlist_name", DEFAULT_WATCHLIST_NAME)

    if "signal_monitor_items" not in st.session_state:
        history = load_signal_snapshot_history(active_name)
        if history:
            st.session_state.signal_monitor_items = history[-1].get("items", [])
            st.session_state.signal_monitor_watchlist_name = active_name

    signal_items = prepare_signal_items(st.session_state.get("signal_monitor_items", []))
    if not signal_items:
        st.info("Noch kein Signal-Snapshot vorhanden. Starte die Berechnung im Tab 'Backtest & ML' unter '⚙️ Datenpflege & Signal-Snapshot erstellen'.")
        return

    history = load_signal_snapshot_history(active_name)
    score_history = build_score_history_frame(history)

    m_stat1, m_stat2, m_stat3 = st.columns(3)
    m_stat1.caption(f"Watchlist: `{active_name}`")
    m_stat2.caption(f"Analysierte Werte: **{len(signal_items)} Symbole**")
    m_stat3.caption(f"Snapshot-Historie: **{len(history)} Tage**")

    st.caption(
        "Sortiert nach **Brodel 2.0**. Die Punkte der Einzelspalten sind 2.0-Punkte. "
        "Der alte **Brodel 1.0** steht zum Vergleich in der letzten Spalte."
    )
    table_rows = build_signal_table_rows(signal_items)

    active_sym = st.session_state.get("active_selected_symbol")
    if not active_sym and signal_items:
        active_sym = signal_items[0]["symbol"]
        st.session_state["active_selected_symbol"] = active_sym

    clicked_symbol = render_interactive_signals_table(
        table_rows,
        selected_symbol=active_sym,
        key="main_signals_table",
    )

    if clicked_symbol and clicked_symbol != active_sym:
        st.session_state["active_selected_symbol"] = clicked_symbol
        st.rerun()

    active_sym = st.session_state.get("active_selected_symbol", signal_items[0]["symbol"] if signal_items else "")
    selected_row_idx = 0
    for idx, it in enumerate(signal_items):
        if it["symbol"] == active_sym:
            selected_row_idx = idx
            break

    st.markdown("---")
    st.subheader("🔍 Detail-Analyse")
    st.write("Klicke direkt auf eine Zeile in der Tabelle oben oder wähle eine Aktie aus:")
    
    options = [f"{item['symbol']} - {item['name']} (Brodel 2.0: {primary_score(item)})" for item in signal_items]
    selected_option = st.selectbox("Aktie suchen", options=options, index=selected_row_idx if options else None)
    
    if selected_option:
        selected_symbol = selected_option.split(" - ")[0]
        st.session_state["active_selected_symbol"] = selected_symbol
        item = next((i for i in signal_items if i["symbol"] == selected_symbol), None)
        
        if item:
            head_col1, head_col2 = st.columns([3, 1])
            with head_col1:
                st.markdown(
                    f"### {item['symbol']} - {item['name']} | Brodel 2.0: {primary_score(item)}"
                    f" <span style='font-size:0.6em;color:gray'>(Brodel 1.0: {item.get('brodel_score', 0)})</span>",
                    unsafe_allow_html=True,
                )
                if item.get("stale_from"):
                    st.caption(f"Stand vom {item['stale_from']}: Der heutige Abruf für diese Aktie steht noch aus oder ist fehlgeschlagen.")
                elif not snapshot_store.item_has_price_data(item):
                    st.caption("Für diese Aktie kamen beim letzten Abruf keine Kursdaten. Der Score ist daher nicht aussagekräftig.")
                if item.get("brodel_v2_estimated"):
                    st.caption("Brodel 2.0 aus einem älteren Snapshot nachgerechnet (ohne Rückkauf-Daten und ohne Makro-Overlay).")
                if item["resolved"]:
                    st.caption(f"Eingabe: {item['input_name']} | {item['resolution_note']}")
            with head_col2:
                if st.button(f"🔄 Daten für {item['symbol']} neu laden", key=f"btn_refresh_{item['symbol']}"):
                    get_extended_fundamentals.clear(item["symbol"])
                    st.rerun()

            # Extended Fundamentals & Profile
            with st.spinner("Lade Unternehmenszahlen & Profil..."):
                ext = get_extended_fundamentals(item["symbol"])

            detail_tab_signals, detail_tab_fundamentals = st.tabs(["🔥 Brodel-Index Kalkulation", "🏢 Unternehmenswerte"])

            with detail_tab_signals:
                col1, col2 = st.columns(2)
                with col1:
                    st.markdown("**Signal-Zusammenfassung**")
                    if item.get("signal_items"):
                        for detail in item.get("signal_items", []):
                            st.markdown(f"- {detail}")
                    else:
                        st.markdown("- Keine aussagekraeftigen Fruehsignale erkannt.")

                with col2:
                    peer_context = item.get("peer_context", {})
                    st.markdown("**Peer- und Sektor-Kontext**")
                    st.markdown(
                        f"- Sektor: {peer_context.get('sector', 'Unbekannt')} | Branche: {peer_context.get('industry', 'Unbekannt')}"
                    )
                    st.markdown(
                        f"- Sektor-Durchschnitt: {peer_context.get('sector_average', 0)} | Abstand: {peer_context.get('score_vs_sector', 0)} | Rang: {peer_context.get('sector_rank', 1)}/{peer_context.get('sector_count', 1)}"
                    )
                    top_peer = peer_context.get("top_peer")
                    if top_peer:
                        st.markdown(
                            f"- Staerkster Peer in der Watchlist: {top_peer['symbol']} - {top_peer['name']} | Score {top_peer['score']}"
                        )
                    else:
                        st.markdown("- Kein weiterer Peer im gleichen Sektor innerhalb der Watchlist.")

                st.markdown("**Signal-Breakdown**")
                breakdown_rows = build_breakdown_rows(item)
                st.dataframe(
                    pd.DataFrame(breakdown_rows),
                    use_container_width=True,
                    hide_index=True,
                    height=breakdown_table_height(len(breakdown_rows)),
                    column_config={"Detail": st.column_config.TextColumn("Detail", width="large")},
                )

                st.markdown("---")
                st.markdown("**Score-Verlauf (letzte 100 Tage)**")
                if not score_history.empty:
                    symbol_history = score_history[score_history["symbol"] == selected_symbol].copy()
                    if not symbol_history.empty:
                        symbol_history["timestamp"] = pd.to_datetime(symbol_history["timestamp"])
                        last_100_days = pd.Timestamp.utcnow().normalize() - pd.Timedelta(days=100)
                        symbol_history = symbol_history[symbol_history["timestamp"] >= last_100_days]
                        symbol_history = symbol_history.sort_values("timestamp")
                        
                        if len(symbol_history) > 1:
                            chart_data = symbol_history.set_index("timestamp")[["brodel_score_v2", "brodel_score"]].rename(
                                columns={"brodel_score_v2": "Brodel 2.0", "brodel_score": "Brodel 1.0"}
                            )
                            st.line_chart(chart_data)
                        else:
                            st.info("Nicht genuegend Historien-Daten fuer ein Diagramm (mindestens 2 Snapshots benoetigt).")
                    else:
                        st.info("Noch keine Verlaufsdaten fuer diese Aktie vorhanden.")
                else:
                    st.info("Noch keine Verlaufsdaten vorhanden.")

            with detail_tab_fundamentals:
                st.markdown("#### 🏢 Unternehmensprofil")
                st.info(ext.get("summary_de", "Keine Zusammenfassung verfuegbar."))

                p_cols = st.columns(4)
                p_cols[0].metric("Sektor", ext.get("sector_de", "-"))
                p_cols[1].metric("Branche", ext.get("industry_de", "-"))
                p_cols[2].metric("Hauptsitz", f"{ext.get('city', '-')}, {ext.get('country', '-')}")
                emp = ext.get("employees")
                p_cols[3].metric("Mitarbeiter", f"{emp:,}" if emp else "-")

                st.markdown("#### 📈 Zukünftig geschätzter Wert & Analysten-Konsens")
                v_cols = st.columns(4)
                curr_price = ext.get("current_price")
                target_mean = ext.get("target_mean_price")
                target_med = ext.get("target_median_price")
                upside = ext.get("upside_pct")
                curr_str = ext.get("currency", "EUR")

                v_cols[0].metric(
                    "Aktueller Kurs",
                    f"{curr_price:.2f} {curr_str}" if curr_price else "n/a"
                )
                v_cols[1].metric(
                    "Kursziel (Mittelwert)",
                    f"{target_mean:.2f} {curr_str}" if target_mean else "n/a",
                    help="Durchschnittliches Kursziel der Analysten"
                )
                v_cols[2].metric(
                    "Aufwärtspotenzial",
                    f"{upside:+.1f} %" if upside is not None else "n/a",
                    delta=f"{upside:+.1f} %" if upside is not None else None,
                    help="Prozentualer Abstand zum mittleren Analysten-Kursziel"
                )
                imp_mc = ext.get("implied_market_cap")
                if imp_mc:
                    imp_str = f"{imp_mc / 1e9:.2f} Mrd. {curr_str}" if imp_mc >= 1e9 else f"{imp_mc / 1e6:.1f} Mio. {curr_str}"
                else:
                    imp_str = "n/a"
                v_cols[3].metric(
                    "Implizite Marktkapitalisierung",
                    imp_str,
                    help="Erwartete Marktkapitalisierung bei Erreichen des mittleren Analystenkursziels"
                )

                st.markdown("#### 📊 Bruttogewinn & Bruttomarge")
                m_cols = st.columns(3)
                ttm_margin = ext.get("gross_margin_ttm")
                gm_hist = ext.get("gross_margin_history", [])
                latest_gp = gm_hist[-1]["Bruttogewinn"] if gm_hist else None
                latest_rev = gm_hist[-1]["Umsatz"] if gm_hist else None

                m_cols[0].metric(
                    "Bruttomarge (TTM)",
                    f"{ttm_margin:.1f} %" if ttm_margin is not None else "n/a",
                    help="Bruttomarge der letzten 12 Monate (Gross Margin TTM)"
                )
                if latest_gp is not None:
                    gp_str = f"{latest_gp / 1e9:.2f} Mrd. {curr_str}" if abs(latest_gp) >= 1e9 else f"{latest_gp / 1e6:.1f} Mio. {curr_str}"
                else:
                    gp_str = "n/a"
                m_cols[1].metric(
                    f"Bruttogewinn ({gm_hist[-1]['Jahr']})" if gm_hist else "Letzter Bruttogewinn",
                    gp_str,
                    help="Gross Profit des letzten vollständigen Geschäftsjahres"
                )
                if latest_rev is not None:
                    rev_str = f"{latest_rev / 1e9:.2f} Mrd. {curr_str}" if abs(latest_rev) >= 1e9 else f"{latest_rev / 1e6:.1f} Mio. {curr_str}"
                else:
                    rev_str = "n/a"
                m_cols[2].metric(
                    f"Umsatz ({gm_hist[-1]['Jahr']})" if gm_hist else "Letzter Jahresumsatz",
                    rev_str,
                    help="Total Revenue des letzten vollständigen Geschäftsjahres"
                )

                if gm_hist:
                    st.caption("Historischer Verlauf von Bruttogewinn und Bruttomarge (geprüfte Jahresabschlüsse):")
                    gm_display_rows = []
                    for row in gm_hist:
                        rev_fmt = f"{row['Umsatz'] / 1e9:.2f} Mrd." if row['Umsatz'] and abs(row['Umsatz']) >= 1e9 else (f"{row['Umsatz'] / 1e6:.1f} Mio." if row['Umsatz'] else "-")
                        gp_fmt = f"{row['Bruttogewinn'] / 1e9:.2f} Mrd." if row['Bruttogewinn'] and abs(row['Bruttogewinn']) >= 1e9 else (f"{row['Bruttogewinn'] / 1e6:.1f} Mio." if row['Bruttogewinn'] else "-")
                        gm_display_rows.append({
                            "Jahr": str(row["Jahr"]),
                            f"Umsatz ({curr_str})": rev_fmt,
                            f"Bruttogewinn ({curr_str})": gp_fmt,
                            "Bruttomarge (%)": f"{row['Bruttomarge']:.1f} %" if row['Bruttomarge'] is not None else "n/a",
                            "_margin_raw": row["Bruttomarge"],
                        })
                    gm_df = pd.DataFrame(gm_display_rows)
                    gmc1, gmc2 = st.columns([1, 1])
                    with gmc1:
                        st.dataframe(gm_df[["Jahr", f"Umsatz ({curr_str})", f"Bruttogewinn ({curr_str})", "Bruttomarge (%)"]], use_container_width=True, hide_index=True)
                    with gmc2:
                        chart_df = gm_df.dropna(subset=["_margin_raw"]).set_index("Jahr")[["_margin_raw"]]
                        chart_df.columns = ["Bruttomarge (%)"]
                        if not chart_df.empty:
                            st.bar_chart(chart_df)
                else:
                    st.info("Keine historischen Bruttogewinn-Daten ausgewiesen (typisch für Finanzinstitute/Banken oder ETFs).")

                st.markdown("#### ⚙️ Operative Kosten & Aufwand (OpEx)")
                op_cols = st.columns(5)
                ttm_op_margin = ext.get("operating_margin_ttm")
                oc_hist = ext.get("operating_cost_history", [])
                latest_opex = oc_hist[-1]["OpEx"] if oc_hist else None
                latest_fe = oc_hist[-1]["FE"] if oc_hist else None
                latest_sga = oc_hist[-1]["SGA"] if oc_hist else None
                latest_ebit = (oc_hist[-1].get("Operativer_Gewinn") if oc_hist[-1].get("Operativer_Gewinn") is not None else oc_hist[-1].get("EBIT")) if oc_hist else None
                latest_op_margin = oc_hist[-1].get("Operative_Marge") if oc_hist else None
                latest_opex_quote = oc_hist[-1].get("OpEx_Quote") if oc_hist else None
                latest_fe_quote = oc_hist[-1]["FE_Quote"] if oc_hist else None
                latest_sga_quote = oc_hist[-1]["SGA_Quote"] if oc_hist else None
                latest_year = oc_hist[-1]["Jahr"] if oc_hist else None

                op_cols[0].metric(
                    "Operative Marge (TTM)",
                    f"{ttm_op_margin:.1f} %" if ttm_op_margin is not None else "n/a",
                    help="Operative Marge (Operating Margin) der letzten 12 Monate"
                )

                if latest_ebit is not None:
                    ebit_str = f"{latest_ebit / 1e9:.2f} Mrd. {curr_str}" if abs(latest_ebit) >= 1e9 else f"{latest_ebit / 1e6:.1f} Mio. {curr_str}"
                else:
                    ebit_str = "n/a"
                op_cols[1].metric(
                    f"EBIT / Op. Gewinn ({latest_year})" if latest_year else "EBIT / Op. Gewinn",
                    ebit_str,
                    delta=f"{latest_op_margin:+.1f} % Marge" if latest_op_margin is not None else None,
                    delta_color="normal",
                    help="Operativer Gewinn (Earnings Before Interest and Taxes / Operating Income) des letzten vollständigen Geschäftsjahres"
                )

                if latest_opex is not None:
                    opex_str = f"{latest_opex / 1e9:.2f} Mrd. {curr_str}" if abs(latest_opex) >= 1e9 else f"{latest_opex / 1e6:.1f} Mio. {curr_str}"
                else:
                    opex_str = "n/a"
                op_cols[2].metric(
                    f"OpEx gesamt ({latest_year})" if latest_year else "Letzte OpEx gesamt",
                    opex_str,
                    delta=f"{latest_opex_quote:.1f} % v. Umsatz" if latest_opex_quote is not None else None,
                    delta_color="off",
                    help="Gesamte operative Betriebskosten (Operating Expenses) des letzten Geschäftsjahres"
                )

                if latest_fe is not None:
                    fe_str = f"{latest_fe / 1e9:.2f} Mrd. {curr_str}" if abs(latest_fe) >= 1e9 else f"{latest_fe / 1e6:.1f} Mio. {curr_str}"
                else:
                    fe_str = "n/a"
                op_cols[3].metric(
                    f"F&E / R&D ({latest_year})" if latest_year else "Forschung & Entwicklung",
                    fe_str,
                    delta=f"{latest_fe_quote:.1f} % v. Umsatz" if latest_fe_quote is not None else None,
                    delta_color="off",
                    help="Aufwendungen für Forschung und Entwicklung (Research & Development)"
                )

                if latest_sga is not None:
                    sga_str = f"{latest_sga / 1e9:.2f} Mrd. {curr_str}" if abs(latest_sga) >= 1e9 else f"{latest_sga / 1e6:.1f} Mio. {curr_str}"
                else:
                    sga_str = "n/a"
                op_cols[4].metric(
                    f"SG&A ({latest_year})" if latest_year else "Vertrieb & Verwaltung",
                    sga_str,
                    delta=f"{latest_sga_quote:.1f} % v. Umsatz" if latest_sga_quote is not None else None,
                    delta_color="off",
                    help="Aufwendungen für Vertrieb, Verwaltung und Allgemeines (Selling, General & Administrative)"
                )

                if oc_hist and any(row.get("OpEx") is not None or row.get("FE") is not None or row.get("SGA") is not None for row in oc_hist):
                    st.caption("Historischer Verlauf der operativen Kosten & Aufwandsaufschlüsselung:")
                    oc_display_rows = []
                    chart_rows = []
                    for row in oc_hist:
                        rev_f = f"{row['Umsatz'] / 1e9:.2f} Mrd." if row['Umsatz'] and abs(row['Umsatz']) >= 1e9 else (f"{row['Umsatz'] / 1e6:.1f} Mio." if row['Umsatz'] else "-")
                        eb_val = row.get("Operativer_Gewinn") if row.get("Operativer_Gewinn") is not None else row.get("EBIT")
                        ebit_f = f"{eb_val / 1e9:.2f} Mrd." if eb_val and abs(eb_val) >= 1e9 else (f"{eb_val / 1e6:.1f} Mio." if eb_val else "-")
                        opex_f = f"{row['OpEx'] / 1e9:.2f} Mrd." if row['OpEx'] and abs(row['OpEx']) >= 1e9 else (f"{row['OpEx'] / 1e6:.1f} Mio." if row['OpEx'] else "-")
                        fe_f = f"{row['FE'] / 1e9:.2f} Mrd." if row['FE'] and abs(row['FE']) >= 1e9 else (f"{row['FE'] / 1e6:.1f} Mio." if row['FE'] else "-")
                        sga_f = f"{row['SGA'] / 1e9:.2f} Mrd." if row['SGA'] and abs(row['SGA']) >= 1e9 else (f"{row['SGA'] / 1e6:.1f} Mio." if row['SGA'] else "-")
                        
                        oc_display_rows.append({
                            "Jahr": str(row["Jahr"]),
                            f"Umsatz ({curr_str})": rev_f,
                            f"EBIT ({curr_str})": ebit_f,
                            f"OpEx ({curr_str})": opex_f,
                            f"F&E ({curr_str})": fe_f,
                            f"SG&A ({curr_str})": sga_f,
                            "Op. Marge (%)": f"{row['Operative_Marge']:.1f} %" if row.get("Operative_Marge") is not None else "n/a",
                            "OpEx-Quote (%)": f"{row['OpEx_Quote']:.1f} %" if row.get("OpEx_Quote") is not None else "n/a",
                        })

                        fe_val_m = (row["FE"] / 1e6) if row.get("FE") is not None else 0.0
                        sga_val_m = (row["SGA"] / 1e6) if row.get("SGA") is not None else 0.0
                        if fe_val_m > 0 or sga_val_m > 0:
                            chart_rows.append({
                                "Jahr": str(row["Jahr"]),
                                f"F&E (Mio. {curr_str})": fe_val_m,
                                f"SG&A (Mio. {curr_str})": sga_val_m,
                            })

                    oc_df = pd.DataFrame(oc_display_rows)
                    occ1, occ2 = st.columns([1, 1])
                    with occ1:
                        st.dataframe(oc_df, use_container_width=True, hide_index=True)
                    with occ2:
                        if chart_rows:
                            chart_df = pd.DataFrame(chart_rows).set_index("Jahr")
                            st.caption(f"Aufwandssplit F&E vs. SG&A (in Mio. {curr_str}):")
                            st.bar_chart(chart_df)
                        else:
                            st.info("Keine detaillierte Aufteilung in F&E / SG&A verfügbar.")
                else:
                    st.info("Keine klassischen operativen Kosten (OpEx / F&E) im Geschäftsbericht ausgewiesen (typisch für Banken, Versicherungen oder Finanzdienstleister).")

                st.markdown("#### 📊 KGV-Analyse & Bewertung")
                k_cols = st.columns(2)
                curr_pe = ext.get("trailing_pe")
                fwd_pe = ext.get("forward_pe")
                k_cols[0].metric(
                    "Aktuelles KGV (Trailing)",
                    f"{curr_pe:.1f}" if curr_pe else "n/a",
                    help="Kurs-Gewinn-Verhaeltnis bezogen auf die letzten 12 Monate",
                )
                k_cols[1].metric(
                    "KGV (Forward)",
                    f"{fwd_pe:.1f}" if fwd_pe else "n/a",
                    help="Erwartetes KGV auf Basis von Analystenschaetzungen",
                )

                pe_trend = ext.get("pe_trend", [])
                if pe_trend:
                    st.caption("Historischer KGV-Verlauf der letzten Geschäftsjahre:")
                    pe_df = pd.DataFrame(pe_trend)
                    disp_cols = [c for c in ["Jahr", "Kurs", "KGV"] if c in pe_df.columns]
                    pe_c1, pe_c2 = st.columns([2, 1])
                    with pe_c1:
                        chart_pe = pe_df.dropna(subset=["KGV"]).set_index("Jahr")[["KGV"]]
                        if not chart_pe.empty:
                            st.line_chart(chart_pe)
                    with pe_c2:
                        st.dataframe(pe_df[disp_cols] if disp_cols else pe_df, use_container_width=True, hide_index=True)
                else:
                    st.info("Keine historischen KGV-Jahresabschluesse fuer diesen Titel verfuegbar.")

                st.markdown("#### 💰 Dividenden-Analyse & Historie")
                d_cols = st.columns(3)
                d_yield = ext.get("dividend_yield_pct")
                d_rate = ext.get("dividend_rate")
                d_streak = ext.get("dividend_streak_years", 0)

                d_cols[0].metric(
                    "Dividendenrendite",
                    f"{d_yield:.2f} %" if d_yield is not None else "0.00 %",
                )
                d_cols[1].metric(
                    "Dividende (Zahlung)",
                    f"{d_rate:.2f} {curr_str}" if d_rate is not None else "0.00",
                )
                if d_streak > 0:
                    d_cols[2].metric(
                        "Dividenden-Steigerung",
                        f"{d_streak} Jahre in Folge 🏆",
                        help="Anzahl aufeinanderfolgender Jahre mit gesteigerter Jahresdividende.",
                    )
                else:
                    d_cols[2].metric(
                        "Dividenden-Steigerung",
                        "0 Jahre",
                        help="Keine mehrjaehrige Steigerungsserie vorhanden.",
                    )

                div_hist = ext.get("dividend_history", [])
                if div_hist:
                    st.caption("Dividenden-Verlauf der letzten 15 Jahre (Rendite & Ausschuettung):")
                    div_df = pd.DataFrame(div_hist)
                    div_c1, div_c2 = st.columns([2, 1])
                    with div_c1:
                        div_chart = div_df.set_index("Jahr")[["Dividende"]]
                        st.bar_chart(div_chart)
                    with div_c2:
                        st.dataframe(div_df, use_container_width=True, hide_index=True)
                else:
                    st.info("Keine Dividenden-Historie fuer diesen Titel vorhanden.")

def render_truth_machine_help():
    """Plain-language help for the truth machine and its ETF benchmark."""
    st.markdown("### 🧪 Die Wahrheitsmaschine einfach erklärt")
    st.write(
        "Die Wahrheitsmaschine beantwortet eine einzige Frage: Hätte man mit dieser Aktien-Strategie in den letzten 20 Jahren "
        "mehr Geld verdient als mit einem ganz normalen ETF? Gezählt wird erst, nachdem Gebühren und deutsche Steuern bezahlt sind. "
        "Du findest sie im Reiter **Backtest & ML** ganz oben."
    )

    with st.expander("1. Die Grundidee: faul gegen fleißig"):
        st.markdown(
            "Stell dir vor, du bekommst **100.000 € Spielgeld** und hast zwei Möglichkeiten:\n\n"
            "- **Faul:** Du kaufst am ersten Tag einen ETF und machst 20 Jahre lang gar nichts.\n"
            "- **Fleißig:** Jeden Monat suchst du nach festen Regeln die 20 „besten“ Aktien aus und tauschst dein Depot um.\n\n"
            "Die Wahrheitsmaschine spielt beide Wege mit den echten Kursen der Vergangenheit durch. Am Ende vergleicht sie, wer mehr Geld auf dem Konto hat."
        )
        st.markdown(
            "**Warum heißt sie Wahrheitsmaschine?** Weil sie nicht schummeln darf. An jedem Tag kennt sie nur die Kurse bis zu diesem Tag. "
            "Sie weiß im Jahr 2008 also nicht, dass Apple später riesig wird. Und sie zieht jede Gebühr und jeden Euro Steuer ab, so wie es im echten Leben passiert."
        )
        st.info("Wenn der fleißige Weg nicht gewinnt, lohnt sich die viele Arbeit nicht. Dann ist der ETF die bessere Wahl. Genau das soll die Maschine herausfinden, bevor echtes Geld im Spiel ist.")

    with st.expander("2. Was ist ein ETF, und welche ETFs stehen zur Auswahl?"):
        st.markdown(
            "Ein **ETF** ist wie eine Tüte gemischter Süßigkeiten. Statt eine einzelne Sorte zu kaufen, bekommst du mit einem Griff alle Sorten auf einmal. "
            "Ein S&P-500-ETF enthält zum Beispiel die 500 größten Firmen der USA.\n\n"
            "- Geht eine Firma pleite, merkst du das kaum, weil die anderen 499 noch da sind.\n"
            "- Ein ETF kostet sehr wenig Gebühren, und du musst nichts tun.\n"
            "- Darum ist er der Gegner, den jede Strategie schlagen muss. Profis nennen so einen Gegner **Benchmark**, auf Deutsch **Messlatte**."
        )
        st.markdown("**Die vier ETFs in der App:**")
        st.table(pd.DataFrame([
            {"Kürzel": "SPY", "Was steckt drin": "die 500 größten US-Firmen (S&P 500)", "Passendes Universum": "S&P 500"},
            {"Kürzel": "QQQ", "Was steckt drin": "die 100 größten Firmen der Technologiebörse Nasdaq, ohne Banken, sehr viel Technik", "Passendes Universum": "Nasdaq-100"},
            {"Kürzel": "DIA", "Was steckt drin": "30 bekannte US-Großkonzerne aus dem Dow Jones", "Passendes Universum": "Dow Jones"},
            {"Kürzel": "URTH", "Was steckt drin": "rund 1.400 Firmen aus 23 Industrieländern (MSCI World)", "Passendes Universum": "keins direkt, dient als Vergleich mit dem „Welt-ETF“"},
        ]))
        st.markdown(
            "**Tipp:** Nimm den ETF, der zum Universum passt. Wer Aktien aus dem S&P 500 auswählt, sollte gegen SPY antreten. "
            "Sonst vergleichst du Äpfel mit Birnen.\n\n"
            "**Gut zu wissen:** SPY, QQQ, DIA und URTH sind amerikanische ETFs. In Deutschland kauft man meist eine europäische Version, "
            "zum Beispiel einen S&P-500-ETF mit „UCITS“ im Namen. Der verläuft fast genauso. Deshalb taugt SPY trotzdem als Messlatte."
        )

    with st.expander("3. So wird der ETF im Test genau behandelt"):
        st.markdown(
            "Der ETF spielt den faulen Anleger. Er bekommt genau diese Regeln:\n\n"
            "1. **Kauf am Start:** Am ersten Handelstag des Tests wird das ganze Startkapital von 100.000 in den ETF gesteckt. Dafür fallen 0,1 % Gebühr an.\n"
            "2. **Nichts tun:** Danach wird nichts mehr verändert. Kein Umschichten und kein Trendfilter. Der ETF bleibt immer zu 100 % investiert, auch mitten im Börsencrash.\n"
            "3. **Dividenden:** Ausschüttungen werden automatisch wieder angelegt. Sie stecken schon in den bereinigten Kursen von Yahoo Finance.\n"
            "4. **Verkauf am Ende:** Am letzten Tag wird alles verkauft. Dafür fallen noch einmal 0,1 % Gebühr an.\n"
            "5. **Steuer nur einmal, ganz am Ende.** Gerechnet wird so:"
        )
        st.code(
            "Gewinn           = Verkaufserlös - 100.000\n"
            "steuerpflichtig  = Gewinn x 70 %             (30 % Teilfreistellung)\n"
            "nach Freibetrag  = steuerpflichtig - 1.000   (Sparerpauschbetrag)\n"
            "Steuer           = nach Freibetrag x 26,375 %",
            language=None,
        )
        st.markdown(
            "**Rechenbeispiel, vereinfacht ohne Gebühren:** Aus 100.000 € werden in 20 Jahren 400.000 €.\n\n"
            "- Der Gewinn beträgt 300.000 €.\n"
            "- 30 % davon sind steuerfrei. Steuerpflichtig bleiben 210.000 €.\n"
            "- Nach Abzug des Freibetrags bleiben 209.000 €.\n"
            "- Die Steuer darauf beträgt rund 55.124 €.\n"
            "- Am Ende hast du also rund **344.876 €** auf dem Konto."
        )
        st.markdown(
            "**Was ist die Teilfreistellung?** Ein Aktienfonds zahlt intern schon Steuern auf Dividenden, bevor du etwas davon siehst. "
            "Damit nicht doppelt kassiert wird, lässt der deutsche Staat 30 % deines Gewinns aus Aktien-ETFs steuerfrei. "
            "Für einzelne Aktien gibt es das nicht.\n\n"
            "**Der versteckte Vorteil des ETF:** Weil er erst am Ende Steuern zahlt, bleibt das Steuergeld 20 Jahre lang im Depot und arbeitet mit. "
            "Das ist wie ein Schneeball, der beim Rollen immer größer wird. Wer jeden Monat verkauft und Steuer zahlt, nimmt dem Schneeball ständig etwas weg."
        )
        st.markdown(
            "**Was beim ETF vereinfacht ist:**\n\n"
            "- **Vorabpauschale:** In echt zahlt man beim ETF jedes Jahr eine kleine Steuer-Vorauszahlung. Die fehlt im Test. Das lässt den ETF etwas besser aussehen.\n"
            "- **Freibetrag:** Der ETF nutzt den Sparerpauschbetrag nur einmal am Ende. Die Strategie darf ihn jedes Jahr nutzen. Das hilft der Strategie etwas.\n"
            "- **Laufende Kosten:** Die jährliche Fondsgebühr steckt bei SPY schon im Kurs.\n"
            "- **Kirchensteuer** wird nicht berechnet.\n"
            "- **Währung:** Alles wird in Dollar gerechnet, ohne Umtausch in Euro. Das gilt für beide Seiten gleich, der Vergleich bleibt also fair."
        )

    with st.expander("4. So funktioniert die Aktien-Strategie"):
        st.markdown(
            "Die Strategie spielt den fleißigen Anleger. Jeden Monat läuft dasselbe ab:\n\n"
            "1. **Zeugnistag am Monatsende:** Jede Aktie im Universum bekommt Noten. Diese Noten heißen **Faktoren**, sie werden im nächsten Abschnitt erklärt.\n"
            "2. **Rangliste:** Aus den Noten wird eine Rangliste wie in der Klasse. Die beste Aktie bekommt fast 100 %, die schlechteste fast 0 %. "
            "Bei mehreren Faktoren zählt der Durchschnitt der Ränge.\n"
            "3. **Auswahl:** Die besten 20 Aktien werden gekauft, jede mit gleich viel Geld, also je 5 %.\n"
            "4. **Ein Tag Abstand:** Gekauft wird erst am nächsten Handelstag. So kann die Maschine nicht mit dem Wissen von heute zum Preis von heute handeln.\n"
            "5. **Umtausch nach einem Monat:** Wer aus den Top 20 fällt, wird verkauft. Neue Aufsteiger werden gekauft.\n"
            "6. **Am Ende** wird alles verkauft, und die letzte Steuer wird fällig."
        )
        st.markdown(
            "**Gebühren und Steuern bei der Strategie:**\n\n"
            "- Jeder Kauf und jeder Verkauf kostet 0,1 % Gebühr.\n"
            "- Bei jedem Verkauf mit Gewinn behält die Bank sofort 26,375 % Steuer ein, so wie ein deutscher Broker. Dieses Geld fehlt dann für die nächsten Käufe.\n"
            "- Verluste wandern in den **Verlusttopf**. Sie werden mit späteren Gewinnen verrechnet, auch über Jahre hinweg.\n"
            "- Pro Jahr sind 1.000 € Gewinn steuerfrei, das ist der **Sparerpauschbetrag**."
        )
        st.warning("Monatliches Umschichten ist teuer. Im ersten Testlauf hat die laufende Steuer etwa ein Viertel der Rendite aufgefressen. Je seltener verkauft wird, desto besser für den Schneeball.")

    with st.expander("5. Die Faktoren: nach welchen Noten wird sortiert?"):
        st.table(pd.DataFrame([
            {"Faktor": "momentum_12_1", "Einfach erklärt": "Wie stark ist die Aktie in den letzten 12 Monaten gestiegen? Der jüngste Monat wird weggelassen.",
             "Idee dahinter": "Gewinner bleiben oft eine Weile Gewinner. Der letzte Monat zählt nicht, weil Aktien nach einem starken Monat oft kurz zurückfallen."},
            {"Faktor": "momentum_6_1", "Einfach erklärt": "Dasselbe, aber nur über 6 Monate.", "Idee dahinter": "Eine kürzere, schnellere Version von Momentum."},
            {"Faktor": "low_volatility", "Einfach erklärt": "Wie ruhig ist die Aktie? Wenig Schwankung im letzten Jahr gibt eine gute Note.",
             "Idee dahinter": "Ruhige Aktien bringen erstaunlich oft ähnliche Renditen mit weniger Stress."},
            {"Faktor": "reversal_1m", "Einfach erklärt": "Wer im letzten Monat am stärksten gefallen ist, bekommt die beste Note.",
             "Idee dahinter": "Kurze Übertreibungen drehen oft wieder. Achtung: sehr viel Umschichten, also viel Gebühren und Steuer."},
            {"Faktor": "trend_200d", "Einfach erklärt": "Wie weit liegt der Kurs über seinem Durchschnitt der letzten 200 Handelstage?",
             "Idee dahinter": "Wer über seinem Durchschnitt liegt, steckt in einem Aufwärtstrend."},
        ]))
        st.write(
            "Alle Faktoren werden nur aus Kursen berechnet. Der Grund: Nur Kurse gibt es kostenlos für 20 Jahre rückwirkend. "
            "Was Analysten 2008 über eine Aktie dachten, lässt sich heute nicht mehr abrufen. Deshalb kann die Wahrheitsmaschine den Brodel-Score selbst nicht über 20 Jahre testen."
        )

    with st.expander("6. Alle Einstellungen erklärt"):
        st.table(pd.DataFrame([
            {"Einstellung": "Universum", "Was sie macht": "Aus welchem Topf die Aktien ausgewählt werden.", "Standard": "S&P 500"},
            {"Einstellung": "Benchmark-ETF", "Was sie macht": "Der Gegner, gegen den die Strategie antritt.", "Standard": "SPY"},
            {"Einstellung": "Startjahr", "Was sie macht": "Ab wann gerechnet wird. Die Kurse werden ein Jahr früher geladen, damit der 12-Monats-Faktor schon am Start eine Note hat.", "Standard": "2005"},
            {"Einstellung": "Anzahl Aktien", "Was sie macht": "Wie viele Aktien gleichzeitig im Depot sind. Wenige Aktien bedeuten mehr Chance, aber auch mehr Risiko.", "Standard": "20"},
            {"Einstellung": "Faktoren", "Was sie macht": "Welche Noten zählen. Alle gewählten Faktoren zählen gleich viel.", "Standard": "momentum_12_1 und low_volatility"},
            {"Einstellung": "Bisher getestete Varianten", "Was sie macht": "Wie oft du schon verschiedene Einstellungen ausprobiert hast. Bitte ehrlich eintragen.", "Standard": "1"},
            {"Einstellung": "Trendfilter", "Was sie macht": "Liegt der ETF unter seiner 200-Tage-Linie, investiert die Strategie weniger.", "Standard": "an"},
            {"Einstellung": "Investitionsquote im Abwärtstrend", "Was sie macht": "Wie viel bei aktivem Trendfilter noch in Aktien steckt. Der Rest liegt als Bargeld ohne Zinsen.", "Standard": "50 %"},
            {"Einstellung": "Deutsche Steuer berücksichtigen", "Was sie macht": "Schaltet die Steuer für beide Seiten ein oder aus. Ausgeschaltet dient nur zum Vergleich.", "Standard": "an"},
        ]))
        st.markdown(
            "**Der Trendfilter einfach erklärt:** Die 200-Tage-Linie ist der Durchschnittskurs der letzten 200 Handelstage, also etwa der letzten zehn Monate. "
            "Sie ist wie eine Wetterfahne. Liegt der Kurs des ETF darunter, herrscht an der Börse eher Regenwetter. Dann hält die Strategie nur noch die Hälfte in Aktien. "
            "Geprüft wird jeweils am Monatsende. Der Trendfilter gilt nur für die Strategie, der ETF bleibt immer voll investiert."
        )
        st.markdown(
            "**Warum „Bisher getestete Varianten“ so wichtig ist:** Lass 100 Leute je zehnmal eine Münze werfen. Einer davon wirft wahrscheinlich neunmal Kopf. "
            "Ist er ein Münzwurf-Genie? Nein, das ist Zufall. Genauso findet man durch Herumprobieren irgendwann zufällig eine Einstellung, die in der Vergangenheit toll aussah. "
            "Je mehr Varianten du einträgst, desto strenger wird die Prüfung in der Deflated Sharpe Ratio."
        )
        st.markdown(
            "**Fest eingestellt und in der App nicht änderbar:**\n\n"
            "- Startkapital 100.000\n"
            "- Gebühr 0,1 % pro Kauf und Verkauf\n"
            "- Umschichten einmal im Monat\n"
            "- Gleiche Gewichtung aller ausgewählten Aktien\n"
            "- Steuersatz 26,375 %, das sind 25 % Abgeltungssteuer plus Solidaritätszuschlag, ohne Kirchensteuer\n"
            "- Sparerpauschbetrag 1.000 € pro Jahr\n"
            "- Teilfreistellung 30 % für den ETF\n\n"
            "Über die Kommandozeile mit `python -m factor_lab --help` lassen sich einige davon ändern, zum Beispiel Gebühr, Umschicht-Rhythmus und Sektorgrenze."
        )

    with st.expander("7. Die Ergebnisse lesen"):
        st.markdown(
            "**Zeitraum und Universum** zeigen, von wann bis wann gerechnet wurde und wie viele Aktien im Topf waren.\n\n"
            "**Das Urteil** wird automatisch aus den Zahlen geschrieben. Niemand hat es schöngeredet."
        )
        st.table(pd.DataFrame([
            {"Zeile": "Rendite p. a. (Depotwert)", "Bedeutung": "Um wie viel Prozent der Depotwert im Schnitt pro Jahr gewachsen ist. Bei der Strategie ist die laufende Steuer schon abgezogen, beim ETF noch nicht."},
            {"Zeile": "Rendite p. a. nach Endverkauf und Steuer", "Bedeutung": "Die wichtigste Zeile. Beide Seiten verkaufen am Ende alles und haben alle Steuern bezahlt. Erst das ist ein fairer Vergleich."},
            {"Zeile": "Volatilität p. a.", "Bedeutung": "Wie stark der Wert schwankt. Wie bei einer Achterbahn: Ein hoher Wert bedeutet eine wilde Fahrt."},
            {"Zeile": "Maximaler Verlust", "Bedeutung": "Der größte Absturz vom bisherigen Höchststand. −24 % heißt: Aus 100 € wurden zwischendurch 76 €."},
            {"Zeile": "Sharpe Ratio", "Bedeutung": "Rendite pro Schwankung, ähnlich wie Tore pro Spielminute. Bei Aktien ist 0,5 normal und über 1 sehr gut."},
            {"Zeile": "Endvermögen nach Steuern", "Bedeutung": "Was am Ende wirklich auf dem Konto bleibt, ausgehend von 100.000."},
            {"Zeile": "Gezahlte Steuern", "Bedeutung": "Alle Steuern zusammen, die über den ganzen Zeitraum ans Finanzamt gingen."},
            {"Zeile": "Transaktionskosten", "Bedeutung": "Alle Gebühren für Käufe und Verkäufe der Strategie."},
        ]))
        st.markdown(
            "**Die Vermögenskurve** zeigt beide Wege als Linien über die Zeit. Die ETF-Linie ist vor Steuer gezeichnet, weil der ETF erst am Ende zahlt. "
            "Deshalb ist sein Endvermögen in der Tabelle etwas niedriger als das Ende der Linie.\n\n"
            "**Warum wenige Prozentpunkte so viel ausmachen:** 7,5 % gegen 10 % pro Jahr klingt nach wenig. Über 20 Jahre wird daraus aber ein riesiger Unterschied:"
        )
        st.code(
            "100.000 mit  7,5 % pro Jahr über 20 Jahre = rund 425.000\n"
            "100.000 mit 10,0 % pro Jahr über 20 Jahre = rund 673.000",
            language=None,
        )

    with st.expander("8. Die Statistik: Rank-IC, t-Wert, Deflated Sharpe und Walk-forward"):
        st.markdown(
            "**Rank-IC:** Jeden Monat wird geprüft, ob die Rangliste der Noten zur Rangliste der späteren Renditen passt. "
            "+1 heißt perfekt vorhergesagt, 0 heißt reiner Zufall, −1 heißt genau falsch herum. "
            "In der Praxis sind schon 0,03 bis 0,05 gut. Das ist wie eine Wettervorhersage, die nur etwas besser als Raten ist, dafür aber jeden Tag.\n\n"
            "**t-Wert:** Er sagt, wie sicher es ist, dass der Rank-IC kein Zufall ist. Ab 2 gilt ein Effekt als **signifikant**, also wahrscheinlich echt.\n\n"
            "**Trefferquote:** In wie viel Prozent der Monate die Noten in die richtige Richtung gezeigt haben. 50 % ist so gut wie ein Münzwurf.\n\n"
            "**Monate:** Wie viele Messungen es gab. Mehr Messungen machen das Ergebnis verlässlicher.\n\n"
            "**composite:** Die gemeinsame Note aus allen gewählten Faktoren. Nach ihr wird tatsächlich gekauft."
        )
        st.markdown(
            "**Deflated Sharpe Ratio:** Eine Zahl zwischen 0 und 1. Sie schätzt, wie wahrscheinlich der Vorsprung gegenüber dem ETF echt ist. "
            "Glück und die Zahl deiner ausprobierten Varianten werden dabei herausgerechnet. Erst ab 0,95 gilt das Ergebnis als belastbar."
        )
        st.markdown(
            "**Walk-forward-Test:** Hier prüft die Maschine, ob sie selbst eine bessere Mischung der Faktoren lernen kann. "
            "Das funktioniert wie beim Vokabellernen: Du übst mit alten Tests und wirst dann mit einem neuen Test geprüft, den du noch nie gesehen hast. "
            "Die Maschine lernt nur aus mindestens 36 vergangenen Monaten. Getestet wird mit einem Monat Abstand auf dem nächsten, noch unbekannten Monat. "
            "Schlägt die gelernte Mischung die gleiche Verteilung nicht, bleibt es bei der gleichen Verteilung."
        )

    with st.expander("9. Die Grenzen: wo sich die Maschine irren kann"):
        st.markdown(
            "- **Survivorship Bias, der wichtigste Punkt:** Stell dir vor, du willst wissen, wie gut eine Schule vor 20 Jahren war. Du fragst aber nur die Schüler, die heute ihr Abitur in der Hand haben. "
            "Wer sitzengeblieben ist oder die Schule verlassen hat, fehlt. So sieht alles besser aus, als es war. "
            "Genauso besteht das Universum aus den **heutigen** Indexmitgliedern. Firmen, die pleitegingen oder aus dem Index flogen, fehlen. Besonders Momentum sieht dadurch zu gut aus.\n"
            "- **Dividenden** werden auf beiden Seiten steuerfrei wieder angelegt. In echt würde darauf Steuer anfallen.\n"
            "- **Vorabpauschale** des ETF fehlt, das hilft dem ETF etwas.\n"
            "- **Bargeld** bringt keine Zinsen. In echt gäbe es Tagesgeldzinsen, das würde dem Trendfilter etwas helfen.\n"
            "- **Währung:** Alles in Dollar. Für einen Euro-Anleger kommt der Wechselkurs dazu.\n"
            "- **Vergangenheit ist nicht Zukunft.** Auch ein ehrlicher Test zeigt nur, was früher funktioniert hätte."
        )

    with st.expander("10. Brodel-Score auf dem Prüfstand"):
        st.markdown(
            "Jeden Tag speichert die App einen **Snapshot**, also ein Foto aller Brodel-Scores. Der Prüfstand schaut nach: "
            "Hatten Aktien mit hohem Score danach wirklich bessere Renditen als Aktien mit niedrigem Score?\n\n"
            "- **Horizont:** Nach wie vielen Handelstagen die Rendite gemessen wird. 5 Tage sind etwa eine Woche, 21 Tage ein Monat und 63 Tage ein Quartal.\n"
            "- **Snapshot-Tage:** Wie viele Tage mit gespeicherten Scores es gibt.\n"
            "- **Unabhängige Messpunkte:** Wie viele Messungen sich zeitlich nicht überschneiden.\n"
            "- **Mittlerer Rank-IC:** Wie gut der Score die Reihenfolge der späteren Renditen getroffen hat, wie in Abschnitt 8 erklärt."
        )
        st.markdown(
            "**Warum nur unabhängige Messpunkte zählen:** Misst du jeden Tag die Rendite des nächsten Monats, überlappen sich die Zeiträume fast vollständig. "
            "Das ist, als würdest du dasselbe Fußballspiel 20-mal anschauen und behaupten, du hättest 20 Spiele gesehen. "
            "Darum zählt der Prüfstand für den t-Wert nur Zeiträume ohne Überschneidung."
        )
        st.info("Für eine belastbare Aussage braucht es mindestens 24 unabhängige Messpunkte. Beim Monatshorizont sind das gut zwei Jahre tägliche Snapshots. Bis dahin ist jedes Ergebnis nur ein erster Hinweis.")

    with st.expander("11. Was das Ergebnis für dich bedeutet"):
        st.markdown(
            "- **Schlägt die Strategie den ETF nach Steuern nicht,** ist der ETF für den Großteil des Geldes die vernünftigere Wahl.\n"
            "- **Schlägt sie ihn, aber nicht belastbar,** kann es Glück gewesen sein. Dann lieber erst mit wenig Geld oder auf dem Papier weiter beobachten.\n"
            "- **Schlägt sie ihn belastbar,** solltest du trotzdem den Survivorship Bias bedenken und mit einem kleinen Teil des Geldes starten.\n\n"
            "Der erste Lauf mit den Standardeinstellungen auf dem S&P 500 ergab 7,5 % pro Jahr nach Steuern. Der ETF schaffte 10,0 %. "
            "Die Strategie hatte dafür nur etwa halb so große Abstürze."
        )
        st.caption("Die Wahrheitsmaschine ist ein Lern- und Prüfwerkzeug und keine Anlageberatung.")


def render_help_tab():
    st.subheader("Hilfe & Methodik")
    st.write("Der **Brodel-Score** (Skala: -30 bis 100) ist ein 'Frühwarn-Thermometer' dieses Systems. "
             "Er zählt Punkte aus 11 Bausteinen zusammen und wendet abschließend ein Makro-Overlay an. "
             "Die App rankt nach **Brodel 2.0**. Der alte **Brodel 1.0** läuft zum Vergleich mit und steht in der Tabelle ganz rechts.")

    st.markdown("### Schnellstart: der empfohlene Ablauf")
    st.markdown(
        "1. Öffne **Signal Monitor**. Dort steht die Rangliste aus dem letzten Tages-Snapshot. Die Snapshots werden jeden Tag automatisch erstellt.\n"
        "2. Bei Bedarf aktualisierst du die Signale in **Backtest & ML** über **⚙️ Datenpflege**. Dabei wird ebenfalls ein Tages-Snapshot gespeichert.\n"
        "3. Prüfe neben dem Gesamtscore immer die Einzelkomponenten, die fundamentale Verfassung, die Liquidität und den Sektor-Kontext.\n"
        "4. Prüfe in **Backtest & ML** mit der Wahrheitsmaschine und dem Brodel-Prüfstand, ob eine Strategie den ETF überhaupt schlägt. Ein hoher Score ist ein Recherche-Signal und keine Kaufentscheidung."
    )

    with st.expander("Die drei Tabs im Überblick"):
        st.markdown(
            "- **🔥 Signal Monitor:** aktuelle Frühwarnsignale, Detailanalyse und historischer Score-Verlauf.\n"
            "- **Backtest & ML:** Wahrheitsmaschine (Strategie gegen ETF nach Kosten und Steuern), Brodel-Score-Prüfstand, historische Simulation des Top-N-Portfolios, Training der Komponenten-Gewichte sowie manuelle Datenpflege.\n"
            "- **Hilfe & Methodik:** Definitionen der Signale, Datenquellen, Berechnungen und Grenzen."
        )

    with st.expander("Scores richtig interpretieren"):
        st.markdown(
            "Der Brodel-Score ist ein Ranking innerhalb des aktuellen Analysezeitpunkts. Er ist **keine Wahrscheinlichkeit**, dass eine Aktie steigt, und kein Kursziel. "
            "Vergleiche möglichst Aktien aus ähnlichen Branchen und Märkten. Ein Score sollte erst dann zu einer Handelsidee werden, wenn mindestens folgende Punkte zusammenpassen: Trend oder klarer Katalysator, ausreichende Liquidität, plausibles Chance-Risiko-Verhältnis und ein definierter Ausstieg."
        )
        st.warning("Ein fehlender Datenpunkt wird nicht automatisch zu einem positiven Signal. Prüfe in der Detailanalyse, ob ein Score durch echte Daten oder durch neutrale Standardwerte zustande kommt.")
    
    st.markdown("---")
    st.markdown("### Brodel 2.0: was ist neu und warum")
    with st.expander("Brodel 2.0 gegen Brodel 1.0", expanded=True):
        st.write(
            "Brodel 2.0 nutzt dieselben Daten wie 1.0, verteilt die Punkte aber anders. Grundlage ist die Auswertung der "
            "gespeicherten Snapshots und ein 20-Jahres-Test der Kursregeln (November 2026). Bausteine, die gute Aktien "
            "nach oben sortiert haben, bekommen mehr Punkte. Bausteine ohne Nutzen oder mit falscher Richtung bekommen weniger."
        )
        st.table(pd.DataFrame([
            {"Baustein": "Fundamentale Bewertung", "Max 1.0": "10", "Max 2.0": "15", "Grund": "in den Snapshots der stärkste Baustein"},
            {"Baustein": "EPS-Revisionen", "Max 1.0": "15", "Max 2.0": "15", "Grund": "neue Regel: Anteil der Hochstufungen statt Anzahl"},
            {"Baustein": "Kursziele & Konsens", "Max 1.0": "15", "Max 2.0": "5", "Grund": "hohe Kursziele liefen nach 3 Monaten schlechter"},
            {"Baustein": "Preis/Volumen", "Max 1.0": "10", "Max 2.0": "5", "Grund": "über 20 Jahre ohne Nutzen"},
            {"Baustein": "Technische Indikatoren", "Max 1.0": "10", "Max 2.0": "5", "Grund": "über 20 Jahre ohne Nutzen"},
            {"Baustein": "Aktienrückkauf (neu)", "Max 1.0": "–", "Max 2.0": "5", "Grund": "Firmen, die eigene Aktien zurückkaufen, liefen leicht besser"},
            {"Baustein": "News, Event, Insider, Short, Rel. Stärke", "Max 1.0": "unverändert", "Max 2.0": "unverändert", "Grund": "noch zu wenig Daten für eine Änderung"},
        ]))
        st.write(
            "Die Punkte von 1.0 werden dafür umgerechnet. Beispiel Kursziele: 1.0 vergibt bis zu 15 Punkte, 2.0 bis zu 5. "
            "Aus 10 Punkten in 1.0 werden also 10 × 5/15 ≈ 3 Punkte in 2.0."
        )
        st.warning(
            "Ehrlicher Hinweis: Die neuen Gewichte wurden an denselben, noch wenigen Snapshots ausgesucht, an denen sie auch gut aussehen. "
            "Ob 2.0 wirklich besser ist, zeigt erst die Zukunft. Deshalb läuft 1.0 weiter mit, und der Brodel-Prüfstand in "
            "**Backtest & ML** misst beide Versionen nebeneinander."
        )

    st.markdown("### Die 11 Bausteine")

    with st.expander("📊 EPS-Revisionen (1.0: max. 15 | 2.0: max. 15)"):
        st.write("**Was es misst:** Haben Analysten ihre Gewinnschätzungen (Gewinn je Aktie) zuletzt nach oben oder nach unten korrigiert?")
        st.markdown("- **Brodel 1.0:** Hochstufungen minus Herabstufungen. Ist das Ergebnis positiv, gibt es 6 Punkte plus 3 je Hochstufung Überhang (max. 15). Ist es negativ, gibt es bis zu −5 Punkte.")
        st.markdown("- **Brodel 2.0:** zählt den **Anteil** der Hochstufungen an allen Revisionen (mindestens 2 Revisionen): ab 80 % **+15**, ab 65 % **+10**, ab 50 % **+5**, höchstens 35 % **−5**.")
        st.write("**Warum die neue Regel:** Große Firmen haben viele Analysten und damit fast immer einen Überhang von 3 Hochstufungen. Unter 1.0 bekamen sie deshalb fast immer volle Punkte.")
        st.write("**Datenquelle:** Yahoo Finance (`yfinance`)")

    with st.expander("🎯 Kursziele & Konsens (1.0: max. 15 | 2.0: max. 5)"):
        st.write("**Was es misst:** Wie weit liegt das durchschnittliche Analysten-Kursziel über dem Kurs, und wie viele Analysten raten zum Kauf?")
        st.markdown("- Kursziel mindestens 20 % über dem Kurs: **+10**, mindestens 10 %: **+5**, darüber: **+2**.")
        st.markdown("- Bei mindestens 5 Analysten: Kaufempfehlungen ab 80 %: **+5**, ab 60 %: **+3**.")
        st.markdown("- **Brodel 2.0:** dieselben Regeln, aber nur ein Drittel der Punkte.")
        st.write("**Datenquelle:** Finnhub mit Fallback auf Yahoo Finance")
        st.warning("Analysten hinken dem Kurs oft hinterher. Fällt eine Aktie stark, sieht das Kurspotenzial plötzlich groß aus. In den Snapshots liefen Aktien mit hohem Kursziel-Potenzial nach 3 Monaten sogar schlechter.")

    with st.expander("📰 News-Sentiment (1.0: max. 15 | 2.0: max. 15)"):
        st.write("**Was es misst:** Wie viele Nachrichten gab es in den letzten 7 Tagen, und klingen sie gut oder schlecht?")
        st.markdown("- **Nachrichtendichte:** ab 2 Meldungen **+3**, ab 4 **+5**, ab 6 **+7**.")
        st.markdown("- **Stimmung:** Die Überschriften werden per KI (Gemini) oder Stichwortliste bewertet: **−8 bis +8**.")
        st.markdown("- Summe begrenzt auf −10 bis +15.")
        st.write("**Datenquelle:** Yahoo Finance (`yfinance`)")

    with st.expander("🏦 Fundamentale Bewertung (1.0: max. 10 | 2.0: max. 15)"):
        st.write("**Was es misst:** Ist die Firma solide und günstig bewertet?")
        st.markdown("- **KGV (Forward P/E):** unter 15 **+2**, unter 25 **+1**, über 50 **−2**.")
        st.markdown("- **PEG-Ratio:** unter 1,0 **+2**, unter 1,5 **+1**.")
        st.markdown("- **Verschuldung (Debt/Equity):** unter 50 % **+2**, unter 100 % **+1**.")
        st.markdown("- **Free-Cashflow-Rendite:** über 5 % **+2**, über 2 % **+1**.")
        st.markdown("- **Gewinnmarge:** über 20 % **+2**, über 10 % **+1**.")
        st.markdown("- **Brodel 2.0:** dieselben Regeln, Punkte mal 1,5.")
        st.write("**Datenquelle:** Alpha Vantage (30 Tage Cache) mit Fallback auf Yahoo Finance")

    with st.expander("🔁 Aktienrückkauf (nur 2.0: max. 5)"):
        st.write("**Was es misst:** Hat die Firma heute weniger Aktien als vor einem Jahr? Dann kauft sie eigene Aktien zurück. Jedem Aktionär gehört danach ein größeres Stück der Firma.")
        st.markdown("- Mindestens 3 % weniger Aktien: **+5**, mindestens 1 % weniger: **+3**.")
        st.markdown("- Mindestens 5 % mehr Aktien (Verwässerung durch neue Aktien): **−2**.")
        st.write("**Warum:** Im Test 2017 bis 2026 liefen die stärksten Rückkäufer gut 1,8 % pro Jahr besser als der Durchschnitt. Das ist ein kleiner Vorteil und statistisch noch nicht sicher, zeigte aber in die richtige Richtung.")
        st.write("**Datenquelle:** Yahoo Finance (Aktienanzahl-Historie)")

    with st.expander("🚀 Preis/Volumen (1.0: max. 10 | 2.0: max. 5)"):
        st.write("**Was es misst:** Läuft der Kurs im Aufwärtstrend, und fließt gerade viel Geld in die Aktie?")
        st.markdown("- Kurs über der 20-Tage-Linie: **+5**, über der 50-Tage-Linie: **+6**.")
        st.markdown("- In 5 Tagen mindestens 7 % gestiegen: **+4**, mindestens 7 % gefallen: **−3**.")
        st.markdown("- Steigender Tag mit mehr als dem 1,5-fachen Durchschnittsvolumen: **+3**.")
        st.markdown("- Summe begrenzt auf −10 bis +10. **Brodel 2.0:** halbe Punkte.")
        st.write("**Warum weniger in 2.0:** Über 20 Jahre nachgerechnet halfen diese Regeln nicht. Auf Wochensicht liefen Aktien über der 20-Tage-Linie sogar leicht schlechter.")
        st.write("**Datenquelle:** Yahoo Finance (`yfinance`)")

    with st.expander("📈 Technische Indikatoren (1.0: max. 10 | 2.0: max. 5)"):
        st.write("**Was es misst:** Ist die Aktie rechnerisch überkauft oder überverkauft?")
        st.markdown("- **RSI:** unter 30 (überverkauft) **+4**, über 70 (überkauft) **−4**.")
        st.markdown("- **MACD:** über der Signallinie **+3**, darunter **−1**.")
        st.markdown("- **Bollinger-Bänder:** Kurs unter dem unteren Band **+3**, über dem oberen Band **−3**.")
        st.markdown("- Summe begrenzt auf −8 bis +10. **Brodel 2.0:** halbe Punkte.")
        st.write("**Datenquelle:** Yahoo Finance (6 Monate Kurshistorie)")

    with st.expander("👔 Insider-Aktivität (1.0: max. 10 | 2.0: max. 10)"):
        st.write("**Was es misst:** Kaufen Vorstände und Direktoren mit eigenem Geld Aktien ihrer Firma?")
        st.markdown("- Insider-Stimmung der letzten 3 Monate: viele Käufe **+10**, mehrere **+6**, ein Kauf **+4**.")
        st.markdown("- Mehr als doppelt so viele Verkäufe wie Käufe: **−3** (nicht unter 0).")
        st.write("**Datenquelle:** Finnhub (Insider Sentiment aus SEC-Form-4-Meldungen) mit Fallback auf Yahoo Finance")
        st.info("Insider verkaufen aus vielen Gründen (Steuern, Hauskauf), aber sie kaufen meist nur aus einem: Sie glauben an steigende Kurse.")

    with st.expander("💪 Relative Stärke (1.0: max. 5 | 2.0: max. 5)"):
        st.write("**Was es misst:** Lief die Aktie im letzten Monat besser als ihr Heimatindex (z. B. S&P 500, DAX, Nikkei 225)?")
        st.markdown("- Mindestens 10 Prozentpunkte besser: **+5**, mindestens 5: **+3**, mindestens 2: **+1**.")
        st.write("**Datenquelle:** Yahoo Finance (`yfinance`)")

    with st.expander("📅 Event-Druck (1.0: max. 5 | 2.0: max. 5)"):
        st.write("**Was es misst:** Steht bald ein Termin an, zum Beispiel Quartalszahlen?")
        st.markdown("- Nächster Termin in höchstens 7 Tagen: **+5**, in höchstens 14 Tagen: **+3**, in höchstens 30 Tagen: **+1**.")
        st.write("**Datenquelle:** Yahoo Finance (`yfinance`)")

    with st.expander("🔥 Short Interest (1.0: max. 5 | 2.0: max. 5)"):
        st.write("**Was es misst:** Wetten viele Leerverkäufer auf fallende Kurse? Steigt der Kurs trotzdem, müssen sie teuer zurückkaufen (Short Squeeze).")
        st.markdown("- Nur wenn der Kurs über der 50-Tage-Linie liegt: Short-Anteil ab 20 % **+5**, ab 10 % **+3**, ab 5 % **+1**.")
        st.markdown("- Alternativ nach Tagen zum Eindecken: ab 5 Tagen **+4**, ab 3 Tagen **+2**.")
        st.markdown("- Unter der 50-Tage-Linie gibt es **0 Punkte**, denn dann haben die Leerverkäufer bisher recht.")
        st.write("**Datenquelle:** Yahoo Finance (`yfinance`)")

    st.markdown("---")
    st.markdown("### Das Makro-Overlay (Markt-Kontext)")
    st.write("Nachdem der Basis-Score berechnet wurde (Brodel 2.0 maximal 90 Punkte, Brodel 1.0 maximal 100 Punkte), wird die Großwetterlage geprüft. Das Overlay gilt für beide Versionen gleich:")

    st.markdown("- **Bullenmarkt-Bonus:** Steht der S&P 500 (SPY) über seiner 200-Tage-Linie, wird der Basis-Score um **10% angehoben (1.1x)**.")
    st.markdown("- **Bärenmarkt-Malus:** Steht der S&P 500 unter der 200-Tage-Linie, wird der Score um **20% gekürzt (0.8x)**.")
    st.markdown("- **Volatilitäts-Bremse:** Liegt der Angstindex (VIX) über 25 Punkten, wird der Score pauschal um **10% reduziert (0.9x)**.")
    st.markdown("- **Rezessions-Indikator (FRED):** Wenn die US-Zinsstrukturkurve invertiert ist (10Y Rendite minus 2Y Rendite < 0), wird der Score aus Risiko-Erwägungen um weitere **5% (0.95x)** reduziert.")
    st.info(
        "Alle Faktoren werden zu einem Gesamt-Multiplikator verrechnet. Positive Scores werden damit multipliziert, negative Scores dadurch geteilt. "
        "So wird ein schlechter Score in einem schwachen Markt schlechter und nicht besser. Beispiel: Bei 0,8x wird aus +20 ein +16 und aus −20 ein −25."
    )

    st.markdown("---")
    st.markdown("### Strategie-Setups")
    st.write("Die Strategien versuchen, aus dem Signalprofil konkrete, getrennte Handelsideen abzuleiten. Sie ersetzen nicht die Einzelprüfung der Aktie.")
    with st.expander("Momentum / Breakout"):
        st.write("Sucht Aktien mit Trend über MA20 und MA50, positiver kurzfristiger Bewegung, Volumenbestätigung, positiven Revisionen oder Konsensdaten und relativer Stärke. Das Setup ist trendfolgend und kann bei späten Einstiegen besonders anfällig für Rücksetzer sein.")
    with st.expander("Mean Reversion / Oversold Bounce"):
        st.write("Sucht überverkaufte Aktien mit niedrigem RSI, Nähe zum unteren Bollinger Band und starkem Rückgang. News und Short Interest sollen keinen eindeutig bearishen Zustand anzeigen. Das Setup ist antizyklisch und kann in einem echten Abwärtstrend weiter fallen.")
    with st.expander("Pre-Earnings"):
        st.write("Sucht Aktien mit bevorstehenden Quartalszahlen, intaktem Trend, positiver Gewinnrevision und ohne extremes Überkauft-Signal. Der Earnings-Termin ist ein Ereignisrisiko: Kurslücken können Stop-Loss-Ausführungen deutlich verschlechtern.")
    with st.expander("Short Squeeze"):
        st.write("Sucht hohe Short-Quote zusammen mit steigender Kursstärke und ungewöhnlichem Volumen. Eine hohe Short-Quote allein ist kein Kaufsignal; sie kann auch auf fundamentale Probleme oder anhaltenden Verkaufsdruck hindeuten.")

    st.markdown("### Backtesting: Was wird simuliert?")
    st.write(
        "Der Backtest nimmt die gespeicherten Signal-Snapshots und simuliert daraus ein Portfolio. Standardmäßig werden die Aktien mit den höchsten Brodel-Scores ausgewählt, "
        "die Positionen werden nach dem gewählten Intervall neu zusammengestellt und mit einer Benchmark verglichen. Die Simulation verwendet verfügbare Handelstage, führt ein Signal frühestens am nächsten Handelstag aus und prüft offene Stops und Take-Profits täglich."
    )
    st.markdown("**Einstellungen:**")
    st.markdown(
        "- **Startkapital:** rein rechnerischer Portfoliowert zum Start.\n"
        "- **Max. Positionen:** begrenzt die Anzahl gleichzeitig geöffneter Positionen.\n"
        "- **Rebalancing:** Abstand zwischen den Portfolio-Umschichtungen in Tagen.\n"
        "- **Benchmark:** Vergleichsindex, zum Beispiel SPY, QQQ, IWM oder DAX."
    )
    st.markdown("**Ausgaben:**")
    st.markdown(
        "- **Total Return:** Gesamtveränderung des simulierten Portfolios.\n"
        "- **CAGR:** annualisierte Rendite über die tatsächliche Zeitspanne.\n"
        "- **Sharpe Ratio:** Rendite im Verhältnis zur Schwankung; höhere Werte sind nicht automatisch belastbar.\n"
        "- **Max Drawdown:** größter Rückgang vom bisherigen Höchststand.\n"
        "- **Win Rate und Profit Factor:** Gewinnhäufigkeit und Verhältnis von Bruttogewinnen zu Bruttoverlusten.\n"
        "- **Alpha:** Differenz zwischen Portfolio- und Benchmark-Rendite.\n"
        "- **Equity-Kurve und Trades:** zeitlicher Verlauf und einzelne Ein-/Ausstiege."
    )
    st.info("Ein Backtest ist nur so gut wie seine Snapshots und Kursdaten. Er modelliert nicht automatisch jeden Spread, jede Marktgängigkeit oder jede Kurslücke. Besonders bei kleinen Aktien können echte Ausführungen deutlich schlechter sein.")

    with st.expander("Risikobasierte Positionsgröße"):
        st.write("Wenn ein Strategie-Signal einen Stop-Loss liefert, wird die Positionsgröße anhand des Stop-Abstands berechnet. Standardmäßig werden dabei ungefähr 0,75% des Startkapitals riskiert. Ein weiter Stop führt deshalb zu einer kleineren Position, ein enger Stop zu einer größeren Position.")
        st.code("Risiko je Trade = Startkapital * 0,0075\nAktienanzahl = Risiko je Trade / abs(Einstieg - Stop-Loss)")
        st.write("Das ist eine Risikobegrenzung, keine Garantie gegen Verluste. Bei Kurslücken kann der tatsächliche Verlust über dem geplanten Risiko liegen.")

    st.markdown("---")
    render_truth_machine_help()
    st.markdown("---")

    st.markdown("### ML-Gewichtung")
    st.write(
        "Mit **ML-Gewichtung trainieren** werden historische Snapshots mit der späteren 30-Tage-Forward-Rendite verbunden. Ein Ridge-Regressionsmodell schätzt, welche der zehn Komponenten im vorhandenen Datenbestand stärker oder schwächer gewichtet werden sollten. Negative Gewichte werden ausgeschlossen und die Gewichte anschließend zur besseren Lesbarkeit normiert."
    )
    st.markdown(
        "- Es werden mindestens fünf Snapshots für ein Training benötigt.\n"
        "- **Out-of-Sample-Schutz:** Die gelernten Gewichte werden nur angewendet, wenn sie auf einem zeitlich getrennten Testzeitraum besser sortieren als die einfache Gleichgewichtung. "
        "Dafür werden die ältesten 70 % der Snapshot-Tage zum Lernen genutzt, die jüngsten zum Prüfen, mit einem Abstand von 30 Tagen dazwischen. "
        "Diese Prüfung braucht mindestens 60 Snapshot-Tage. Bis ein Modell diese Prüfung bestanden hat, wird in der Haupttabelle kein ML-Score angezeigt.\n"
        "- Die Gewichte werden in `ml_weights/optimized_weights.json` gespeichert, zusammen mit dem Ergebnis der Prüfung.\n"
        "- Nach dem Training zeigt die App an, ob die Gewichte angewendet werden und warum."
    )

    st.markdown("### Datenquellen und Caching")
    st.markdown(
        "- **Yahoo Finance / yfinance:** Kurse, Volumen, technische Historie, News, Earnings-Termine, Basis-Fundamentaldaten und teilweise Insider-/Short-Daten.\n"
        "- **Finnhub:** Analysten-Kursziele, Empfehlungen und Insider-Sentiment, sofern `FINNHUB_API_KEY` eingerichtet ist. Cache-Dauer: typischerweise 24 Stunden.\n"
        "- **Alpha Vantage:** Fundamentaldaten, sofern `ALPHAVANTAGE_API_KEY` eingerichtet ist. Cache-Dauer: typischerweise 30 Tage; bei fehlendem Key oder Limit greift die App auf Yahoo Finance zurück.\n"
        "- **FRED:** US-Zinskurven-Spread `T10Y2Y` für den Makro-Overlay, sofern `FRED_API_KEY` eingerichtet ist.\n"
        "- **Google Gemini:** optionale semantische News-Auswertung, wenn die Google-GenAI-Abhängigkeit und ein gültiger Key verfügbar sind; sonst wird eine lokale Keyword-Auswertung verwendet.\n"
        "- **Wikipedia:** Indexzusammensetzungen für unterstützte Indizes."
    )
    st.caption("Lokale Caches sparen API-Aufrufe, können aber veraltete Daten enthalten. Prüfe das Alter der Daten, bevor du eine Entscheidung triffst.")

    st.warning(
        "Die App ist ein Research- und Priorisierungstool. Sie gibt keine Anlageberatung, führt keine Orders aus und kann Verluste nicht verhindern."
    )


TRUTH_UNIVERSES = ["S&P 500", "Nasdaq-100", "Dow Jones"]
TRUTH_BENCHMARKS = ["SPY", "QQQ", "URTH", "DIA"]


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and value == value


@st.cache_data(show_spinner=False, ttl=60 * 60 * 12)
def _truth_price_panel(universe: str, benchmark: str, start: str):
    symbols = load_universe(universe)
    return download_close_prices(symbols + [benchmark], start=start)


def build_truth_metrics_rows(report: dict) -> list[dict]:
    """Side-by-side comparison of strategy and benchmark for display."""
    m = report["backtest"]["metrics"]
    b = report["backtest"]["benchmark_metrics"]

    def pct(value):
        return f"{value * 100:.1f} %" if _is_number(value) else "–"

    def money(value):
        return f"{value:,.0f}".replace(",", ".") if _is_number(value) else "–"

    def ratio(value):
        return f"{value:.2f}" if _is_number(value) else "–"

    return [
        {"Kennzahl": "Rendite p. a. (Depotwert)", "Strategie": pct(m["cagr"]), "ETF": pct(b["cagr"])},
        {"Kennzahl": "Rendite p. a. nach Endverkauf und Steuer", "Strategie": pct(m["cagr_after_tax"]), "ETF": pct(b["cagr_after_tax"])},
        {"Kennzahl": "Volatilität p. a.", "Strategie": pct(m["volatility"]), "ETF": pct(b["volatility"])},
        {"Kennzahl": "Maximaler Verlust", "Strategie": pct(m["max_drawdown"]), "ETF": pct(b["max_drawdown"])},
        {"Kennzahl": "Sharpe Ratio", "Strategie": ratio(m["sharpe"]), "ETF": ratio(b["sharpe"])},
        {"Kennzahl": "Endvermögen nach Steuern", "Strategie": money(m["final_value_after_tax"]), "ETF": money(b["final_value_after_tax"])},
        {"Kennzahl": "Gezahlte Steuern", "Strategie": money(m["taxes_paid"]), "ETF": money(b["taxes_paid"])},
        {"Kennzahl": "Transaktionskosten", "Strategie": money(m["costs_paid"]), "ETF": "–"},
    ]


def build_factor_ic_rows(report: dict) -> list[dict]:
    rows = []
    for name, values in report["factor_ic"].items():
        rows.append({
            "Faktor": name,
            "Mittlerer Rank-IC": round(values["mean_ic"], 3) if _is_number(values["mean_ic"]) else None,
            "t-Wert": round(values["t_stat"], 2) if _is_number(values["t_stat"]) else None,
            "Trefferquote": f"{values['hit_rate'] * 100:.0f} %" if _is_number(values["hit_rate"]) else "–",
            "Monate": values["n"],
        })
    return rows


def render_truth_machine_section():
    st.subheader("🧪 Wahrheitsmaschine: Schlägt das System einen ETF?")
    st.write(
        "Testet kursbasierte Faktoren über bis zu 20 Jahre gegen einen ETF, mit Transaktionskosten, "
        "deutscher Abgeltungssteuer samt Verlusttopf und Sparerpauschbetrag sowie Trendfilter für die Investitionsquote. "
        "Signale entstehen zum Monatsende und werden erst am nächsten Handelstag ausgeführt."
    )
    st.caption("Eine ausführliche, einfache Erklärung aller Einstellungen und des ETF-Vergleichs steht im Reiter **Hilfe & Methodik** unter „Die Wahrheitsmaschine einfach erklärt“.")
    c1, c2, c3 = st.columns(3)
    with c1:
        universe = st.selectbox("Universum", TRUTH_UNIVERSES, index=0, key="truth_universe")
        benchmark = st.selectbox("Benchmark-ETF", TRUTH_BENCHMARKS, index=0, key="truth_benchmark")
    with c2:
        start_year = st.number_input("Startjahr", min_value=1995, max_value=2023, value=2005, step=1, key="truth_start")
        top_n = st.slider("Anzahl Aktien", min_value=5, max_value=100, value=20, key="truth_top_n")
    with c3:
        factors = st.multiselect(
            "Faktoren (gleich gewichtet)",
            options=list(FACTOR_DESCRIPTIONS),
            default=["momentum_12_1", "low_volatility"],
            help="\n".join(f"{k}: {v}" for k, v in FACTOR_DESCRIPTIONS.items()),
            key="truth_factors",
        )
        n_trials = st.number_input(
            "Bisher getestete Varianten",
            min_value=1, max_value=1000, value=1, step=1,
            help="Jede ausprobierte Einstellung erhöht die Chance auf einen Zufallstreffer. Diese Zahl fließt in die Deflated Sharpe Ratio ein.",
            key="truth_trials",
        )
    c4, c5, c6 = st.columns(3)
    with c4:
        trend_filter = st.checkbox("Trendfilter (ETF unter 200-Tage-Linie)", value=True, key="truth_trend")
    with c5:
        risk_off = st.slider("Investitionsquote im Abwärtstrend", 0.0, 1.0, 0.5, 0.1, disabled=not trend_filter, key="truth_risk_off")
    with c6:
        apply_tax = st.checkbox("Deutsche Steuer berücksichtigen", value=True, key="truth_tax")

    if st.button("Wahrheitsmaschine starten", use_container_width=True, disabled=not factors):
        with st.spinner("Lade Kurshistorie und rechne... (beim ersten Lauf 1–2 Minuten)"):
            try:
                close = _truth_price_panel(universe, benchmark, f"{int(start_year) - 1}-01-01").copy()
                if benchmark not in close.columns:
                    st.error(f"Benchmark {benchmark} konnte nicht geladen werden.")
                    return
                bench = close.pop(benchmark)
                config = BacktestConfig(
                    factor_weights={name: 1.0 for name in factors},
                    top_n=int(top_n),
                    trend_filter=trend_filter,
                    risk_off_exposure=float(risk_off),
                    apply_tax=apply_tax,
                    n_trials=int(n_trials),
                )
                st.session_state["truth_report"] = build_truth_report(close, bench, config)
            except Exception as exc:
                st.error(f"Wahrheitsmaschine fehlgeschlagen: {exc}")
                return

    report = st.session_state.get("truth_report")
    if not report:
        return
    st.markdown(f"**Zeitraum:** {report['period']['start']} bis {report['period']['end']} · **Universum:** {report['universe_size']} Titel")
    st.markdown("##### Urteil")
    for line in report["verdict"]:
        st.markdown(f"- {line}")
    st.dataframe(pd.DataFrame(build_truth_metrics_rows(report)), use_container_width=True, hide_index=True)
    equity = report["backtest_result"].equity[["strategy", "benchmark"]].rename(columns={"strategy": "Strategie", "benchmark": "ETF"})
    st.line_chart(equity)

    with st.expander("Statistik der Faktoren und Walk-forward-Test"):
        st.caption("Rank-IC: Rangkorrelation zwischen Score und Rendite des Folgemonats. Ab einem t-Wert von 2 gilt ein Effekt als signifikant.")
        st.dataframe(pd.DataFrame(build_factor_ic_rows(report)), use_container_width=True, hide_index=True)
        dsr = report["backtest"]["metrics"].get("deflated_sharpe_excess")
        if _is_number(dsr):
            st.write(f"Deflated Sharpe Ratio der Überrendite: **{dsr:.2f}** (ab 0,95 belastbar)")
        wf = report.get("walk_forward")
        if wf and _is_number(wf["summary_learned"]["mean_ic"]):
            st.write(
                f"Gelernte Gewichte, Rank-IC out of sample: {wf['summary_learned']['mean_ic']:+.3f} · "
                f"Gleichgewichtung: {wf['summary_equal']['mean_ic']:+.3f}"
            )
    with st.expander("Grenzen dieses Tests"):
        for caveat in report["caveats"]:
            st.markdown(f"- {caveat}")


BRODEL_CHECK_VERSIONS = [("Brodel 2.0", "brodel_score_v2"), ("Brodel 1.0", "brodel_score")]


def build_brodel_check_rows(results: dict[str, dict]) -> list[dict]:
    rows = []
    for label, _ in BRODEL_CHECK_VERSIONS:
        result = results[label]
        overall = result["summary"]
        independent = result["summary_independent"]
        rows.append({
            "Score": label,
            "Mittlerer Rank-IC": f"{overall['mean_ic']:+.3f}" if overall["n"] else "–",
            "Unabhängige Messpunkte": independent["n"],
            "t-Wert (unabhängig)": f"{independent['t_stat']:.1f}" if independent["n"] > 1 else "–",
        })
    return rows


def render_brodel_check_section():
    st.subheader("🔬 Brodel-Score auf dem Prüfstand")
    st.write(
        "Misst, ob ein hoher Brodel-Score in den gespeicherten Snapshots tatsächlich höhere Folgerenditen gebracht hat. "
        "Gemessen werden **Brodel 2.0** und zum Vergleich **Brodel 1.0** auf denselben Tagen. "
        "Überlappende Zeitfenster werden für den belastbaren t-Wert herausgerechnet."
    )
    st.caption(
        "Für ältere Snapshots wird Brodel 2.0 aus den gespeicherten Einzelpunkten nachgerechnet, ohne Rückkauf-Daten. "
        "Das Makro-Overlay ändert die Reihenfolge innerhalb eines Tages nicht und spielt für diese Messung keine Rolle."
    )
    horizon = st.select_slider("Horizont (Handelstage)", options=[5, 10, 21, 63], value=21, key="brodel_horizon")
    if st.button("Brodel-Score messen", use_container_width=True):
        with st.spinner("Lade Kurse für alle Snapshot-Titel..."):
            snapshots = load_snapshots()
            if not snapshots:
                st.info("Keine Snapshots vorhanden.")
                return
            snapshots = [(ts, [ensure_brodel_v2(dict(item)) for item in items]) for ts, items in snapshots]
            symbols = sorted({item.get("symbol") for _, items in snapshots for item in items if item.get("symbol")})
            first = min(ts for ts, _ in snapshots).strftime("%Y-%m-%d")
            close = download_close_prices(filter_single_currency(symbols, us_only=False), start=first)
            results = {
                label: snapshot_score_ic(snapshots, close, horizon_days=int(horizon), score_key=key)
                for label, key in BRODEL_CHECK_VERSIONS
            }
        main = results["Brodel 2.0"]
        independent = main["summary_independent"]
        c1, c2 = st.columns(2)
        c1.metric("Snapshot-Tage", main["n_snapshot_days"])
        c2.metric("Unabhängige Messpunkte", independent["n"])
        st.table(pd.DataFrame(build_brodel_check_rows(results)))
        if independent["n"] < 24:
            st.warning(
                f"Nur {independent['n']} unabhängige Messpunkte. Für eine belastbare Aussage braucht es mindestens 24, "
                "also gut zwei Jahre tägliche Snapshots bei einem Monatshorizont."
            )
        elif independent["t_stat"] >= 2:
            st.success(f"Brodel 2.0 sortiert signifikant (t = {independent['t_stat']:.1f}).")
        else:
            st.info(f"Kein signifikanter Effekt für Brodel 2.0 (t = {independent['t_stat']:.1f}).")


def render_backtest_tab():
    with st.expander("⚙️ Datenpflege: Signal-Snapshot manuell erstellen", expanded=False):
        st.write(
            "Berechnet die aktuellen Frühsignale für alle Aktien der Hintergrund-Watchlist (`watchlists/meine_watchlist.txt`) "
            "und speichert einen tagesaktuellen Snapshot für den Signal Monitor, Backtests und ML-Training."
        )
        if st.button("Signale jetzt neu berechnen & Snapshot speichern", use_container_width=True):
            execute_signal_calculation()
            st.rerun()

    render_truth_machine_section()
    st.markdown("---")
    render_brodel_check_section()
    st.markdown("---")

    st.subheader("Event-Backtest: Punktebereich-Eintritt")
    st.write(
        "Kauft alle Aktien genau an dem Tag, an dem sie in einen definierten Punktebereich eintreten, "
        "verteilt das Kapital gleichmäßig auf alle getätigten Käufe und ermittelt den heutigen Gesamtwert des Depots."
    )

    history_dir = Path("signal_history")
    available_files: list[str] = []
    if history_dir.exists():
        available_files = snapshot_store.list_sources(history_dir)

    col_src, col_mode = st.columns([1, 1])
    with col_src:
        source_options = ["Alle Snapshots zusammen"] + available_files
        chosen_source = st.selectbox("Snapshot-Datenbasis", options=source_options, index=0)
    with col_mode:
        entry_mode_label = st.selectbox(
            "Eintritts-Bedingung",
            options=[
                "Aufsteiger & Neueintritte (Standard: Aktie klettert in den Punktebereich)",
                "Nur Aufsteiger von unten (Vorheriger Score lag strikt unter Min-Punkte)",
                "Alle im Punktebereich (Jede Aktie mit Score im Bereich)",
            ],
            index=0,
            help="Definiert, wann ein Kauf ausgelöst wird, sobald eine Aktie den Punktebereich erreicht.",
        )
        if "Nur Aufsteiger" in entry_mode_label:
            entry_mode = "climbed_from_below"
        elif "Alle im Punktebereich" in entry_mode_label:
            entry_mode = "all_in_range"
        else:
            entry_mode = "fresh_entry"

    col_score, col_period, col_cap = st.columns([2, 1, 1])
    with col_score:
        score_range = st.slider(
            "Punktebereich (Brodel-Score)",
            min_value=0,
            max_value=100,
            value=(70, 80),
            step=1,
            help="Aktien, deren Score beim Eintritt in dieses Intervall fällt, werden gekauft.",
        )
        min_score, max_score = score_range
    with col_period:
        lookback_days = st.number_input(
            "Zeitraum (letzte X Tage)",
            min_value=0,
            max_value=1000,
            value=100,
            step=10,
            help="0 = gesamter gespeicherter Snapshot-Verlauf.",
        )
    with col_cap:
        initial_capital = st.number_input(
            "Startkapital (€)",
            min_value=500,
            max_value=10_000_000,
            value=10_000,
            step=1000,
            help="Wird gleichmäßig auf alle qualifizierten Käufe aufgeteilt.",
        )

    if st.button("🚀 Backtest starten", use_container_width=True, type="primary"):
        with st.spinner("Analysiere Snapshots, identifiziere Eintrittszeitpunkte und lade aktuelle Kurse..."):
            snapshots = []
            if chosen_source != "Alle Snapshots zusammen":
                try:
                    history = snapshot_store.load_history(history_dir, chosen_source)
                    snapshots = snapshots_with_datetimes(history, datetime.now())
                except Exception as e:
                    st.error(f"Fehler beim Laden von {chosen_source}: {e}")
            else:
                snapshots = load_snapshots(history_dir)

            result = run_score_range_backtest(
                snapshots=snapshots,
                min_score=float(min_score),
                max_score=float(max_score),
                lookback_days=int(lookback_days),
                initial_capital=float(initial_capital),
                entry_mode=entry_mode,
                one_trade_per_symbol=True,
            )

        if result.num_positions == 0:
            st.warning(
                f"Im gewählten Zeitraum (letzte {lookback_days} Tage) und Punktebereich ({min_score} - {max_score}) "
                "sind keine Aktien neu in den Bereich eingetreten. Tipp: Vergrößere den Zeitraum oder passe den Punktebereich an."
            )
        else:
            st.success(f"Backtest abgeschlossen: {result.num_positions} Aktien qualifiziert und simuliert gekauft!")

            # KPI Metrics
            m1, m2, m3, m4, m5 = st.columns(5)
            m1.metric("Startkapital", f"{result.initial_capital:,.2f} €")
            m2.metric("Depotwert heute", f"{result.total_current_value:,.2f} €")
            delta_str = f"{result.total_profit_loss:+,.2f} € ({result.total_return_pct:+.2f}%)"
            m3.metric("Gesamtrendite", f"{result.total_return_pct:+.2f}%", delta=delta_str)
            m4.metric("Gekaufte Aktien", f"{result.num_positions}")
            m5.metric("Trefferquote (Win-Rate)", f"{result.win_rate:.1f}%")

            trades_df = result.to_dataframe()
            if not trades_df.empty:
                st.markdown("### Detaillierte Liste der getätigten Käufe & heutiger Wert")
                st.dataframe(trades_df, use_container_width=True, hide_index=True)

                csv_data = trades_df.to_csv(index=False, sep=";").encode("utf-8")
                st.download_button(
                    label="📥 Ergebnis-Tabelle als CSV herunterladen",
                    data=csv_data,
                    file_name=f"backtest_score_{min_score}_{max_score}.csv",
                    mime="text/csv",
                )

    with st.expander("Erweiterte Tools (Klassischer Rebalancing-Backtest & ML-Training)"):
        st.write("Historischer Portfolio-Rebalancing-Backtest basierend auf festen monatlichen Intervallen.")
        r_col1, r_col2, r_col3 = st.columns(3)
        with r_col1:
            old_cash = st.number_input("Startkapital (Rebalance)", min_value=10000, max_value=10_000_000, value=100_000, step=10000)
        with r_col2:
            old_max_pos = st.slider("Max. Positionen", min_value=1, max_value=30, value=10)
        with r_col3:
            old_rebal_days = st.slider("Rebalancing (Tage)", min_value=7, max_value=90, value=30)
        old_benchmark = st.selectbox("Benchmark", options=["SPY", "DAX", "QQQ", "IWM"], index=0)

        if st.button("Klassischen Rebalancing-Backtest starten", use_container_width=True):
            with st.spinner("Lade historische Daten und simuliere Portfolio..."):
                old_result = run_backtest_on_snapshots(
                    initial_cash=float(old_cash),
                    max_positions=old_max_pos,
                    rebalance_days=old_rebal_days,
                    benchmark=old_benchmark,
                )
            st.code(old_result.summary())
            if not old_result.equity_curve.empty:
                st.line_chart(old_result.equity_curve[["total_value"]])
            if old_result.trades:
                st.dataframe(pd.DataFrame(old_result.trades), use_container_width=True, hide_index=True)

        st.markdown("---")
        st.subheader("ML-Gewichtung trainieren")
        st.write(
            "Trainiere die Score-Gewichtung auf Basis historischer Snapshots und Forward-Renditen. "
            "Die Gewichte werden nur angewendet, wenn sie auf einem zeitlich getrennten Testzeitraum "
            "die einfache Gleichgewichtung schlagen. Sonst bleibt es bei der Gleichgewichtung."
        )
        if st.button("ML-Gewichtung trainieren", use_container_width=True):
            with st.spinner("Trainiere Gewichte... (kann einige Minuten dauern)"):
                snapshots = load_snapshots()
                trainer = train_on_snapshots(snapshots, forward_days=30)
                if trainer.validated:
                    st.success("Gewichte bestehen den Out-of-Sample-Test und werden angewendet.")
                else:
                    reason = trainer.performance.get("oos_reason") or "Keine Trainingsdaten."
                    st.warning(f"Gewichte werden nicht angewendet: {reason}")
                st.json({
                    "validated": trainer.validated,
                    "weights": trainer.weights,
                    "performance": trainer.performance,
                    "trained_at": datetime.now(timezone.utc).isoformat(),
                })


def render_stock_agent():
    st.title("🔥 Brodel-Radar – Quantitative Marktbeobachtung")
    st.caption("Frühwarnsignale, Akkumulation & fundamentale Unternehmensanalysen")

    mapping_text = load_mapping_text()

    stock_tabs = st.tabs(["🔥 Signal Monitor", "Backtest & ML", "Hilfe & Methodik"])
    with stock_tabs[0]:
        render_watchlist_signal_monitor(mapping_text)
    with stock_tabs[1]:
        render_backtest_tab()
    with stock_tabs[2]:
        render_help_tab()


def main():
    render_stock_agent()


if __name__ == "__main__":
    main()

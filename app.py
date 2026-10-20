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
from backtest_engine.engine import load_snapshots


st.set_page_config(layout="wide")


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
            if not isinstance(item, dict):
                continue
            rows.append(
                {
                    "timestamp": timestamp,
                    "symbol": item.get("symbol"),
                    "name": item.get("name"),
                    "brodel_score": item.get("brodel_score", 0),
                }
            )

    if not rows:
        return pd.DataFrame(columns=["timestamp", "symbol", "name", "brodel_score"])

    frame = pd.DataFrame(rows)
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], errors="coerce")
    return frame.sort_values(["timestamp", "symbol"])


def render_watchlist_signal_monitor(mapping_text: str):
    st.subheader("Signal Monitor V2")
    st.write(
        "V2 priorisiert die Watchlist nach 9 Fruehsignalen: EPS-Revisionen, Kursziel-Potenzial & Konsens, "
        "News-Sentiment, Preis/Volumen-Verhalten, Event-Naehe, Insider-Aktivitaet, Short Interest, Relative Staerke und Fundamentaldaten."
    )

    if "watchlist_text" not in st.session_state or not st.session_state.get("watchlist_text", "").strip():
        default_name, default_text = load_default_watchlist_text()
        st.session_state.watchlist_text = default_text
        st.session_state.active_watchlist_name = default_name

    active_name = st.session_state.get("active_watchlist_name", DEFAULT_WATCHLIST_NAME)
    st.caption(f"Aktive Watchlist im Hintergrund: `{active_name}` (wird automatisch aus `watchlists/` verwaltet)")

    if st.button("Signale aktualisieren"):
        watchlist_content = st.session_state.get("watchlist_text", "").strip()
        if not watchlist_content:
            default_name, default_text = load_default_watchlist_text()
            watchlist_content = default_text.strip()
            st.session_state.watchlist_text = default_text
            st.session_state.active_watchlist_name = default_name

        if not watchlist_content:
            st.warning("Die Watchlist-Datei `watchlists/meine_watchlist.txt` ist leer oder nicht vorhanden.")
            return

        with st.spinner("Berechne V2-Fruehsignale..."):
            entries = parse_watchlist_text(st.session_state.watchlist_text)
            symbol_mappings = parse_symbol_mappings(mapping_text or "")
            
            if not entries:
                st.warning("Es wurden keine gueltigen Symbole gefunden.")
                return
                
            progress_bar = st.progress(0, text="Lade Signale...")
            live_table = st.empty()
            raw_results = []
            
            for i, entry in enumerate(entries):
                progress_bar.progress((i) / len(entries), text=f"Lade Signale für {entry} ({i}/{len(entries)})...")
                item = get_symbol_signal_monitor(entry, symbol_mappings)
                raw_results.append(item)
                
                # Show live updates without peer context yet
                temp_rows = []
                for tmp_item in raw_results:
                    temp_rows.append({
                        "Symbol": tmp_item["symbol"],
                        "Name": tmp_item["name"],
                        "Sektor": "Berechne...",
                        "Brodel-Score": tmp_item["brodel_score"],
                        "Vs. Sektor": 0,
                        "Sektor-Rang": "-",
                        "Top-Signal": tmp_item["signal_items"][0] if tmp_item["signal_items"] else "Keine Signale",
                    })
                live_table.dataframe(pd.DataFrame(temp_rows), use_container_width=True, hide_index=True)
            
            progress_bar.progress(1.0, text="Berechnung Peer-Kontext...")
            
            # Final calculation with peer context and strategy signals
            enriched_results = add_watchlist_peer_context(raw_results)
            strategy_results = build_strategy_signals(enriched_results)
            
            # Apply ML weights if available
            trainer = load_trained_weights()
            for item in strategy_results:
                item["ml_score"] = round(trainer.predict_score(item), 2)
            
            st.session_state.signal_monitor_items = sorted(
                strategy_results,
                key=lambda x: x.get("ml_score", x.get("brodel_score", 0)),
                reverse=True,
            )
            watchlist_name = st.session_state.get("active_watchlist_name", DEFAULT_WATCHLIST_NAME)
            st.session_state.signal_monitor_watchlist_name = watchlist_name
            # Automatisch als Tages-Snapshot abspeichern (idempotent)
            save_signal_snapshot(watchlist_name, st.session_state.signal_monitor_items)
            
            progress_bar.empty()
            live_table.empty()

    if "signal_monitor_items" not in st.session_state:
        current_watchlist = st.session_state.get("active_watchlist_name", DEFAULT_WATCHLIST_NAME)
        history = load_signal_snapshot_history(current_watchlist)
        if history:
            st.session_state.signal_monitor_items = history[-1].get("items", [])
            st.session_state.signal_monitor_watchlist_name = current_watchlist

    signal_items = st.session_state.get("signal_monitor_items", [])
    if not signal_items:
        st.info("Noch kein Signal Monitor vorhanden. Starte die Analyse mit 'Signale aktualisieren'.")
        return

    st.success(f"{len(signal_items)} Symbole mit V2-Signalprofil berechnet.")

    watchlist_name = st.session_state.get("signal_monitor_watchlist_name", st.session_state.get("active_watchlist_name", DEFAULT_WATCHLIST_NAME))
    history = load_signal_snapshot_history(watchlist_name)
    score_history = build_score_history_frame(history)

    st.caption(f"Snapshot-Historie: {len(history)} gespeicherte Tages-Snapshots für `{watchlist_name}`")

    st.markdown("**Strategie-Signale & Handlungsempfehlungen**")
    strategy_rows = []
    for item in signal_items:
        best = item.get("best_strategy")
        if best:
            strategy_rows.append(
                {
                    "Symbol": item["symbol"],
                    "Name": item["name"],
                    "Setup": best.get("setup", "-"),
                    "Strategie": best.get("strategy_name", "-"),
                    "Richtung": best.get("direction", "-"),
                    "Konfidenz": f"{best.get('confidence', 0):.0%}",
                    "Einstieg": best.get("entry_price"),
                    "Stop-Loss": best.get("stop_loss"),
                    "Take-Profit": best.get("take_profit"),
                    "Pos.-Grösse": f"{best.get('position_size_pct', 0):.1%}",
                    "Begründung": best.get("rationale", "")[:80] + "...",
                }
            )
    if strategy_rows:
        st.dataframe(pd.DataFrame(strategy_rows), use_container_width=True, hide_index=True)
    else:
        st.info("Keine klaren Strategie-Setups in der aktuellen Watchlist erkannt.")

    st.markdown("**Alle Signale in der Uebersicht (detailliert)**")
    table_rows = []
    for item in signal_items:
        peer_context = item.get("peer_context", {})
        breakdown = item.get("signal_breakdown", {})
        table_rows.append(
            {
                "Symbol": item["symbol"],
                "Name": item["name"],
                "Sektor": peer_context.get("sector", "Unbekannt"),
                "Brodel": item.get("brodel_score", 0),
                "ML-Score": item.get("ml_score", item.get("brodel_score", 0)),
                "EPS": breakdown.get("EPS-Revisionen", {}).get("score", 0),
                "Kursziel": breakdown.get("Kursziele & Konsens", {}).get("score", 0),
                "P/V": breakdown.get("Preis/Volumen", {}).get("score", 0),
                "News": breakdown.get("News-Sentiment", {}).get("score", 0),
                "Event": breakdown.get("Event-Druck", {}).get("score", 0),
                "Insider": breakdown.get("Insider-Aktivitaet", {}).get("score", 0),
                "Short": breakdown.get("Short Interest", {}).get("score", 0),
                "Rel.St.": breakdown.get("Relative Staerke", {}).get("score", 0),
                "Fundam.": breakdown.get("Fundamentale Bewertung", {}).get("score", 0),
                "Tech.": breakdown.get("Technische Indikatoren", {}).get("score", 0),
                "Vs. Sektor": peer_context.get("score_vs_sector", 0),
                "Rang": f"{peer_context.get('sector_rank', 1)}/{peer_context.get('sector_count', 1)}",
            }
        )

    st.dataframe(pd.DataFrame(table_rows), use_container_width=True, hide_index=True)

    st.markdown("---")
    st.subheader("🔍 Detail-Analyse")
    st.write("Waehle eine Aktie aus der Tabelle, um die genauen Fruehsignale und Peer-Vergleiche zu sehen.")
    
    options = [f"{item['symbol']} - {item['name']} (Score: {item['brodel_score']})" for item in signal_items]
    selected_option = st.selectbox("Aktie suchen", options=options, index=0 if options else None)
    
    if selected_option:
        selected_symbol = selected_option.split(" - ")[0]
        item = next((i for i in signal_items if i["symbol"] == selected_symbol), None)
        
        if item:
            st.markdown(f"### {item['symbol']} - {item['name']} | Brodel-Score: {item['brodel_score']}")
            if item["resolved"]:
                st.caption(f"Eingabe: {item['input_name']} | {item['resolution_note']}")

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

                    st.markdown("**Signal-Breakdown**")
                    max_scores = {
                        "EPS-Revisionen": 15, "Kursziele & Konsens": 15, "Preis/Volumen": 10,
                        "News-Sentiment": 15, "Event-Druck": 5, "Insider-Aktivitaet": 10,
                        "Short Interest": 5, "Relative Staerke": 5, "Fundamentale Bewertung": 10,
                        "Technische Indikatoren": 10,
                    }
                    breakdown_rows = []
                    for component in item.get("signal_breakdown", {}).values():
                        breakdown_rows.append({
                            "Komponente": component["name"],
                            "Punkte": component["score"],
                            "Maximal": max_scores.get(component["name"], 0),
                            "Detail": component["summary"],
                        })
                    st.dataframe(pd.DataFrame(breakdown_rows), use_container_width=True, hide_index=True)

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
                            chart_data = symbol_history.set_index("timestamp")[["brodel_score"]]
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
                op_cols = st.columns(4)
                ttm_op_margin = ext.get("operating_margin_ttm")
                oc_hist = ext.get("operating_cost_history", [])
                latest_opex = oc_hist[-1]["OpEx"] if oc_hist else None
                latest_fe = oc_hist[-1]["FE"] if oc_hist else None
                latest_sga = oc_hist[-1]["SGA"] if oc_hist else None
                latest_fe_quote = oc_hist[-1]["FE_Quote"] if oc_hist else None
                latest_sga_quote = oc_hist[-1]["SGA_Quote"] if oc_hist else None
                latest_year = oc_hist[-1]["Jahr"] if oc_hist else None

                op_cols[0].metric(
                    "Operative Marge (TTM)",
                    f"{ttm_op_margin:.1f} %" if ttm_op_margin is not None else "n/a",
                    help="Operative Marge (Operating Margin) der letzten 12 Monate"
                )

                if latest_opex is not None:
                    opex_str = f"{latest_opex / 1e9:.2f} Mrd. {curr_str}" if abs(latest_opex) >= 1e9 else f"{latest_opex / 1e6:.1f} Mio. {curr_str}"
                else:
                    opex_str = "n/a"
                op_cols[1].metric(
                    f"OpEx gesamt ({latest_year})" if latest_year else "Letzte OpEx gesamt",
                    opex_str,
                    help="Gesamte operative Betriebskosten (Operating Expenses) des letzten Geschäftsjahres"
                )

                if latest_fe is not None:
                    fe_str = f"{latest_fe / 1e9:.2f} Mrd. {curr_str}" if abs(latest_fe) >= 1e9 else f"{latest_fe / 1e6:.1f} Mio. {curr_str}"
                else:
                    fe_str = "n/a"
                op_cols[2].metric(
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
                op_cols[3].metric(
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
                        opex_f = f"{row['OpEx'] / 1e9:.2f} Mrd." if row['OpEx'] and abs(row['OpEx']) >= 1e9 else (f"{row['OpEx'] / 1e6:.1f} Mio." if row['OpEx'] else "-")
                        fe_f = f"{row['FE'] / 1e9:.2f} Mrd." if row['FE'] and abs(row['FE']) >= 1e9 else (f"{row['FE'] / 1e6:.1f} Mio." if row['FE'] else "-")
                        sga_f = f"{row['SGA'] / 1e9:.2f} Mrd." if row['SGA'] and abs(row['SGA']) >= 1e9 else (f"{row['SGA'] / 1e6:.1f} Mio." if row['SGA'] else "-")
                        
                        oc_display_rows.append({
                            "Jahr": str(row["Jahr"]),
                            f"Umsatz ({curr_str})": rev_f,
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
                k_cols = st.columns(3)
                curr_pe = ext.get("trailing_pe")
                fwd_pe = ext.get("forward_pe")
                peg = ext.get("peg_ratio")
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
                k_cols[2].metric(
                    "PEG-Verhaeltnis",
                    f"{peg:.2f}" if peg else "n/a",
                    help="Price/Earnings to Growth Ratio",
                )

                pe_trend = ext.get("pe_trend", [])
                if pe_trend:
                    st.caption("KGV-Trend der letzten Geschaeftsjahre (gepruefte Jahres-EPS und historische Jahresendkurse):")
                    pe_df = pd.DataFrame(pe_trend)
                    pe_c1, pe_c2 = st.columns([2, 1])
                    with pe_c1:
                        chart_pe = pe_df.dropna(subset=["KGV"]).set_index("Jahr")[["KGV"]]
                        if not chart_pe.empty:
                            st.line_chart(chart_pe)
                    with pe_c2:
                        st.dataframe(pe_df, use_container_width=True, hide_index=True)
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

def render_help_tab():
    st.subheader("Hilfe & Methodik")
    st.write("Der **Brodel-Score** (Skala: -30 bis 100) ist ein proprietäres 'Frühwarn-Thermometer' dieses Systems. "
             "Er aggregiert Signale aus 10 verschiedenen Finanzkategorien und wendet abschließend ein Makro-Overlay an. "
             "Das Ziel ist es, starke Aktien in schwachen Märkten, ausbrechende Momentum-Titel und Value-Chancen zu identifizieren.")

    st.markdown("### Schnellstart: der empfohlene Ablauf")
    st.markdown(
        "1. Konfiguriere deine Watchlist im Hintergrund über `watchlists/meine_watchlist.txt` (Symbole oder unterstützte Indexkürzel wie DAX, S&P 500, SOX, NBI, Nikkei 225).\n"
        "2. Öffne **Signal Monitor V2** und starte **Signale aktualisieren**. Die App lädt die verfügbaren Marktdaten, berechnet die Komponenten und ordnet die Watchlist nach Priorität.\n"
        "3. Beim Aktualisieren der Signale wird automatisch ein **Tages-Snapshot** gespeichert. Die so kontinuierlich aufgebaute Historie versorgt den Score-Verlauf, den Backtest und die Trainingsdaten für die ML-Gewichte.\n"
        "4. Prüfe neben dem Gesamtscore immer die Einzelkomponenten, das Setup, den Stop-Loss, die Liquidität und den Sektor-Kontext.\n"
        "5. Nutze **Backtest & ML** zunächst zur Prüfung und danach im Paper-Trading. Ein hoher Score ist ein Recherche-Signal und keine automatische Kaufentscheidung."
    )

    with st.expander("Die drei Tabs im Überblick"):
        st.markdown(
            "- **Signal Monitor V2:** aktuelle Frühwarnsignale, Strategie-Setups, ML-Score, Detailanalyse und historischer Score-Verlauf.\n"
            "- **Backtest & ML:** historische Simulation des Top-N-Portfolios, Equity-Kurve, Trade-Liste und Training der Komponenten-Gewichte.\n"
            "- **Hilfe & Methodik:** Definitionen der Signale, Datenquellen, Berechnungen, Grenzen und Bedienhinweise.\n\n"
            "*Hinweis: Die Watchlist-Verwaltung läuft headless im Hintergrund über `watchlists/meine_watchlist.txt`.*"
        )

    with st.expander("Scores richtig interpretieren"):
        st.markdown(
            "Der Brodel-Score ist ein Ranking innerhalb des aktuellen Analysezeitpunkts. Er ist **keine Wahrscheinlichkeit**, dass eine Aktie steigt, und kein Kursziel. "
            "Vergleiche möglichst Aktien aus ähnlichen Branchen und Märkten. Ein Score sollte erst dann zu einer Handelsidee werden, wenn mindestens folgende Punkte zusammenpassen: Trend oder klarer Katalysator, ausreichende Liquidität, plausibles Chance-Risiko-Verhältnis und ein definierter Ausstieg."
        )
        st.warning("Ein fehlender Datenpunkt wird nicht automatisch zu einem positiven Signal. Prüfe in der Detailanalyse, ob ein Score durch echte Daten oder durch neutrale Standardwerte zustande kommt.")
    
    st.markdown("---")
    st.markdown("### Die 10 Signalkomponenten")
    
    with st.expander("📊 EPS-Revisionen (Max. 15 Punkte)"):
        st.write("**Was es misst:** Haben Analysten ihre Gewinnerwartungen (Earnings per Share) in letzter Zeit nach oben oder unten korrigiert?")
        st.write("**Bewertungslogik:**")
        st.markdown("- **+3 Punkte** für jede netto-positive Revision (Upgrades minus Downgrades).")
        st.markdown("- **0 Punkte** bei negativen Netto-Revisionen.")
        st.write("**Datenquelle:** Yahoo Finance (`yfinance`)")
        st.info("💡 **Warum wichtig:** Steigende Gewinnerwartungen treiben historisch die Aktienkurse am stärksten. Ein 'Upward Earnings Revision' Trend ist ein starkes Kaufsignal.")

    with st.expander("🎯 Kursziel & Analystenkonsens (Max. 15 Punkte)"):
        st.write("**Was es misst:** Wo sehen professionelle Analysten den fairen Wert der Aktie in 12 Monaten?")
        st.write("**Bewertungslogik:**")
        st.markdown("- **+1 Punkt** für jede 2% Aufwärtspotenzial (Upside) zum durchschnittlichen Kursziel (max. 10 Punkte).")
        st.markdown("- **+5 Bonuspunkte**, wenn der Anteil der 'Buy' und 'Strong Buy' Ratings bei über 80% liegt.")
        st.write("**Datenquelle:** Finnhub (Echtzeit REST-API, 24h gecached)")
        st.warning("⚠️ **Blind Spot:** Analysten hinken dem Markt oft hinterher. Bei schnell fallenden Kursen wirkt das Upside oft künstlich hoch.")

    with st.expander("📰 News-Sentiment (Max. 15 Punkte)"):
        st.write("**Was es misst:** Wie ist die aktuelle Nachrichtenlage rund um das Unternehmen in den letzten 7 Tagen?")
        st.write("**Bewertungslogik:**")
        st.markdown("- Die Nachrichtenüberschriften werden per LLM (KI) semantisch analysiert.")
        st.markdown("- **+3 Punkte** für jede klar positive/bullishe Nachricht (z.B. neue Rekordumsätze, FDA-Zulassung).")
        st.markdown("- **-3 Punkte** für jede stark negative/bearishe Nachricht (z.B. Klagen, Produktionsausfälle).")
        st.write("**Datenquelle:** Yahoo Finance (`yfinance`)")

    with st.expander("📈 Technische Indikatoren (Max. 10 Punkte)"):
        st.write("**Was es misst:** Ist die Aktie rein mathematisch/technisch überkauft oder überverkauft?")
        st.write("**Bewertungslogik:**")
        st.markdown("- **RSI (Relative Strength Index):** Unter 30 (überverkauft) gibt **+4 Punkte**. Über 70 (überkauft) gibt **-4 Punkte**.")
        st.markdown("- **MACD:** Ein positiver Trend gibt **+3 Punkte**.")
        st.markdown("- **Bollinger Bänder:** Wenn der aktuelle Kurs unter dem unteren Bollinger Band liegt (Rückschlagspotenzial), gibt das **+3 Punkte**.")
        st.write("**Datenquelle:** Yahoo Finance (berechnet auf Basis der 1-Jahres-Historie)")

    with st.expander("🏦 Fundamentale Bewertung (Max. 10 Punkte)"):
        st.write("**Was es misst:** Ist die Aktie basierend auf harten Bilanzen günstig bewertet?")
        st.write("**Bewertungslogik:**")
        st.markdown("- **KGV (Forward P/E):** Unter 15 (+2 Punkte), unter 25 (+1 Punkt), über 50 (-2 Punkte Abzug).")
        st.markdown("- **PEG-Ratio (Wachstums-KGV):** Unter 1.0 (+2 Punkte), unter 1.5 (+1 Punkt).")
        st.markdown("- **Debt/Equity (Verschuldung):** Unter 50% (+2 Punkte), unter 100% (+1 Punkt).")
        st.markdown("- **Free Cashflow Yield:** Über 5% (+2 Punkte), über 2% (+1 Punkt).")
        st.markdown("- **Gewinnmarge:** Über 20% (+2 Punkte), über 10% (+1 Punkt).")
        st.write("**Datenquelle:** Alpha Vantage (Overview-Endpoint, 30 Tage Rolling-Cache) mit Fallback auf Yahoo Finance.")

    with st.expander("🚀 Preis- & Volumen-Momentum (Max. 10 Punkte)"):
        st.write("**Was es misst:** Fließt aktuell viel Kapital (Volumen) in die Aktie und stimmt der Trend?")
        st.write("**Bewertungslogik:**")
        st.markdown("- **Kurstrend:** Kurs über der 20-Tage-Linie (+3 Punkte), Kurs über der 50-Tage-Linie (+2 Punkte).")
        st.markdown("- **Volumenspitzen:** Letztes Volumen > 200% des Durchschnitts an einem 'Up-Day' (+3 Punkte).")
        st.markdown("- **Crash-Penaltie:** Fiel der Kurs in den letzten 5 Tagen um mehr als 10%, gibt das **-5 Punkte** Abzug.")
        st.write("**Datenquelle:** Yahoo Finance (`yfinance`)")

    with st.expander("👔 Insider-Aktivität (Max. 10 Punkte)"):
        st.write("**Was es misst:** Kauft das Management (CEOs, Direktoren) mit eigenem Geld Aktien des Unternehmens?")
        st.write("**Bewertungslogik:**")
        st.markdown("- Wir werten das 'Insider Sentiment' der letzten 3 Monate aus.")
        st.markdown("- **+4 bis +10 Punkte** gestaffelt nach Volumen und Anzahl der Käufe.")
        st.markdown("- Starker Überhang an Verkäufen führt zu Punktabzug (**-3 Punkte**).")
        st.write("**Datenquelle:** Finnhub (Insider Sentiment API) basierend auf echten SEC Form 4 Filings.")
        st.info("💡 **Warum wichtig:** Insider verkaufen aus vielen Gründen (Hauskauf, Steuern), aber sie kaufen nur aus einem Grund: Sie glauben, der Kurs wird steigen.")

    with st.expander("💪 Relative Stärke (Max. 5 Punkte)"):
        st.write("**Was es misst:** Schlägt die Aktie den allgemeinen Markt?")
        st.write("**Bewertungslogik:**")
        st.markdown("- Die Performance der letzten 20 Handelstage wird mit einem regionalen Benchmark-Index (z.B. DAX, S&P 500, SMI, Nikkei 225) verglichen.")
        st.markdown("- Übertrifft die Aktie den Benchmark, gibt das **+5 Punkte**.")
        st.write("**Datenquelle:** Yahoo Finance (`yfinance`)")

    with st.expander("📅 Event-Druck (Max. 5 Punkte)"):
        st.write("**Was es misst:** Stehen kurzfristige Katalysatoren (wie Quartalszahlen) an?")
        st.write("**Bewertungslogik:**")
        st.markdown("- Quartalszahlen in < 7 Tagen: **+5 Punkte**")
        st.markdown("- Quartalszahlen in < 14 Tagen: **+3 Punkte**")
        st.write("**Datenquelle:** Yahoo Finance (`yfinance`)")

    with st.expander("🔥 Short Interest (Max. 5 Punkte)"):
        st.write("**Was es misst:** Setzen viele Leerverkäufer (Shorter) auf fallende Kurse?")
        st.write("**Bewertungslogik:**")
        st.markdown("- Short Quote über 20%: **+5 Punkte** (Short-Squeeze Potenzial).")
        st.markdown("- Das Signal entfaltet seine volle positive Punktzahl besonders, wenn der Kurs gleichzeitig über der 50-Tage-Linie notiert (Shorter geraten unter Druck).")
        st.write("**Datenquelle:** Yahoo Finance (`yfinance`)")

    st.markdown("---")
    st.markdown("### Das Makro-Overlay (Markt-Kontext)")
    st.write("Nachdem der Basis-Score (Maximal 100 Punkte) berechnet wurde, wird die Großwetterlage geprüft:")

    st.markdown("- **Bullenmarkt-Bonus:** Steht der S&P 500 (SPY) über seiner 200-Tage-Linie, wird der Basis-Score um **10% angehoben (1.1x)**.")
    st.markdown("- **Bärenmarkt-Malus:** Steht der S&P 500 unter der 200-Tage-Linie, wird der Score um **20% gekürzt (0.8x)**.")
    st.markdown("- **Volatilitäts-Bremse:** Liegt der Angstindex (VIX) über 25 Punkten, wird der Score pauschal um **10% reduziert (0.9x)**.")
    st.markdown("- **Rezessions-Indikator (FRED):** Wenn die US-Zinsstrukturkurve invertiert ist (10Y Rendite minus 2Y Rendite < 0), wird der Score aus Risiko-Erwägungen um weitere **5% (0.95x)** reduziert.")

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

    st.markdown("### ML-Gewichtung")
    st.write(
        "Mit **ML-Gewichtung trainieren** werden historische Snapshots mit der späteren 30-Tage-Forward-Rendite verbunden. Ein Ridge-Regressionsmodell schätzt, welche der zehn Komponenten im vorhandenen Datenbestand stärker oder schwächer gewichtet werden sollten. Negative Gewichte werden ausgeschlossen und die Gewichte anschließend zur besseren Lesbarkeit normiert."
    )
    st.markdown(
        "- Es werden mindestens fünf Snapshots benötigt. Mehrere Monate mit regelmäßig gespeicherten Snapshots sind deutlich aussagekräftiger.\n"
        "- Die Gewichte werden in `ml_weights/optimized_weights.json` gespeichert.\n"
        "- Der Signal Monitor lädt vorhandene Gewichte und zeigt zusätzlich zum Brodel-Score einen ML-Score.\n"
        "- Die angezeigte Trainingskorrelation ist keine Garantie für zukünftige Rendite. Ohne getrennte Out-of-sample-Prüfung kann ein Modell überangepasst sein."
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

    st.markdown("### Empfohlener Einstiegsplan")
    st.write(
        "Die App ist erst dann wirklich nützlich, wenn genügend Historie vorhanden ist. Bis dahin ist jede Strategie nur eine Hypothese. "
        "Der folgende Plan ist bewusst defensiv gehalten. Er priorisiert das Sammeln von Beweisen vor dem Einsatz von Kapital."
    )
    with st.expander("Schritt 1: Automatische Datensammlung (ab sofort)"):
        st.markdown(
            "- Richte `daily_job.py` so ein, dass es täglich nach Börsenschluss läuft. Unter Windows geht das über die Aufgabenplanung, unter Linux über cron.\n"
            "- Sorge dafür, dass die Watchlists stabil bleiben. Häufiges Hinzufügen und Entfernen von Aktien verwässert die Historie.\n"
            "- Prüfe regelmäßig, ob Snapshots in `signal_history/` geschrieben werden und ob die Dateien gültiges JSON enthalten.\n"
            "- Mindestziel: 3 bis 6 Monate täglicher Snapshots, bevor du ernsthafte Rückschlüsse ziehst."
        )
    with st.expander("Schritt 2: Paper-Trading (Monat 1 bis 3)"):
        st.markdown(
            "- Notiere dir für jedes Signal, das du handeln würdest: Symbol, Einstiegskurs, Stop-Loss, Take-Profit, Positionsgröße und Begründung.\n"
            "- Führe diese Trades nur auf dem Papier oder in einem separaten Notizblatt durch, nicht mit echtem Geld.\n"
            "- Vergleiche am Ende jeder Woche die Ergebnisse mit dem Benchmark und mit deinen ursprünglichen Erwartungen.\n"
            "- Ziel ist nicht Gewinn, sondern zu lernen, wie oft Signale falsch liegen und wie groß typische Drawdowns sind."
        )
    with st.expander("Schritt 3: Backtest und ML-Validierung (Monat 3 bis 6)"):
        st.markdown(
            "- Nutze den Tab **Backtest & ML**, sobald mindestens 60 bis 90 Snapshots vorhanden sind.\n"
            "- Teile die Historie in Training und Out-of-sample auf. Trainiere Gewichte nur auf dem älteren Teil und prüfe die Performance auf dem neueren Teil.\n"
            "- Ein positives Ergebnis ist nur dann relevant, wenn es auf Daten entstanden ist, die während des Trainings noch nicht bekannt waren.\n"
            "- Wenn der Backtest im Out-of-sample-Bereich schlechter abschneidet als der Benchmark, ist die Strategie noch nicht bereit für echtes Geld."
        )
    with st.expander("Schritt 4: Erster Echtgeld-Einsatz (frühestens nach positiver Out-of-sample-Phase)"):
        st.markdown(
            "- Starte mit einem Betrag, dessen kompletter Verlust deine Lebensplanung nicht beeinträchtigt.\n"
            "- Halte dich strikt an die vorgeschlagene Positionsgröße und das Risiko pro Trade (maximal 0,5 bis 1 % des Kapitals).\n"
            "- Setze niemals das gesamte Vermögen in eine einzelne Aktie oder Strategie.\n"
            "- Führe ein Trading-Tagebuch: Warum wurde eingestiegen? Was ging anders als erwartet? Wurde der Stop eingehalten?\n"
            "- Behalte einen Kernbestand in breit gestreuten ETFs. Stock-Picking sollte ein Satellit bleiben, nicht das Fundament."
        )

    st.markdown("### Der menschliche Faktor")
    st.write(
        "Die beste Strategie nützt nichts, wenn sie nicht diszipliniert umgesetzt wird. Die App kann Signale liefern, aber sie kann nicht verhindern, "
        "dass du aus Angst verkaufst, aus Gier nachkaufst oder einen Verlusttrade emotional in einen größeren verwandelst."
    )
    with st.expander("Typische Verhaltensfallen"):
        st.markdown(
            "- **Nachkaufen in fallende Kurse:** Wenn der Stop erreicht ist, wird die Position geschlossen – nicht erhöht, um den Einstieg zu „verbilligen“.\n"
            "- **Zu große Positionen:** Ein einzelner Trade sollte das Depot nicht gefährden können.\n"
            "- **Bestätigungsfehler:** Nur Signale beachten, die die eigene Meinung bestätigen, und Warnsignale ignorieren.\n"
            "- **Überoptimierung:** Ständig Parameter ändern, weil der letzte Trade verloren hat. Das zerstört jede statistische Aussagekraft.\n"
            "- **FOMO:** In einen Trade einsteigen, weil er bereits stark gestiegen ist, statt auf das nächste klare Setup zu warten.\n"
            "- **Kein Plan:** Ein Trade ohne definierten Ausstieg ist kein Trade, sondern eine Wette."
        )
    with st.expander("Regeln, die helfen"):
        st.markdown(
            "- Setze vor jedem Trade Stop-Loss und Take-Profit fest und halte dich daran.\n"
            "- Riskiere pro Trade nur einen kleinen, festen Prozentsatz des Kapitals.\n"
            "- Wenn du drei Verlusttrades hintereinander hattest, mache eine Pause und prüfe die Strategie, statt das Risiko zu erhöhen.\n"
            "- Dokumentiere jeden Trade. Auswertung ist wichtiger als das Gefühl, richtig gelegen zu haben.\n"
            "- Akzeptiere Verluste als Teil des Systems. Ein einzelner Verlust bedeutet nicht, dass die Strategie falsch ist.\n"
            "- Lass dich nicht von einem einzigen großen Gewinner blenden. Langfristig zählt die Summe aller Trades."
        )

    st.markdown("### Grenzen und sicherer Arbeitsablauf")
    st.warning(
        "Die App ist ein Research- und Priorisierungstool. Sie gibt keine Anlageberatung, führt keine Orders aus und kann Verluste nicht verhindern. "
        "Verwende zunächst historische Out-of-sample-Tests und Paper-Trading. Setze nur Kapital ein, dessen Verlust du finanziell tragen kannst."
    )
    st.markdown(
        "Für eine belastbare Weiterentwicklung sollten Strategien getrennt nach Marktphase, Branche, Marktkapitalisierung und Liquidität ausgewertet werden. "
        "Ein gutes Ergebnis ist nicht nur eine hohe Rendite, sondern eine nachvollziehbare Rendite bei kontrolliertem Drawdown, realistischen Kosten und genügend Trades."
    )


def render_backtest_tab():
    st.subheader("Event-Backtest: Punktebereich-Eintritt")
    st.write(
        "Kauft alle Aktien genau an dem Tag, an dem sie in einen definierten Punktebereich eintreten, "
        "verteilt das Kapital gleichmäßig auf alle getätigten Käufe und ermittelt den heutigen Gesamtwert des Depots."
    )

    history_dir = Path("signal_history")
    available_files: list[str] = []
    if history_dir.exists():
        available_files = sorted([f.name for f in history_dir.glob("*.json")])

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
                target_file = history_dir / chosen_source
                if target_file.exists():
                    import json
                    try:
                        with open(target_file, "r", encoding="utf-8") as f:
                            raw_data = json.load(f)
                        mtime = target_file.stat().st_mtime
                        for s in raw_data:
                            if isinstance(s, dict) and "items" in s:
                                ts_raw = s.get("timestamp")
                                p_ts = pd.to_datetime(ts_raw, errors="coerce", utc=True)
                                dt = datetime.fromtimestamp(mtime) if pd.isna(p_ts) else p_ts.to_pydatetime().replace(tzinfo=None)
                                snapshots.append((dt, s["items"]))
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
            "Die optimierten Gewichte werden automatisch im Signal Monitor angewendet."
        )
        if st.button("ML-Gewichtung trainieren", use_container_width=True):
            with st.spinner("Trainiere Gewichte... (kann einige Minuten dauern)"):
                snapshots = load_snapshots()
                trainer = train_on_snapshots(snapshots, forward_days=30)
                st.json({
                    "weights": trainer.weights,
                    "performance": trainer.performance,
                    "trained_at": datetime.now(timezone.utc).isoformat(),
                })


def render_stock_agent():
    st.title("Aktien-Agent")
    st.caption("Watchlist-Monitor fuer Marktveraenderungen, Fruehsignale und priorisierte Beobachtung.")

    mapping_text = load_mapping_text()

    stock_tabs = st.tabs(["Signal Monitor V2", "Backtest & ML", "Hilfe & Methodik"])
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

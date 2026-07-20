import os

import pandas as pd
import streamlit as st

from stock_agent import (
    build_watchlist_alerts,
    build_signal_delta_report,
    build_symbol_signal_monitor,
    build_symbol_summary,
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


st.set_page_config(layout="wide")


DEFAULT_WATCHLIST_NAME = "meine_watchlist.txt"


@st.cache_data(show_spinner=False, ttl=3600, persist="disk")
def get_symbol_summary(entry: str, symbol_mappings: dict):
    return build_symbol_summary(entry, symbol_mappings)


@st.cache_data(show_spinner=False, ttl=3600, persist="disk")
def get_symbol_signal_monitor(entry: str, symbol_mappings: dict):
    return build_symbol_signal_monitor(entry, symbol_mappings)


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


def append_indices_to_watchlist():
    raw_text = st.session_state.get("index_input_text", "")
    if not raw_text.strip():
        return

    normalized_entries = [entry.strip() for entry in raw_text.replace(";", ",").split(",") if entry.strip()]
    if not normalized_entries:
        return

    current_text = st.session_state.get("watchlist_text", "").strip()
    appended_text = "\n".join(normalized_entries)
    st.session_state.watchlist_text = f"{current_text}\n{appended_text}".strip() + "\n"
    st.session_state.pending_index_input_clear = True


def render_watchlist_source_controls():
    if "watchlist_initialized" not in st.session_state:
        default_name, default_text = load_default_watchlist_text()
        st.session_state.watchlist_text = default_text
        st.session_state.active_watchlist_name = default_name
        st.session_state.selected_watchlist_name = default_name if default_text else ""
        st.session_state.watchlist_initialized = True

    if "watchlist_text" not in st.session_state:
        default_name, default_text = load_default_watchlist_text()
        st.session_state.watchlist_text = default_text
        st.session_state.active_watchlist_name = default_name
    if "active_watchlist_name" not in st.session_state:
        st.session_state.active_watchlist_name = DEFAULT_WATCHLIST_NAME
    if st.session_state.pop("pending_index_input_clear", False):
        st.session_state.index_input_text = ""
    pending_selected_watchlist = st.session_state.pop("pending_selected_watchlist_name", None)
    if pending_selected_watchlist is not None:
        st.session_state.selected_watchlist_name = pending_selected_watchlist

    watchlist_files = list_watchlist_files()
    supported_indices = get_supported_indices()
    current_selected_watchlist = st.session_state.get("selected_watchlist_name", DEFAULT_WATCHLIST_NAME)
    if current_selected_watchlist not in watchlist_files:
        st.session_state.selected_watchlist_name = ""
    selected_watchlist = st.selectbox(
        "Gespeicherte Watchlist",
        options=[""] + watchlist_files,
        format_func=lambda value: value if value else "Bitte waehlen",
        key="selected_watchlist_name",
    )
    uploaded_file = st.file_uploader("Textdatei mit Tickern", type=["txt"])

    st.caption("Unterstuetzte Indizes in der Watchlist: " + ", ".join(supported_indices))

    index_cols = st.columns([3, 1])
    with index_cols[0]:
        index_input = st.text_input(
            "Indexlisten zur Watchlist hinzufuegen",
            key="index_input_text",
            help="Mehrere Indexnamen per Komma oder in separaten Durchlaeufen eingeben, zum Beispiel: DAX, S&P 500",
        )
    with index_cols[1]:
        st.button("Indizes einfuegen", use_container_width=True, on_click=append_indices_to_watchlist)

    control_cols = st.columns(3)

    with control_cols[0]:
        if st.button("Gespeicherte Watchlist laden", use_container_width=True):
            if selected_watchlist:
                st.session_state.watchlist_text = load_watchlist_file(selected_watchlist)
                st.session_state.active_watchlist_name = selected_watchlist
            else:
                st.warning("Bitte zuerst eine gespeicherte Watchlist auswaehlen.")

    with control_cols[1]:
        if st.button("Hochgeladene Datei uebernehmen", use_container_width=True):
            if uploaded_file is not None:
                st.session_state.watchlist_text = uploaded_file.getvalue().decode("utf-8")
                st.session_state.active_watchlist_name = uploaded_file.name or "upload_watchlist.txt"
            else:
                st.warning("Bitte zuerst eine Textdatei hochladen.")

    save_name_default = selected_watchlist[:-4] if selected_watchlist.endswith(".txt") else "meine_watchlist"
    with control_cols[2]:
        save_name = st.text_input("Dateiname zum Speichern", value=save_name_default or "meine_watchlist")
        if st.button("Aktuelle Watchlist speichern", use_container_width=True):
            if st.session_state.watchlist_text.strip():
                saved_path = save_watchlist_file(save_name, st.session_state.watchlist_text)
                st.session_state.active_watchlist_name = saved_path.name
                st.session_state.pending_selected_watchlist_name = saved_path.name
                st.success(f"Watchlist gespeichert: {saved_path.as_posix()}")
            else:
                st.warning("Die Watchlist ist leer und wurde nicht gespeichert.")

    st.text_area(
        "Oder Watchlist direkt einfuegen",
        key="watchlist_text",
        help="Ein Symbol pro Zeile oder komma-separiert. Kommentare mit # sind erlaubt. Bekannte Indexnamen wie DAX erweitern sich automatisch auf ihre Mitglieder.",
        height=180,
    )

    index_summary = summarize_index_entries(st.session_state.get("watchlist_text", ""))
    if index_summary["supported"]:
        supported_lines = [
            f"{item['entry']} -> {item['index_name']} ({item['count']} Titel)"
            for item in index_summary["supported"]
        ]
        st.info("Erkannte Index-Erweiterungen: " + " | ".join(supported_lines))

    if index_summary["unsupported"]:
        unsupported_lines = [item["entry"] for item in index_summary["unsupported"]]
        st.warning(
            "Diese indexaehnlichen Eintraege werden aktuell nicht auf Mitglieder erweitert: "
            + ", ".join(unsupported_lines)
            + ". Unterstuetzt werden derzeit DAX, S&P 500 und Dow Jones."
        )


def render_watchlist_briefing(mapping_text: str):
    st.write(
        "Erstellt pro Symbol eine Zusammenfassung zu News, Insideraktivitaet, "
        "Analysten-Upgrades oder Downgrades und naechsten Terminen."
    )

    if st.button("Zusammenfassung erstellen", type="primary"):
        if not st.session_state.watchlist_text.strip():
            st.warning("Bitte eine Watchlist-Datei hochladen, laden oder mindestens ein Symbol eingeben.")
            return

        with st.spinner("Lade Marktdaten und erstelle Briefing..."):
            entries = parse_watchlist_text(st.session_state.watchlist_text)
            symbol_mappings = parse_symbol_mappings(mapping_text or "")
            
            if not entries:
                st.warning("Es wurden keine gueltigen Symbole gefunden.")
                return

            progress_bar = st.progress(0, text="Lade Daten...")
            summary_items = []
            
            for i, entry in enumerate(entries):
                progress_bar.progress((i) / len(entries), text=f"Lade Daten für {entry} ({i}/{len(entries)})...")
                item = get_symbol_summary(entry, symbol_mappings)
                summary_items.append(item)
            
            progress_bar.progress(1.0, text="Laden abgeschlossen.")

        st.success(f"{len(summary_items)} Symbole analysiert.")
        for item in summary_items:
            label = f"{item['symbol']} - {item['name']}"
            with st.expander(label, expanded=False):
                if item["resolved"]:
                    st.caption(f"Eingabe: {item['input_name']} | {item['resolution_note']}")
                st.write(item["summary"])

                st.markdown("**Insideraktivitaet**")
                st.write(item["insider_activity"]["headline"])
                insider_items = item["insider_activity"]["items"] or ["Keine Detailzeilen verfuegbar."]
                for detail in insider_items:
                    st.markdown(f"- {detail}")

                st.markdown("**Upgrades / Downgrades**")
                analyst_items = item["analyst_actions"]["items"]
                st.write(item["analyst_actions"]["headline"])
                if analyst_items:
                    for detail in analyst_items:
                        st.markdown(f"- {detail}")

                st.markdown("**Naechste Termine**")
                next_dates = item["next_dates"] or ["Keine Termine verfuegbar."]
                for detail in next_dates:
                    st.markdown(f"- {detail}")

                st.markdown("**News-Lage**")
                news_items = item["news"]
                if news_items:
                    for detail in news_items:
                        meta_parts = [part for part in (detail.get("date"), detail.get("publisher")) if part]
                        meta_text = " | ".join(meta_parts)
                        label = f"[{detail['title']}]({detail['url']})"
                        if meta_text:
                            st.markdown(f"- {meta_text} | {label}")
                        else:
                            st.markdown(f"- {label}")
                else:
                    st.markdown("- Keine aktuellen News gefunden.")


def render_watchlist_alerts(mapping_text: str):
    st.write("Filtert die Watchlist auf neue Analysten-Aenderungen, Insiderkaeufe und anstehende Termine.")
    lookahead_days = st.slider("Termine innerhalb der naechsten Tage", min_value=1, max_value=365, value=30)

    if st.button("Alerts erzeugen"):
        if not st.session_state.watchlist_text.strip():
            st.warning("Bitte eine Watchlist-Datei hochladen, laden oder mindestens ein Symbol eingeben.")
            return

        with st.spinner("Pruefe Watchlist auf Alerts..."):
            entries = parse_watchlist_text(st.session_state.watchlist_text)
            symbol_mappings = parse_symbol_mappings(mapping_text or "")
            
            if not entries:
                st.warning("Es wurden keine gueltigen Symbole gefunden.")
                return

            progress_bar = st.progress(0, text="Prüfe Alerts...")
            summary_items = []
            
            for i, entry in enumerate(entries):
                progress_bar.progress((i) / len(entries), text=f"Prüfe {entry} ({i}/{len(entries)})...")
                item = get_symbol_summary(entry, symbol_mappings)
                summary_items.append(item)
            
            progress_bar.progress(1.0, text="Prüfung abgeschlossen.")

            # Calculate alerts from summaries
            import datetime
            alert_items = []
            for item in summary_items:
                alert_parts = []
                if item["analyst_actions"]["items"]:
                    alert_parts.append(f"Analysten: {item['analyst_actions']['items'][0]}")
                if item["insider_activity"]["items"]:
                    alert_parts.append(f"Insider: {item['insider_activity']['items'][0]}")
                
                import re
                for next_date in item["next_dates"]:
                    match = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", next_date)
                    if match:
                        try:
                            date_value = datetime.datetime.strptime(match.group(1), "%Y-%m-%d")
                            if 0 <= (date_value.date() - datetime.datetime.utcnow().date()).days <= lookahead_days:
                                alert_parts.append(f"Termin: {next_date}")
                        except ValueError:
                            pass
                
                if alert_parts:
                    # Dedupe
                    deduped = []
                    seen = set()
                    for p in alert_parts:
                        if p not in seen:
                            seen.add(p)
                            deduped.append(p)
                    alert_items.append({
                        "symbol": item["symbol"],
                        "name": item["name"],
                        "input_name": item["input_name"],
                        "resolution_note": item["resolution_note"],
                        "items": deduped,
                    })

        if not alert_items:
            st.info("Aktuell wurden keine Alerts fuer diese Watchlist gefunden.")
            return

        st.success(f"{len(alert_items)} Symbole mit Alerts gefunden.")
        for item in alert_items:
            header = f"{item['symbol']} - {item['name']}"
            with st.expander(header, expanded=True):
                st.caption(f"Eingabe: {item['input_name']} | {item['resolution_note']}")
                for detail in item["items"]:
                    st.markdown(f"- {detail}")


def render_watchlist_signal_monitor(mapping_text: str):
    st.subheader("Signal Monitor V2")
    st.write(
        "V2 priorisiert die Watchlist nach 9 Fruehsignalen: EPS-Revisionen, Kursziel-Potenzial & Konsens, "
        "News-Sentiment, Preis/Volumen-Verhalten, Event-Naehe, Insider-Aktivitaet, Short Interest, Relative Staerke und Fundamentaldaten."
    )

    with st.expander("Hilfe und Lesart des Signal Monitor V2", expanded=False):
        st.markdown("Der **Brodel-Score** (0 bis 100) ist ein 'Fruehwarn-Thermometer'. Er setzt sich aus 9 Bausteinen zusammen:")
        st.markdown("- **EPS-Revisionen (max. 18 Punkte):** Passten Analysten ihre Gewinnerwartungen zuletzt nach oben oder unten an? Mehr positive Korrekturen geben mehr Punkte.")
        st.markdown("- **Kursziel & Konsens (max. 15 Punkte):** Vergleicht das mittlere Analystenkursziel mit dem aktuellen Kurs und bewertet die Konsens-Staerk (Anteil Buys).")
        st.markdown("- **Preis & Volumen Momentum (max. 15 Punkte):** Technische Lage. Gibt Punkte fuer Kurse ueber der 20- und 50-Tage-Linie, Volumenspitzen und bestraft Crashs.")
        st.markdown("- **News-Sentiment (max. 15 Punkte):** Analysiert nicht nur die Nachrichtenmenge, sondern auch die Stimmung per KI (Gemini). Positive Nachrichten geben Punkte, negative ziehen ab.")
        st.markdown("- **Event-Druck (max. 8 Punkte):** Stehen bald Quartalszahlen oder Dividenden an?")
        st.markdown("- **Insider-Aktivitaet (max. 10 Punkte):** Kaufen oder verkaufen Insider gerade? Cluster-Kaeufe durch Fuehrungskraefte sind eines der staerksten Fruehsignale.")
        st.markdown("- **Short Interest (max. 6 Punkte):** Interpretation abhaengig vom Kurstrend: ueber MA50 = Squeeze-Potenzial, darunter = baerischer Druck.")
        st.markdown("- **Relative Staerke (max. 8 Punkte):** Vergleicht die Monatsperformance der Aktie mit dem regionalen Benchmark (DAX, SMI, Nikkei etc.).")
        st.markdown("- **Fundamentale Bewertung (max. 12 Punkte):** Bewertung anhand von P/E, PEG, Debt/Equity und FCF Yield.")
        st.markdown("---")
        st.markdown("- **Delta-Alerts** zeigen konkret, bei welcher Aktie sich der Score seit dem letzten Scan veraendert hat.")
        st.markdown("- **Peer-Kontext** ordnet die Aktie innerhalb deines eigenen Sektors/deiner eigenen Watchlist ein.")
        st.markdown("- Die **Uebersichtstabelle** zeigt alle 8 Einzelkomponenten als separate Spalten, so dass sofort erkennbar ist, woher der Score kommt.")

    alert_threshold = st.slider("Harter Delta-Alert ab Score-Anstieg von", min_value=1, max_value=30, value=10)

    if st.button("Signale aktualisieren"):
        if not st.session_state.watchlist_text.strip():
            st.warning("Bitte eine Watchlist-Datei hochladen, laden oder mindestens ein Symbol eingeben.")
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
            
            # Final calculation with peer context
            enriched_results = add_watchlist_peer_context(raw_results)
            st.session_state.signal_monitor_items = sorted(enriched_results, key=lambda x: x.get("brodel_score", 0), reverse=True)
            st.session_state.signal_monitor_watchlist_name = st.session_state.get("active_watchlist_name", DEFAULT_WATCHLIST_NAME)
            
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

    if not signal_items:
            st.info("Fuer diese Watchlist konnten keine Signale berechnet werden.")
            return

    st.success(f"{len(signal_items)} Symbole mit V2-Signalprofil berechnet.")

    watchlist_name = st.session_state.get("signal_monitor_watchlist_name", st.session_state.get("active_watchlist_name", DEFAULT_WATCHLIST_NAME))
    history = load_signal_snapshot_history(watchlist_name)
    previous_snapshot = history[-1] if history else None
    delta_items = build_signal_delta_report(signal_items, previous_snapshot)
    score_history = build_score_history_frame(history)

    history_cols = st.columns(2)
    with history_cols[0]:
        if st.button("Snapshot speichern", use_container_width=True):
            snapshot_path = save_signal_snapshot(watchlist_name, signal_items)
            st.success(f"Snapshot gespeichert: {snapshot_path.as_posix()}")
    with history_cols[1]:
        st.caption(f"Snapshot-Historie: {len(history)} vorhandene Snapshots fuer {watchlist_name}")


    st.markdown("**Delta-Alerts seit letztem Snapshot**")
    if delta_items:
        real_deltas = [item for item in delta_items if item["change_type"] != "Neu"]
        new_stocks = [item for item in delta_items if item["change_type"] == "Neu"]
        hard_alerts = [item for item in real_deltas if item["score_delta"] >= alert_threshold]
        
        if hard_alerts:
            st.warning(f"🚨 {len(hard_alerts)} Aktien ueberschreiten den Alert-Schwellwert von +{alert_threshold} Punkten seit dem letzten Snapshot!")

        delta_rows = []
        for item in real_deltas:
            if item["score_delta"] != 0 or item["new_signals"]:
                delta_rows.append(
                    {
                        "Symbol": item["symbol"],
                        "Aenderung": item["change_type"],
                        "Score jetzt": item["current_score"],
                        "Score davor": item["previous_score"],
                        "Delta": item["score_delta"],
                        "Neue Signale": " | ".join(item["new_signals"]) if item["new_signals"] else "-",
                    }
                )
                
        if delta_rows:
            st.dataframe(pd.DataFrame(delta_rows), use_container_width=True, hide_index=True)
        else:
            st.info("Keine relevanten Score-Veraenderungen oder neue Signale bei bestehenden Aktien.")
            
        if new_stocks:
            st.caption(f"Info: {len(new_stocks)} Aktien wurden seit dem letzten Snapshot neu in die Watchlist aufgenommen.")
    else:
        st.info("Noch kein vorheriger Snapshot oder keine relevanten Veraenderungen seit dem letzten Snapshot.")

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
                "Score": item.get("brodel_score", 0),
                "EPS": breakdown.get("EPS-Revisionen", {}).get("score", 0),
                "Kursziel": breakdown.get("Kursziele & Konsens", {}).get("score", 0),
                "P/V": breakdown.get("Preis/Volumen", {}).get("score", 0),
                "News": breakdown.get("News-Sentiment", {}).get("score", 0),
                "Event": breakdown.get("Event-Druck", {}).get("score", 0),
                "Insider": breakdown.get("Insider-Aktivitaet", {}).get("score", 0),
                "Short": breakdown.get("Short Interest", {}).get("score", 0),
                "Rel.St.": breakdown.get("Relative Staerke", {}).get("score", 0),
                "Fundam.": breakdown.get("Fundamentale Bewertung", {}).get("score", 0),
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
                    "EPS-Revisionen": 18, "Kursziele & Konsens": 15, "Preis/Volumen": 15,
                    "News-Sentiment": 15, "Event-Druck": 8, "Insider-Aktivitaet": 10,
                    "Short Interest": 6, "Relative Staerke": 8, "Fundamentale Bewertung": 12,
                }
                breakdown_rows = []
                for component in item.get("signal_breakdown", {}).values():
                    breakdown_rows.append({
                        "Komponente": component["name"],
                        "Punkte": component["score"],
                        "Max": max_scores.get(component["name"], "?"),
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

def render_stock_agent():
    st.title("Aktien-Agent")
    st.caption("Watchlist-Monitor fuer Marktveraenderungen, Fruehsignale und priorisierte Beobachtung.")

    mapping_text = load_mapping_text()

    stock_tabs = st.tabs(["Watchlist Briefing", "Watchlist Alerts", "Signal Monitor V2", "Watchlist Verwaltung"])
    with stock_tabs[0]:
        render_watchlist_briefing(mapping_text)
    with stock_tabs[1]:
        render_watchlist_alerts(mapping_text)
    with stock_tabs[2]:
        render_watchlist_signal_monitor(mapping_text)
    with stock_tabs[3]:
        st.subheader("Watchlist-Quelle")
        st.write(
            "Hier kannst du gespeicherte Watchlists aus dem Projekt laden oder neue Watchlists als Datei speichern."
        )
        st.caption("Manuelle Namens-zu-Ticker-Zuordnungen werden aus stock_mappings.txt geladen.")
        render_watchlist_source_controls()

    st.divider()
    st.subheader("Hinweise")
    st.write(
        "Standardmaessig wird beim Start die Datei meine_watchlist.txt geladen, sofern sie im Ordner watchlists/ vorhanden ist. "
        "Snapshots fuer den Signal Monitor werden im Ordner signal_history/ gespeichert."
    )


def main():
    render_stock_agent()


if __name__ == "__main__":
    main()

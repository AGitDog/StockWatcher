from datetime import datetime, timezone
import os
import re
from pathlib import Path
from typing import Callable

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
import paper_bot
from brodel_v3 import BRODEL_V3_WEIGHTS, QUALITY_CHANGE_DAY, compute_brodel_v3
from factor_lab import BacktestConfig, build_truth_report, snapshot_score_ic
from factor_lab.data import download_close_prices, filter_single_currency, load_universe
from factor_lab.factors import FACTOR_DESCRIPTIONS
import streamlit.components.v1 as components


st.set_page_config(page_title="StockWatcher", page_icon="📈", layout="wide")


VISITOR_PREFS_DIR = Path(__file__).parent / "components" / "visitor_prefs"
try:
    _visitor_prefs_func = components.declare_component("visitor_prefs", path=str(VISITOR_PREFS_DIR))
except Exception:
    _visitor_prefs_func = None


def visitor_prefs(set_value: bool | None = None) -> dict | None:
    """Preference stored in this browser: {"skip_start": bool}. None until the browser answered."""
    if _visitor_prefs_func is None:
        return None
    try:
        return _visitor_prefs_func(set=set_value, key="visitor_prefs", default=None)
    except Exception:
        return None


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
    visible = [{k: v for k, v in row.items() if not k.startswith("_")} for row in rows]
    st.dataframe(pd.DataFrame(visible), use_container_width=True, hide_index=True)
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


HISTORY_COLUMNS = ["timestamp", "symbol", "name", "brodel_score_v3", "brodel_score_v2", "brodel_score"]


def build_score_history_frame(history: list[dict[str, object]]) -> pd.DataFrame:
    """One row per stock and data day. The Rang-Score is recomputed per day from the stored factors,
    so every day uses today's formula; days before the factors were stored have none."""
    rows: list[dict[str, object]] = []
    for snapshot in history:
        timestamp = snapshot.get("timestamp")
        items = snapshot.get("items", []) if isinstance(snapshot, dict) else []
        items = [item for item in items if isinstance(item, dict)]
        if any(isinstance(item.get("factors_v3"), dict) for item in items):
            items = compute_brodel_v3(items)
        for item in items:
            if not snapshot_store.is_fresh_measurement(item):
                continue  # failed fetch or carried over from an earlier day, no measurement
            rows.append(
                {
                    "timestamp": str(timestamp or "")[:10],  # the data day, not the time of the run
                    "symbol": item.get("symbol"),
                    "name": item.get("name"),
                    "brodel_score_v3": item.get("brodel_score_v3"),
                    "brodel_score_v2": primary_score(ensure_brodel_v2(dict(item))),
                    "brodel_score": item.get("brodel_score", 0),
                }
            )

    if not rows:
        return pd.DataFrame(columns=HISTORY_COLUMNS)

    frame = pd.DataFrame(rows, columns=HISTORY_COLUMNS)
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], errors="coerce")
    frame["brodel_score_v3"] = pd.to_numeric(frame["brodel_score_v3"], errors="coerce")
    return frame.sort_values(["timestamp", "symbol"]).reset_index(drop=True)


@st.cache_data(ttl=600, show_spinner=False)
def cached_score_history(watchlist_name: str, latest_stamp: str | None) -> pd.DataFrame:
    """Score history of a watchlist, rebuilt only when a new snapshot arrived."""
    return build_score_history_frame(load_signal_snapshot_history(watchlist_name))


def rescore_items(items: list[dict]) -> list[dict]:
    """Rang-Score and sector comparison with the current formula, also for days stored earlier."""
    items = [item for item in items if isinstance(item, dict)]
    return add_watchlist_peer_context(compute_brodel_v3(items))


V3_TABLE_COLUMNS = ["Qualitaet", "Momentum", "EPS-Revisionen", "Bewertung", "Aktienrueckkauf", "Insider"]


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


def score_order(item: dict) -> tuple:
    """Best first: Rang-Score, stocks without one at the end, ties and the rest by Punkte-Score."""
    score_v3 = item.get("brodel_score_v3")
    has_v3 = isinstance(score_v3, (int, float))
    return (0 if has_v3 else 1, -(score_v3 if has_v3 else 0), -primary_score(item))


def prepare_signal_items(items: list[dict]) -> list[dict]:
    """Make sure every item carries Punkte-Score and sort like the table (Rang-Score first)."""
    prepared = [ensure_brodel_v2(dict(item)) for item in items if isinstance(item, dict)]
    return sorted(prepared, key=score_order)


def score_label(item: dict) -> str:
    score_v3 = item.get("brodel_score_v3")
    rank_text = f"Rang-Score {score_v3:.1f}" if isinstance(score_v3, (int, float)) else "kein Rang-Score"
    return f"{rank_text} · Punkte-Score {primary_score(item)}"


PEER_REGION_LABELS = {"europe": "Europa", "america": "Amerika", "asia": "Asien"}


def peer_group_text(peer_context: dict) -> str:
    """Who a stock is compared with in 'Rang' and 'Vs. Sektor', in words."""
    sector = peer_context.get("sector", "Unbekannt")
    if peer_context.get("score_basis") == "points":
        return f"allen Aktien im Sektor {sector}, nach Punkte-Score"
    region = PEER_REGION_LABELS.get(peer_context.get("region"), peer_context.get("region") or "der Region")
    return f"Aktien aus {region} im Sektor {sector}, nach Rang-Score"


def build_signal_table_rows(signal_items: list[dict]) -> list[dict]:
    """Rows for the main table: Punkte-Score and its points. Keys starting with ``_`` only steer the display."""
    rows = []
    for item in signal_items:
        peer_context = item.get("peer_context", {})
        breakdown_v2 = item.get("signal_breakdown_v2", {})
        row = {
            "Symbol": item["symbol"],
            "Name": item["name"],
            "Sektor": peer_context.get("sector", "Unbekannt"),
            "Rang-Score": item.get("brodel_score_v3"),
            "Punkte-Score": primary_score(item),
        }
        breakdown_v3 = item.get("signal_breakdown_v3") or {}
        for name in V3_TABLE_COLUMNS:
            row[f"R:{name}"] = breakdown_v3.get(name)
        for label, component_name in V2_TABLE_COLUMNS:
            row[label] = breakdown_v2.get(component_name, {}).get("score", 0)
        if peer_context.get("score_basis") == "points" or item.get("brodel_score_v3") is None:
            # no Rang-Score: a points difference would mix two scales in one column
            row["Vs. Sektor"] = None
            row["Rang"] = None
            row["_rang_pos"] = None
        else:
            row["Vs. Sektor"] = peer_context.get("score_vs_sector", 0)
            row["Rang"] = f"{peer_context.get('sector_rank', 1)}/{peer_context.get('sector_count', 1)}"
            row["_rang_pos"] = peer_context.get("sector_rank", 1)
        if item.get("stale_from"):
            row["_status"] = "stale"
            row["_hint"] = f"Stand vom {item['stale_from']}, heutiger Abruf steht noch aus"
        elif not snapshot_store.item_has_price_data(item):
            row["_status"] = "missing"
            row["_hint"] = "Keine Kursdaten beim letzten Abruf, Score nicht aussagekräftig"
        rows.append(row)
    return rows


BRODEL_COMPONENT_LABELS = {
    "Relative Staerke": "Relative Stärke",
    "Insider-Aktivitaet": "Insider-Aktivität",
    BUYBACK_COMPONENT_NAME: "Aktienrückkauf",
}
BRODEL_V3_LABELS = {"Qualitaet": "Qualität", "Aktienrueckkauf": "Aktienrückkauf"}
BRODEL_SHARED_BLOCKS = {
    "EPS-Revisionen": "EPS-Revisionen",
    "Insider-Aktivitaet": "Insider",
    BUYBACK_COMPONENT_NAME: "Aktienrueckkauf",
}


def breakdown_table_height(row_count: int) -> int:
    """Pixel height that shows every row of st.dataframe without an inner scrollbar."""
    return 38 + 35 * max(row_count, 1)


def build_breakdown_rows(item: dict) -> list[dict]:
    """One table: components of the Punkte-Score plus the blocks that only the Rang-Score has."""
    breakdown_v1 = item.get("signal_breakdown", {}) or {}
    breakdown_v2 = item.get("signal_breakdown_v2", {}) or {}
    breakdown_v3 = item.get("signal_breakdown_v3", {}) or {}
    rows = []
    for name in BRODEL_V2_MAX_POINTS:
        component_v2 = breakdown_v2.get(name, {})
        component_v1 = breakdown_v1.get(name, {})
        rows.append({
            "Baustein": BRODEL_COMPONENT_LABELS.get(name, name),
            "Rang-Score": breakdown_v3.get(BRODEL_SHARED_BLOCKS.get(name)),
            "Punkte-Score": component_v2.get("score", 0),
            "Detail": _with_v3_note(clean_detail(component_v2.get("summary") or component_v1.get("summary", "")),
                                    BRODEL_SHARED_BLOCKS.get(name), breakdown_v3.get(BRODEL_SHARED_BLOCKS.get(name)),
                                    item.get("factors_v3") or {}),
        })
    details = v3_block_details(item.get("factors_v3") or {})
    for name in ("Qualitaet", "Bewertung", "Momentum"):
        rows.append({
            "Baustein": BRODEL_V3_LABELS.get(name, name),
            "Rang-Score": breakdown_v3.get(name),
            "Punkte-Score": None,
            "Detail": details[name],
        })

    def order(row: dict) -> tuple[float, float]:
        v3, v2 = row["Rang-Score"], row["Punkte-Score"]
        return (-v3 if v3 is not None else 1.0, -v2 if v2 is not None else 1000.0)

    return sorted(rows, key=order)


# Older snapshots carry the data source as a tag and German words without umlauts.
_SOURCE_TAG = re.compile(r"^\[(?:YF|YFinance|Finnhub|AV)\]\s*")
_UMLAUT_WORDS = {
    "Rueckkauf": "Rückkauf", "Verwaesserung": "Verwässerung", "fuer": "für", "verfuegbar": "verfügbar",
    "unauffaellig": "unauffällig", "Kaeufe": "Käufe", "Verkaeufe": "Verkäufe", "Insiderkaeufe": "Insiderkäufe",
    "Naechster": "Nächster", "ueber": "über", "Ueberkauft": "Überkauft", "Ueberverkauft": "Überverkauft",
    "Baerisch": "Bärisch", "baerisch": "bärisch", "baerischer": "bärischer", "erhoehtes": "erhöhtes",
    "Leerverkaufsaktivitaet": "Leerverkaufsaktivität", "Relative-Staerke-Berechnung": "Relative-Stärke-Berechnung",
}
_UMLAUT_PATTERN = re.compile(r"\b(" + "|".join(sorted(_UMLAUT_WORDS, key=len, reverse=True)) + r")\b")


def clean_detail(text: str) -> str:
    """Detail text without the data source and with proper umlauts."""
    text = _SOURCE_TAG.sub("", text or "")
    return _UMLAUT_PATTERN.sub(lambda match: _UMLAUT_WORDS[match.group(1)], text)


def _with_v3_note(detail: str, block: str | None, points: float | None, factors: dict | None = None) -> str:
    """Add how the Rang-Score reads a block that also exists in the Punkte-Score."""
    if block is None or points is None:
        return detail
    weight = BRODEL_V3_WEIGHTS[block]
    if block == "Insider":
        factors = factors or {}
        if factors.get("insider_buy_usd") is None:
            level = "keine Daten für dieses Land = neutral wie keine Käufe"
        else:
            level = {0.5: "keine Käufe = neutral", 0.75: "kleine Käufe", 1.0: "Käufe ab 100.000 $"}.get(round(points / weight, 2), "")
        note = f"Rang-Score {points:.1f} von {weight}: {level}, nur Käufe zählen, Verkäufe nicht"
    else:
        note = f"Rang-Score {points:.1f} von {weight}: besser als {points / weight * 100:.0f} % der Vergleichsaktien"
    return f"{detail} · {note}" if detail else note


def v3_weight_for_label(label: str) -> int | None:
    """Weight of the Rang-Score block shown in a breakdown row, by its visible label."""
    for name, weight in BRODEL_V3_WEIGHTS.items():
        shown = BRODEL_V3_LABELS.get(name, name)
        if label == shown:
            return weight
    for component, block in BRODEL_SHARED_BLOCKS.items():
        if label == BRODEL_COMPONENT_LABELS.get(component, component):
            return BRODEL_V3_WEIGHTS[block]
    return None


def v3_block_details(factors: dict) -> dict[str, str]:
    """Plain-language values behind the blocks that only the Rang-Score has."""
    def percent(value, signed=False):
        return "k. A." if value is None else f"{value * 100:{'+' if signed else ''}.1f} %"

    pe = factors.get("forward_pe")
    if "operating_margin" in factors:
        quality = (f"Operative Marge {percent(factors.get('operating_margin'))}, Gesamtkapitalrendite {percent(factors.get('return_on_assets'))}, "
                   f"Free Cashflow {percent(factors.get('fcf_to_debt'))} der Schulden")
    else:  # stored before QUALITY_CHANGE_DAY
        debt = factors.get("debt_equity")
        quality = (f"Marge {percent(factors.get('profit_margin'))}, Eigenkapitalrendite {percent(factors.get('return_on_equity'))}, "
                   f"Verschuldung {'k. A.' if debt is None else f'{debt:.0f} %'} des Eigenkapitals")
    return {
        "Qualitaet": quality,
        "Bewertung": f"KGV {'k. A.' if pe is None else f'{pe:.1f}'}, Free-Cashflow-Rendite {percent(factors.get('fcf_yield'))}",
        "Momentum": f"{percent(factors.get('momentum_12_1'), signed=True)} in 12 Monaten ohne den letzten Monat",
    }


def rank_score_explanation(item: dict) -> str | None:
    """The Rang-Score calculation of one stock in one sentence, with the numbers of the table."""
    score_v3 = item.get("brodel_score_v3")
    breakdown = item.get("signal_breakdown_v3") or {}
    if not isinstance(score_v3, (int, float)) or not breakdown:
        return None
    known = {name: value for name, value in breakdown.items() if value is not None}
    points = sum(known.values())
    possible = sum(BRODEL_V3_WEIGHTS[name] for name in known)
    missing = [BRODEL_V3_LABELS.get(name, name) for name, value in breakdown.items() if value is None]
    text = f"So entsteht der Rang-Score: {points:.1f} von {possible} möglichen Punkten"
    if missing:
        text += f" ({', '.join(missing)} ohne Daten, zählt nicht mit)"
    text += (f" → {points:.1f} ÷ {possible} × 100 = **{score_v3:.1f}**. Die Aktie ist damit im gewichteten Mittel "
             f"besser als etwa {score_v3:.0f} % der Vergleichsaktien aus ihrer Region; Qualität und Bewertung werden nur "
             "mit dem eigenen Sektor verglichen. Das ist eine Platzierung, keine Prognose.")
    return text


def _rank_points_style(row: pd.Series) -> list[str]:
    """Rang-Score points are a share of the weight: green upper third, red lower third, neutral between."""
    styles = []
    for column, value in row.items():
        weight = v3_weight_for_label(row.get("Baustein", "")) if column == "Rang-Score" else None
        if column != "Rang-Score" or pd.isna(value) or not weight:
            styles.append("")
            continue
        share = value / weight
        styles.append("color: #2e9e5b; font-weight: 600" if share >= 2 / 3 else "color: #d9534f; font-weight: 600" if share <= 1 / 3 else "")
    return styles


def style_breakdown(frame: pd.DataFrame):
    """Rang-Score column by share of its weight (it is never negative), the point columns by sign."""
    point_columns = [column for column in ("Punkte-Score",) if column in frame]
    styler = style_points(frame, point_columns)
    if "Rang-Score" in frame:
        styler = styler.apply(_rank_points_style, axis=1).format(
            lambda value: "–" if pd.isna(value) else f"{value:.1f}", subset=["Rang-Score"])
    return styler


def style_points(frame: pd.DataFrame, columns: list[str]):
    """Green for positive points, red for negative ones, faint for zero."""
    def color(value):
        if pd.isna(value):
            return ""
        if value > 0:
            return "color: #2e9e5b; font-weight: 600"
        if value < 0:
            return "color: #d9534f; font-weight: 600"
        return "color: #9aa3ad"
    def text(value):
        if pd.isna(value):
            return "–"
        return f"{value:+.1f}" if value != int(value) else f"{value:+.0f}"
    return frame.style.map(color, subset=columns).format(text, subset=columns)


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

        enriched_results = add_watchlist_peer_context(compute_brodel_v3(raw_results))
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
    st.subheader("📊 Marktbeobachtung")

    active_name = st.session_state.get("active_watchlist_name", DEFAULT_WATCHLIST_NAME)

    latest_history = load_signal_snapshot_history(active_name)
    latest_stamp = latest_history[-1].get("timestamp") if latest_history else None
    # Reload when a newer nightly snapshot arrived while the page stayed open
    if "signal_monitor_items" not in st.session_state or (
        latest_stamp and st.session_state.get("signal_monitor_timestamp") not in (None, latest_stamp)
    ):
        if latest_history:
            st.session_state.signal_monitor_items = rescore_items(latest_history[-1].get("items", []))
            st.session_state.signal_monitor_watchlist_name = active_name
            st.session_state.signal_monitor_timestamp = latest_stamp

    signal_items = prepare_signal_items(st.session_state.get("signal_monitor_items", []))
    if not signal_items:
        st.info("Noch kein Snapshot vorhanden. Starte die Berechnung auf der Seite 'Forschung' unter '⚙️ Datenpflege & Signal-Snapshot erstellen'.")
        return

    history = latest_history
    score_history = cached_score_history(active_name, latest_stamp)

    m_stat1, m_stat2, m_stat3 = st.columns(3)
    m_stat1.caption(f"Watchlist: `{active_name}`")
    m_stat2.caption(f"Analysierte Werte: **{len(signal_items)} Symbole**")
    m_stat3.caption(f"Datenstand: **{str(latest_stamp or '')[:10]}** · Historie: **{len(history)} Tage**")

    st.caption(
        "Sortiert nach dem **Rang-Score** (0 bis 100). Der **Punkte-Score** ist die ältere Methode mit festen Punkten. "
        "Rechts oben wählst du, wessen **Bausteine** die Spalten in der Mitte zeigen. "
        "**Vs. Sektor** und **Rang** vergleichen den Rang-Score mit Aktien aus derselben Region und demselben Sektor. "
        "Ein Klick auf eine Spaltenüberschrift sortiert neu, die Maus auf der Überschrift zeigt Erklärung und Maximum. "
        "Blasse Zeilen: ⏱ Wert vom Vortag, ⚠ keine Kursdaten beim letzten Abruf."
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

    options = [f"{item['symbol']} - {item['name']} ({score_label(item)})" for item in signal_items]
    selected_option = st.selectbox("Aktie suchen", options=options, index=selected_row_idx if options else None)

    if selected_option:
        selected_symbol = selected_option.split(" - ")[0]
        st.session_state["active_selected_symbol"] = selected_symbol
        item = next((i for i in signal_items if i["symbol"] == selected_symbol), None)

        if item:
            head_col1, head_col2 = st.columns([3, 1])
            with head_col1:
                st.markdown(f"### {item['symbol']} · {item['name']}")
                if item.get("stale_from"):
                    st.caption(f"Stand vom {item['stale_from']}: Der heutige Abruf für diese Aktie steht noch aus oder ist fehlgeschlagen.")
                elif not snapshot_store.item_has_price_data(item):
                    st.caption("Für diese Aktie kamen beim letzten Abruf keine Kursdaten. Der Score ist daher nicht aussagekräftig.")
                if item.get("brodel_v2_estimated"):
                    st.caption("Punkte-Score aus einem älteren Snapshot nachgerechnet (ohne Rückkauf-Daten).")
                if item["resolved"]:
                    st.caption(f"Eingabe: {item['input_name']} | {item['resolution_note']}")
            with head_col2:
                if st.button(f"🔄 Daten für {item['symbol']} neu laden", key=f"btn_refresh_{item['symbol']}"):
                    get_extended_fundamentals.clear(item["symbol"])
                    st.rerun()

            # Extended Fundamentals & Profile
            with st.spinner("Lade Unternehmenszahlen & Profil..."):
                ext = get_extended_fundamentals(item["symbol"])

            peer_context = item.get("peer_context", {})
            score_v3 = item.get("brodel_score_v3")
            kpi_cols = st.columns(4)
            kpi_cols[0].metric("Rang-Score", f"{score_v3:.1f}" if score_v3 is not None else "–",
                               help="0 bis 100: im gewichteten Mittel der 6 Bausteine besser als so viel Prozent der Vergleichsaktien")
            kpi_cols[1].metric("Punkte-Score", primary_score(item), help="Summe fester Punkte aus 11 Signalen, höchstens 90")
            peer_group = peer_group_text(peer_context)
            kpi_cols[2].metric("Rang im Sektor", f"{peer_context.get('sector_rank', 1)} von {peer_context.get('sector_count', 1)}", help=f"Platz unter {peer_group}")
            kpi_cols[3].metric("Abstand zum Sektor", f"{peer_context.get('score_vs_sector', 0):+.1f}", help=f"Abstand zum Durchschnitt ({peer_context.get('sector_average', 0)}) der {peer_group}")
            top_peer = peer_context.get("top_peer")
            peer_score_name = "Punkte-Score" if peer_context.get("score_basis") == "points" else "Rang-Score"
            peer_text = f" · Stärkster Peer: {top_peer['symbol']} ({peer_score_name} {top_peer['score']})" if top_peer else ""
            st.caption(f"{peer_context.get('sector', 'Unbekannt')} · {peer_context.get('industry', 'Unbekannt')}{peer_text}")

            detail_tab_signals, detail_tab_fundamentals = st.tabs(["🧮 Score-Berechnung", "🏢 Unternehmenswerte"])

            with detail_tab_signals:
                st.markdown("**Bausteine**")
                if score_v3 is None:
                    st.caption("Für diese Aktie gibt es noch keinen Rang-Score: Ihr nächster Lauf steht aus oder es fehlen Daten. ETFs und Indizes bekommen keinen Wert.")
                breakdown_frame = pd.DataFrame(build_breakdown_rows(item))
                st.dataframe(
                    style_breakdown(breakdown_frame),
                    use_container_width=True,
                    hide_index=True,
                    height=breakdown_table_height(len(breakdown_frame)),
                    column_config={
                        "Baustein": st.column_config.TextColumn("Baustein", width="medium"),
                        "Rang-Score": st.column_config.Column("Rang-Score", width="small", help="Punkte dieses Bausteins im Rang-Score: Gewicht × Anteil der Vergleichsaktien, die schlechter sind. Grün oberes, rot unteres Drittel, ohne Farbe Mitte. Insider: keine Käufe oder keine Daten = 5 von 10 (neutral)"),
                        "Punkte-Score": st.column_config.Column("Punkte-Score", width="small", help="Feste Punkte im Punkte-Score. – = Baustein gibt es nur im Rang-Score"),
                        "Detail": st.column_config.TextColumn("Detail", width="large"),
                    },
                )

                explanation = rank_score_explanation(item)
                if explanation:
                    st.caption(explanation)
                if (item.get("factors_v3") or {}).get("insider_source") == "Tracefour":
                    st.caption("Insider-Daten: [Tracefour](https://tracefour.com/de), CC BY 4.0")
                if item.get("next_earnings"):
                    st.caption(f"Nächste Quartalszahlen: {item['next_earnings']}")

                st.markdown("**Score-Verlauf (letzte 100 Tage)**")
                if not score_history.empty:
                    symbol_history = score_history[score_history["symbol"] == selected_symbol].copy()
                    if not symbol_history.empty:
                        last_100_days = pd.Timestamp.utcnow().tz_localize(None).normalize() - pd.Timedelta(days=100)
                        symbol_history = symbol_history[symbol_history["timestamp"] >= last_100_days]
                        symbol_history = symbol_history.sort_values("timestamp")

                        if len(symbol_history) > 1:
                            chart_data = symbol_history.set_index("timestamp")[["brodel_score_v3", "brodel_score_v2"]].rename(
                                columns={"brodel_score_v3": "Rang-Score", "brodel_score_v2": "Punkte-Score"}
                            )
                            chart_data.index.name = "Datenstand"
                            st.line_chart(chart_data)
                            rank_days = int(chart_data["Rang-Score"].notna().sum())
                            st.caption(
                                f"Ein Punkt je Handelstag mit frischen Kursdaten. Den Rang-Score gibt es erst für {rank_days} "
                                f"{'Tag' if rank_days == 1 else 'Tage'}, weil seine Kennzahlen erst seit dem 06.11.2026 gespeichert werden. "
                                f"Seit dem {QUALITY_CHANGE_DAY[8:]}.{QUALITY_CHANGE_DAY[5:7]}.{QUALITY_CHANGE_DAY[:4]} misst der Baustein Qualität andere Kennzahlen (siehe Hilfe), "
                                "Werte davor sind damit nur bedingt vergleichbar."
                            )
                        else:
                            st.info("Nicht genuegend Historien-Daten fuer ein Diagramm (mindestens 2 Snapshots benoetigt).")
                    else:
                        st.info("Noch keine Verlaufsdaten fuer diese Aktie vorhanden.")
                else:
                    st.info("Noch keine Verlaufsdaten vorhanden.")

            with detail_tab_fundamentals:
                render_company_values(ext)


def _de_number(value, digits: int = 2) -> str:
    """German number format: 1.234,56."""
    text = f"{value:,.{digits}f}"
    return text.replace(",", "X").replace(".", ",").replace("X", ".")


def fmt_amount(value, unit: str = "") -> str:
    """Large amounts as Mrd./Mio., a dash when missing."""
    if value is None or value != value:
        return "–"
    suffix = f" {unit}" if unit else ""
    if abs(value) >= 1e9:
        return f"{_de_number(value / 1e9)} Mrd.{suffix}"
    if abs(value) >= 1e6:
        return f"{_de_number(value / 1e6, 1)} Mio.{suffix}"
    return f"{_de_number(value, 0)}{suffix}"


def fmt_pct(value, digits: int = 1, signed: bool = False) -> str:
    if value is None or value != value:
        return "–"
    text = _de_number(value, digits)
    return f"+{text} %" if signed and value > 0 else f"{text} %"


def fmt_plain(value, digits: int = 2, unit: str = "") -> str:
    if value is None or value != value:
        return "–"
    return f"{_de_number(value, digits)} {unit}".strip()


def _by_year_table(rows: list[dict], lines: list[tuple[str, Callable[[dict], str]]]) -> pd.DataFrame | None:
    """Years as columns, one line per figure, like an annual report. Lines without any value are left out."""
    if not rows:
        return None
    rows = sorted(rows, key=lambda row: row["Jahr"])
    table = []
    for label, cell in lines:
        values = {str(row["Jahr"]): cell(row) for row in rows}
        if any(value != "–" for value in values.values()):
            table.append({"Kennzahl": label, **values})
    return pd.DataFrame(table) if table else None


def build_company_profile_line(ext: dict) -> str:
    employees = ext.get("employees")
    parts = [
        ("Sektor", ext.get("sector_de")),
        ("Branche", ext.get("industry_de")),
        ("Sitz", ", ".join(str(part) for part in (ext.get("city"), ext.get("country")) if part)),
        ("Mitarbeiter", _de_number(employees, 0) if employees else None),
    ]
    return " · ".join(f"**{label}:** {value}" for label, value in parts if value and value != "-")


def build_valuation_rows(ext: dict) -> list[dict]:
    currency = ext.get("currency", "EUR")
    cap_currency = ext.get("main_currency") or currency
    return [
        {"Kennzahl": "Aktueller Kurs", "Wert": fmt_plain(ext.get("current_price"), 2, currency), "Bedeutung": ""},
        {"Kennzahl": "Kursziel der Analysten", "Wert": fmt_plain(ext.get("target_mean_price"), 2, currency), "Bedeutung": "Mittelwert aller Kursziele"},
        {"Kennzahl": "Abstand zum Kursziel", "Wert": fmt_pct(ext.get("upside_pct"), 1, signed=True), "Bedeutung": "negativ: Der Kurs liegt schon darüber"},
        {"Kennzahl": "Börsenwert beim Kursziel", "Wert": fmt_amount(ext.get("implied_market_cap"), cap_currency), "Bedeutung": "Marktkapitalisierung, wenn das Kursziel erreicht wird"},
        {"Kennzahl": "KGV letzte 12 Monate", "Wert": fmt_plain(ext.get("trailing_pe"), 1), "Bedeutung": "Kurs geteilt durch den Gewinn je Aktie"},
        {"Kennzahl": "KGV erwartet", "Wert": fmt_plain(ext.get("forward_pe"), 1), "Bedeutung": "mit dem von Analysten geschätzten Gewinn"},
    ]


def build_pe_history_table(ext: dict) -> pd.DataFrame | None:
    currency = ext.get("currency", "EUR")
    return _by_year_table(ext.get("pe_trend") or [], [
        (f"Kurs zum Jahresende ({currency})", lambda row: fmt_plain(row.get("Kurs"), 2)),
        ("KGV", lambda row: fmt_plain(row.get("KGV"), 1)),
    ])


def build_margin_rows(ext: dict) -> list[dict]:
    return [
        {"Kennzahl": "Bruttomarge", "Wert": fmt_pct(ext.get("gross_margin_ttm")), "Bedeutung": "letzte 12 Monate: Umsatz minus Herstellkosten, im Verhältnis zum Umsatz"},
        {"Kennzahl": "Operative Marge", "Wert": fmt_pct(ext.get("operating_margin_ttm")), "Bedeutung": "letzte 12 Monate: Gewinn aus dem Geschäft vor Zinsen und Steuern, im Verhältnis zum Umsatz"},
    ]


def build_income_history_table(ext: dict) -> pd.DataFrame | None:
    """Revenue, profit and costs per fiscal year in one table (from the gross-margin and cost histories)."""
    merged: dict[int, dict] = {}
    for row in (ext.get("gross_margin_history") or []) + (ext.get("operating_cost_history") or []):
        target = merged.setdefault(row["Jahr"], {"Jahr": row["Jahr"]})
        for key, value in row.items():
            if value is not None and target.get(key) is None:
                target[key] = value

    def operating_profit(row: dict):
        return row.get("Operativer_Gewinn") if row.get("Operativer_Gewinn") is not None else row.get("EBIT")

    return _by_year_table(list(merged.values()), [
        ("Umsatz", lambda row: fmt_amount(row.get("Umsatz"))),
        ("Bruttogewinn", lambda row: fmt_amount(row.get("Bruttogewinn"))),
        ("Bruttomarge", lambda row: fmt_pct(row.get("Bruttomarge"))),
        ("Operativer Gewinn (EBIT)", lambda row: fmt_amount(operating_profit(row))),
        ("Operative Marge", lambda row: fmt_pct(row.get("Operative_Marge"))),
        ("Betriebskosten (OpEx)", lambda row: fmt_amount(row.get("OpEx"))),
        ("… in % vom Umsatz", lambda row: fmt_pct(row.get("OpEx_Quote"))),
        ("Forschung & Entwicklung", lambda row: fmt_amount(row.get("FE"))),
        ("… in % vom Umsatz ", lambda row: fmt_pct(row.get("FE_Quote"))),
        ("Vertrieb & Verwaltung (SG&A)", lambda row: fmt_amount(row.get("SGA"))),
        ("… in % vom Umsatz  ", lambda row: fmt_pct(row.get("SGA_Quote"))),
    ])


def build_dividend_rows(ext: dict) -> list[dict]:
    currency = ext.get("currency", "EUR")
    streak = ext.get("dividend_streak_years") or 0
    return [
        {"Kennzahl": "Dividendenrendite", "Wert": fmt_pct(ext.get("dividend_yield_pct"), 2), "Bedeutung": "erwartete Jahresdividende geteilt durch den Kurs"},
        {"Kennzahl": "Dividende je Aktie", "Wert": fmt_plain(ext.get("dividend_rate"), 2, currency), "Bedeutung": "erwartete Jahresdividende"},
        {"Kennzahl": "Steigerungen in Folge", "Wert": f"{streak} Jahre", "Bedeutung": "Jahre nacheinander mit höherer Dividende"},
    ]


def build_dividend_history_table(ext: dict) -> pd.DataFrame | None:
    currency = ext.get("currency", "EUR")
    return _by_year_table(ext.get("dividend_history") or [], [
        (f"Dividende je Aktie ({currency})", lambda row: fmt_plain(row.get("Dividende"), 2)),
        ("Rendite zum Jahresende", lambda row: fmt_pct(row.get("Rendite (%)"), 2)),
        ("Wachstum zum Vorjahr", lambda row: fmt_pct(row.get("Wachstum (%)"), 1, signed=True)),
    ])


def _key_figure_table(rows: list[dict]) -> None:
    st.dataframe(
        pd.DataFrame(rows),
        use_container_width=True,
        hide_index=True,
        column_config={
            "Kennzahl": st.column_config.TextColumn("Kennzahl", width="medium"),
            "Wert": st.column_config.TextColumn("Wert", width="small"),
            "Bedeutung": st.column_config.TextColumn("Bedeutung", width="large"),
        },
    )


def _year_table(table: pd.DataFrame | None, empty_text: str) -> None:
    if table is None:
        st.caption(empty_text)
        return
    st.dataframe(table, use_container_width=True, hide_index=True,
                 column_config={"Kennzahl": st.column_config.TextColumn("Kennzahl", width="medium")})


def render_company_values(ext: dict) -> None:
    """Company figures as plain tables: profile, valuation, results per year, dividend."""
    currency = ext.get("currency", "EUR")
    fin_currency = ext.get("financial_currency") or currency

    st.markdown("#### 🏢 Profil")
    profile = build_company_profile_line(ext)
    if profile:
        st.markdown(profile)
    summary = ext.get("summary_de")
    if summary:
        with st.expander("Was die Firma macht"):
            st.write(summary)

    st.markdown("#### 💶 Kurs und Bewertung")
    if currency in ("GBp", "GBX"):
        st.caption("Kurs, Kursziel und Dividende je Aktie in Pence (100 Pence = 1 Pfund).")
    _key_figure_table(build_valuation_rows(ext))
    st.markdown("**KGV je Geschäftsjahr**")
    _year_table(build_pe_history_table(ext), "Keine KGV-Werte aus früheren Geschäftsjahren vorhanden.")

    st.markdown("#### 📊 Umsatz, Gewinn und Kosten")
    _key_figure_table(build_margin_rows(ext))
    st.markdown(f"**Je Geschäftsjahr** (in {fin_currency}, geprüfte Jahresabschlüsse)")
    if fin_currency != (ext.get("main_currency") or currency):
        st.caption(f"Die Zahlen aus dem Geschäftsbericht sind in {fin_currency}, der Kurs in {currency}.")
    _year_table(build_income_history_table(ext),
                "Keine Umsatz- und Kostenzahlen ausgewiesen. Das ist typisch für Banken, Versicherungen und ETFs.")

    st.markdown("#### 💰 Dividende")
    _key_figure_table(build_dividend_rows(ext))
    st.markdown("**Je Kalenderjahr**")
    if ext.get("dividend_history"):
        st.caption("Das laufende Jahr ist noch nicht vollständig, deshalb steht dort kein Wachstum.")
    _year_table(build_dividend_history_table(ext), "Keine Dividenden-Historie vorhanden.")


def render_truth_machine_help():
    """Plain-language help for the truth machine and its ETF benchmark."""
    st.markdown("### 🧪 Die Wahrheitsmaschine einfach erklärt")
    st.write(
        "Die Wahrheitsmaschine beantwortet eine einzige Frage: Hätte man mit dieser Aktien-Strategie in den letzten 20 Jahren "
        "mehr Geld verdient als mit einem ganz normalen ETF? Gerechnet wird ohne Gebühren und Steuern, damit allein die Aktienauswahl zählt. "
        "Du findest sie auf der Seite **Forschung** ganz oben."
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
            "Sie weiß im Jahr 2008 also nicht, dass Apple später riesig wird."
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
            "1. **Kauf am Start:** Am ersten Handelstag des Tests wird das ganze Startkapital von 100.000 in den ETF gesteckt.\n"
            "2. **Nichts tun:** Danach wird nichts mehr verändert. Kein Umschichten und kein Trendfilter. Der ETF bleibt immer zu 100 % investiert, auch mitten im Börsencrash.\n"
            "3. **Dividenden:** Ausschüttungen werden automatisch wieder angelegt. Sie stecken schon in den bereinigten Kursen von Yahoo Finance."
        )
        st.markdown(
            "**Ohne Gebühren und Steuern:** Beide Seiten rechnen ohne Transaktionskosten und ohne Steuern. "
            "So zeigt der Test, ob die Auswahl der Aktien selbst etwas taugt. Gebühren und Steuern lassen sich hinterher auf ein Ergebnis draufrechnen, "
            "das diesen Test besteht; ein Ergebnis, das ihn nicht besteht, retten sie nicht. Im echten Leben zahlt die Strategie bei jedem Verkauf Steuer, "
            "der ETF erst am Ende; dieser Nachteil der Strategie fehlt hier bewusst.\n\n"
            "**Was sonst vereinfacht ist:**\n\n"
            "- **Laufende Kosten:** Die jährliche Fondsgebühr steckt bei SPY schon im Kurs.\n"
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
            "5. **Umtausch nach einem Monat:** Wer aus den Top 20 fällt, wird verkauft. Neue Aufsteiger werden gekauft."
        )
        st.warning("Umschichten ist hier kostenlos. Im echten Leben kostet jeder Verkauf mit Gewinn Steuer, und Gebühren kommen dazu. "
                   "Eine Strategie, die hier nur knapp vor dem ETF liegt, liegt in echt dahinter.")

    with st.expander("5. Die Faktoren: nach welchen Noten wird sortiert?"):
        st.table(pd.DataFrame([
            {"Faktor": "momentum_12_1", "Einfach erklärt": "Wie stark ist die Aktie in den letzten 12 Monaten gestiegen? Der jüngste Monat wird weggelassen.",
             "Idee dahinter": "Gewinner bleiben oft eine Weile Gewinner. Der letzte Monat zählt nicht, weil Aktien nach einem starken Monat oft kurz zurückfallen."},
            {"Faktor": "momentum_6_1", "Einfach erklärt": "Dasselbe, aber nur über 6 Monate.", "Idee dahinter": "Eine kürzere, schnellere Version von Momentum."},
            {"Faktor": "low_volatility", "Einfach erklärt": "Wie ruhig ist die Aktie? Wenig Schwankung im letzten Jahr gibt eine gute Note.",
             "Idee dahinter": "Ruhige Aktien bringen erstaunlich oft ähnliche Renditen mit weniger Stress."},
            {"Faktor": "reversal_1m", "Einfach erklärt": "Wer im letzten Monat am stärksten gefallen ist, bekommt die beste Note.",
             "Idee dahinter": "Kurze Übertreibungen drehen oft wieder. Achtung: sehr viel Umschichten, in echt also viel Gebühren und Steuer."},
            {"Faktor": "trend_200d", "Einfach erklärt": "Wie weit liegt der Kurs über seinem Durchschnitt der letzten 200 Handelstage?",
             "Idee dahinter": "Wer über seinem Durchschnitt liegt, steckt in einem Aufwärtstrend."},
        ]))
        st.write(
            "Alle Faktoren werden nur aus Kursen berechnet. Der Grund: Nur Kurse gibt es kostenlos für 20 Jahre rückwirkend. "
            "Was Analysten 2008 über eine Aktie dachten, lässt sich heute nicht mehr abrufen. Deshalb kann die Wahrheitsmaschine den Aktien-Score selbst nicht über 20 Jahre testen."
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
            "- Keine Gebühren und keine Steuern\n"
            "- Umschichten einmal im Monat\n"
            "- Gleiche Gewichtung aller ausgewählten Aktien\n\n"
            "Über die Kommandozeile mit `python -m factor_lab --help` lassen sich einige davon ändern, zum Beispiel Umschicht-Rhythmus und Sektorgrenze."
        )

    with st.expander("7. Die Ergebnisse lesen"):
        st.markdown(
            "**Zeitraum und Universum** zeigen, von wann bis wann gerechnet wurde und wie viele Aktien im Topf waren.\n\n"
            "**Das Urteil** wird automatisch aus den Zahlen geschrieben. Niemand hat es schöngeredet."
        )
        st.table(pd.DataFrame([
            {"Zeile": "Rendite p. a.", "Bedeutung": "Die wichtigste Zeile: um wie viel Prozent der Depotwert im Schnitt pro Jahr gewachsen ist, ohne Gebühren und Steuern."},
            {"Zeile": "Volatilität p. a.", "Bedeutung": "Wie stark der Wert schwankt. Wie bei einer Achterbahn: Ein hoher Wert bedeutet eine wilde Fahrt."},
            {"Zeile": "Maximaler Verlust", "Bedeutung": "Der größte Absturz vom bisherigen Höchststand. −24 % heißt: Aus 100 € wurden zwischendurch 76 €."},
            {"Zeile": "Sharpe Ratio", "Bedeutung": "Rendite pro Schwankung, ähnlich wie Tore pro Spielminute. Bei Aktien ist 0,5 normal und über 1 sehr gut."},
            {"Zeile": "Endvermögen", "Bedeutung": "Der Depotwert am Ende, ausgehend von 100.000."},
        ]))
        st.markdown(
            "**Die Vermögenskurve** zeigt beide Wege als Linien über die Zeit.\n\n"
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

    with st.expander("10. Aktien-Score auf dem Prüfstand"):
        st.markdown(
            "Jeden Tag speichert die App einen **Snapshot**, also ein Foto aller Aktien-Scores. Der Prüfstand schaut nach: "
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
            "- **Schlägt die Strategie den ETF schon ohne Gebühren und Steuern nicht,** ist der ETF für den Großteil des Geldes die vernünftigere Wahl.\n"
            "- **Schlägt sie ihn, aber nicht belastbar,** kann es Glück gewesen sein. Dann lieber erst mit wenig Geld oder auf dem Papier weiter beobachten.\n"
            "- **Schlägt sie ihn belastbar,** solltest du trotzdem den Survivorship Bias bedenken und mit einem kleinen Teil des Geldes starten.\n\n"
            "Der erste Lauf mit den Standardeinstellungen auf dem S&P 500 (damals noch mit Gebühren und Steuern) ergab 7,5 % pro Jahr. Der ETF schaffte 10,0 %. "
            "Die Strategie hatte dafür nur etwa halb so große Abstürze."
        )
        st.caption("Die Wahrheitsmaschine ist ein Lern- und Prüfwerkzeug und keine Anlageberatung.")


def build_v3_help_rows() -> list[dict]:
    """Help table of Rang-Score, the points come straight from the weights in the code."""
    return [
        {"Baustein": BRODEL_V3_LABELS.get(name, name), "Punkte": str(weight), "Was gemessen wird": BRODEL_V3_EXPLANATIONS[name]}
        for name, weight in BRODEL_V3_WEIGHTS.items()
    ]


BRODEL_V3_EXPLANATIONS = {
    "Qualitaet": "Operative Marge, Gesamtkapitalrendite und Free Cashflow im Verhältnis zu den Schulden",
    "Momentum": "Kursentwicklung der letzten 12 Monate ohne den letzten Monat",
    "EPS-Revisionen": "Anteil der Analysten-Hochstufungen an allen Änderungen; bei wenigen Analysten zur Mitte gezogen",
    "Bewertung": "Gewinn und Free Cashflow im Verhältnis zum Preis",
    "Aktienrueckkauf": "Rückgang der Aktienzahl in den letzten 12 Monaten",
    "Insider": "Käufe am offenen Markt in 90 Tagen (USA, Europa, Kanada; nicht Japan und Indien). Keine Käufe oder keine Daten 5, unter 100.000 $ 7,5, ab 100.000 $ 10 Punkte",
}


HELP_SCORE_ROWS = [
    {"Score": "Rang-Score", "Skala": "0 bis 100", "Frage": "Wie gut ist die Aktie im Vergleich zu ähnlichen Aktien?",
     "Bausteine": "6", "Genutzt von": "Spieldepot „Rang-Score beste 2 %“, Startseite"},
    {"Score": "Punkte-Score", "Skala": "−30 bis 90", "Frage": "Wie viele feste Punkte sammelt die Aktie bei 11 Signalen?",
     "Bausteine": "11", "Genutzt von": "Spieldepots „Punkte-Score ab 60“, Score-Prüfstand"},
]

HELP_INSIDER_SOURCE_ROWS = [
    {"Land": "USA", "Quelle": "SEC-Meldungen (über Finnhub)"},
    {"Land": "Deutschland", "Quelle": "BaFin-Meldungen über Tracefour (CC BY 4.0)"},
    {"Land": "Schweiz", "Quelle": "SIX Exchange Regulation"},
    {"Land": "Frankreich", "Quelle": "AMF (PDF-Meldungen)"},
    {"Land": "Niederlande", "Quelle": "AFM-Register"},
    {"Land": "Großbritannien, Kanada, Spanien, Australien u. a.", "Quelle": "Yahoo Finance"},
    {"Land": "Japan, Indien", "Quelle": "keine freie Quelle, zählt neutral"},
]

HELP_DATA_SOURCE_ROWS = [
    {"Quelle": "Yahoo Finance", "Wofür": "Kurse, Volumen, Kennzahlen, Analysten-Revisionen, News, Termine, Aktienanzahl, Wechselkurse, Insider außerhalb der USA",
     "Aktualität": "jeder Nachtlauf"},
    {"Quelle": "Finnhub", "Wofür": "Analysten-Empfehlungen, Insider-Daten USA (SEC)", "Aktualität": "Zwischenspeicher 24 Stunden"},
    {"Quelle": "SIX, AMF, AFM, Tracefour", "Wofür": "Insider-Käufe in Europa",
     "Aktualität": "jeder Nachtlauf, gelesene Meldungen in insider_data/"},
    {"Quelle": "Google Gemini", "Wofür": "Stimmung der News-Überschriften, sonst Stichwortliste", "Aktualität": "jeder Nachtlauf"},
    {"Quelle": "Wikipedia", "Wofür": "Mitglieder der Indizes (S&P 500, DAX, Nikkei 225 …)", "Aktualität": "beim Aufbau der Watchlist"},
]


def build_points_help_rows() -> list[dict]:
    """Overview of the Punkte-Score blocks, the maxima come straight from the code."""
    return [
        {"Baustein": BRODEL_COMPONENT_LABELS.get(name, name), "Max. Punkte": str(points)}
        for name, points in sorted(BRODEL_V2_MAX_POINTS.items(), key=lambda item: -item[1])
    ]


def _help_overview() -> None:
    st.markdown(
        "StockWatcher bewertet jeden Werktag alle Aktien der Watchlist und prüft mit Spielgeld, ob diese Bewertung etwas taugt. "
        "Es gibt **zwei Scores**:"
    )
    st.table(pd.DataFrame(HELP_SCORE_ROWS))
    st.markdown("#### Die Seiten")
    st.markdown(
        "- **🏠 Start:** Datenstand, beste Aktien und Spieldepots auf einen Blick.\n"
        "- **📊 Marktbeobachtung:** alle Aktien mit beiden Scores. Ein Klick auf eine Zeile öffnet die Detailansicht mit Berechnung und Unternehmenswerten.\n"
        "- **💼 Trades:** die Spieldepots mit Käufen, Verkäufen und Stop-Loss.\n"
        "- **🔬 Forschung:** Wahrheitsmaschine, Score-Prüfstand und Backtests.\n"
        "- **❓ Hilfe:** diese Seite."
    )
    st.markdown("#### So liest du einen Score")
    st.markdown(
        "- Ein Score ist eine **Platzierung am jeweiligen Tag**, keine Wahrscheinlichkeit und kein Kursziel.\n"
        "- Schau in der Detailansicht, welche Bausteine den Wert tragen und ob echte Daten dahinterstehen.\n"
        "- Ein hoher Score ist ein Anlass zum Recherchieren, keine Kaufentscheidung."
    )
    st.warning("Die App gibt keine Anlageberatung und führt keine Orders aus. Ob die Scores einen ETF schlagen, ist nicht bewiesen.")


def _help_rank_score() -> None:
    st.markdown(
        "Der Rang-Score fragt: **Wie gut ist diese Aktie im Vergleich zu den anderen?** Für jeden Baustein bekommt jede Aktie einen Rang. "
        "Wer besser ist als 80 % der Vergleichsaktien, bekommt 80 % der Punkte dieses Bausteins."
    )
    st.table(pd.DataFrame(build_v3_help_rows()))
    st.markdown(
        "**Beispiel:** Qualität 24,1 + Momentum 19,1 + EPS-Revisionen 19,6 + Bewertung 13,9 + Rückkauf 4,9 + Insider 5 (neutral) "
        "= **86,6** von 100. Die Aktie ist damit im Mittel besser als rund 87 % ihrer Vergleichsaktien."
    )
    with st.expander("Mit wem wird verglichen?"):
        st.markdown(
            "- Immer innerhalb **derselben Region** (Amerika, Europa, Asien).\n"
            "- Qualität und Bewertung zusätzlich innerhalb **desselben Sektors**, denn eine Bank hat andere Kennzahlen als ein Softwarehaus."
        )
    with st.expander("Warum Gesamtkapitalrendite statt Eigenkapitalrendite?"):
        st.markdown(
            "Firmen, die über Jahre eigene Aktien zurückkaufen, haben oft fast kein oder sogar negatives Eigenkapital in der Bilanz. "
            "Eigenkapitalrendite und Verschuldung zum Eigenkapital werden dann unbrauchbar: mal über 100 %, mal gar nicht vorhanden. "
            "Seit dem 11.11.2026 misst die Qualität deshalb die operative Marge, die Rendite auf das gesamte Kapital und den Free Cashflow "
            "im Verhältnis zu den Schulden. Alle drei bleiben vergleichbar, egal wie viel Eigenkapital durch Rückkäufe verschwunden ist. "
            "Tage davor im Score-Verlauf nutzen noch die alten Kennzahlen."
        )
    with st.expander("Wenige Analysten, volle Punkte?"):
        st.markdown(
            "Bei den EPS-Revisionen zählt der Anteil der Hochstufungen. Damit 2 Hochstufungen von 2 Analysten (100 %) nicht vor "
            "18 Hochstufungen und 1 Abstufung (95 %) landen, wird je eine gedachte Hoch- und Abstufung dazugezählt: "
            "aus 2:0 werden 75 %, aus 18:1 werden 90 %. Breiter Konsens gewinnt gegen Zufallstreffer."
        )
    with st.expander("Was passiert, wenn Daten fehlen?"):
        st.markdown(
            "- Fehlt ein Baustein, wird über die übrigen gerechnet. Beispiel ohne Rückkauf: 81,7 von 90 möglichen Punkten ergeben 90,8.\n"
            "- Eine Aktie braucht mindestens **4 Bausteine mit echten Daten**, sonst bekommt sie keinen Wert. ETFs und Indizes bleiben außen vor.\n"
            "- **Insider** ist die Ausnahme: Fehlen Daten, zählt er wie „keine Käufe“, also neutral 5 von 10. "
            "Sonst hätten Aktien aus Ländern ohne Datenquelle einen Vorteil."
        )
    with st.expander("Woher kommen die Insider-Daten?"):
        st.table(pd.DataFrame(HELP_INSIDER_SOURCE_ROWS))
        st.markdown(
            "Es zählen nur Käufe am offenen Markt, keine Rückkäufe der Firma, Optionen oder Mitarbeiteraktien. "
            "Die deutschen Daten stellt [Tracefour](https://tracefour.com/de) bereit. "
            "Der Wochencheck am Sonntag meldet, wenn eine Quelle ausfällt oder ihr Format ändert."
        )
    with st.expander("Die Spalten in der Marktbeobachtung"):
        st.markdown(
            "- **Bausteine:** Rechts oben schaltest du um, ob die Spalten die 6 Bausteine des Rang-Scores oder die 11 des Punkte-Scores zeigen. "
            "Grün heißt oberes Drittel der Vergleichsaktien, rot unteres Drittel.\n"
            "- **Rang:** Platz unter den Aktien derselben Region und desselben Sektors, zum Beispiel 1/43 = beste von 43 europäischen Finanzwerten.\n"
            "- **Vs. Sektor:** Rang-Score minus Durchschnitt dieser Gruppe. +37 heißt 37 Punkte über dem Schnitt.\n"
            "- Aktien ohne Rang-Score (ETFs, zu wenige Daten) haben dort ein „–“."
        )
    with st.expander("Warum diese 6 Bausteine?"):
        st.markdown(
            "Preis/Volumen, Technik, Kursziele, News, Event-Druck und Short Interest sind nicht dabei. "
            "Sie zeigten in unseren Tests keinen Nutzen, sind nicht rückwirkend prüfbar oder messen eher Aufmerksamkeit als Qualität. "
            "Die Marktlage gehört ebenfalls nicht in den Score."
        )
    st.info("Die Gewichte sind fachlich begründete Startwerte, kein Messergebnis. Ob der Rang-Score besser ist, zeigt erst der Vergleich der Spieldepots über mindestens 12 Monate.")


def _help_points_score() -> None:
    st.markdown(
        "Der Punkte-Score zählt **feste Punkte** aus 11 Bausteinen zusammen. Die Summe liegt zwischen −30 und 90. "
        "Bausteine, die in den Tests geholfen haben, bekommen mehr Punkte."
    )
    st.table(pd.DataFrame(build_points_help_rows()))
    st.markdown("### Die 11 Bausteine")
    st.caption("Aufklappen für die genauen Regeln und die Datenquelle.")

    with st.expander("📊 EPS-Revisionen (max. 15)"):
        st.write("**Was es misst:** Haben Analysten ihre Gewinnschätzungen (Gewinn je Aktie) zuletzt nach oben oder nach unten korrigiert?")
        st.markdown("- Gezählt wird der **Anteil** der Hochstufungen an allen Revisionen (mindestens 2 Revisionen): ab 80 % **+15**, ab 65 % **+10**, ab 50 % **+5**, höchstens 35 % **−5**.")
        st.write("**Warum ein Anteil und keine Anzahl:** Große Firmen haben viele Analysten und hätten sonst fast immer volle Punkte.")
        st.write("**Datenquelle:** Yahoo Finance (`yfinance`)")

    with st.expander("🎯 Kursziele & Konsens (max. 5)"):
        st.write("**Was es misst:** Wie weit liegt das durchschnittliche Analysten-Kursziel über dem Kurs, und wie viele Analysten raten zum Kauf?")
        st.markdown("- Kursziel mindestens 20 % über dem Kurs: **+10**, mindestens 10 %: **+5**, darüber: **+2**.")
        st.markdown("- Bei mindestens 5 Analysten: Kaufempfehlungen ab 80 %: **+5**, ab 60 %: **+3**.")
        st.markdown("- Die Summe (höchstens 15) wird auf ein Drittel gekürzt, also höchstens **5** Punkte.")
        st.write("**Datenquelle:** Kursziele von Yahoo Finance, Empfehlungen von Finnhub mit Fallback auf Yahoo Finance")
        st.warning("Analysten hinken dem Kurs oft hinterher. Fällt eine Aktie stark, sieht das Kurspotenzial plötzlich groß aus. In den Snapshots liefen Aktien mit hohem Kursziel-Potenzial nach 3 Monaten sogar schlechter.")

    with st.expander("📰 News-Sentiment (max. 15)"):
        st.write("**Was es misst:** Wie viele Nachrichten gab es in den letzten 7 Tagen, und klingen sie gut oder schlecht?")
        st.markdown("- **Nachrichtendichte:** ab 2 Meldungen **+3**, ab 4 **+5**, ab 6 **+7**.")
        st.markdown("- **Stimmung:** Die Überschriften werden per KI (Gemini) oder Stichwortliste bewertet: **−8 bis +8**.")
        st.markdown("- Summe begrenzt auf −10 bis +15.")
        st.write("**Datenquelle:** Yahoo Finance (`yfinance`)")

    with st.expander("🏦 Fundamentale Bewertung (max. 15)"):
        st.write("**Was es misst:** Ist die Firma solide und günstig bewertet?")
        st.markdown("- **KGV (Forward P/E):** unter 15 **+2**, unter 25 **+1**, über 50 **−2**.")
        st.markdown("- **PEG-Ratio:** unter 1,0 **+2**, unter 1,5 **+1**.")
        st.markdown("- **Verschuldung (Debt/Equity):** unter 50 % **+2**, unter 100 % **+1**.")
        st.markdown("- **Free-Cashflow-Rendite:** über 5 % **+2**, über 2 % **+1**.")
        st.markdown("- **Gewinnmarge:** über 20 % **+2**, über 10 % **+1**.")
        st.markdown("- Die Summe (höchstens 10) wird mal 1,5 genommen, also höchstens **15** Punkte. In den Snapshots war das der stärkste Baustein.")
        st.write("**Datenquelle:** Yahoo Finance")

    with st.expander("🔁 Aktienrückkauf (max. 5)"):
        st.write("**Was es misst:** Hat die Firma heute weniger Aktien als vor einem Jahr? Dann kauft sie eigene Aktien zurück. Jedem Aktionär gehört danach ein größeres Stück der Firma.")
        st.markdown("- Mindestens 3 % weniger Aktien: **+5**, mindestens 1 % weniger: **+3**.")
        st.markdown("- Mindestens 5 % mehr Aktien (Verwässerung durch neue Aktien): **−2**.")
        st.write("**Warum:** Im Test 2017 bis 2026 liefen die stärksten Rückkäufer gut 1,8 % pro Jahr besser als der Durchschnitt. Das ist ein kleiner Vorteil und statistisch noch nicht sicher, zeigte aber in die richtige Richtung.")
        st.write("**Datenquelle:** Yahoo Finance (Aktienanzahl-Historie)")

    with st.expander("🚀 Preis/Volumen (max. 5)"):
        st.write("**Was es misst:** Läuft der Kurs im Aufwärtstrend, und fließt gerade viel Geld in die Aktie?")
        st.markdown("- Kurs über der 20-Tage-Linie: **+5**, über der 50-Tage-Linie: **+6**.")
        st.markdown("- In 5 Tagen mindestens 7 % gestiegen: **+4**, mindestens 7 % gefallen: **−3**.")
        st.markdown("- Steigender Tag mit mehr als dem 1,5-fachen Durchschnittsvolumen: **+3**.")
        st.markdown("- Summe begrenzt auf −10 bis +10, davon zählt die Hälfte, also höchstens **5** Punkte.")
        st.write("**Warum nur halbe Punkte:** Über 20 Jahre nachgerechnet halfen diese Regeln nicht. Auf Wochensicht liefen Aktien über der 20-Tage-Linie sogar leicht schlechter.")
        st.write("**Datenquelle:** Yahoo Finance (`yfinance`)")

    with st.expander("📈 Technische Indikatoren (max. 5)"):
        st.write("**Was es misst:** Ist die Aktie rechnerisch überkauft oder überverkauft?")
        st.markdown("- **RSI:** unter 30 (überverkauft) **+4**, über 70 (überkauft) **−4**.")
        st.markdown("- **MACD:** über der Signallinie **+3**, darunter **−1**.")
        st.markdown("- **Bollinger-Bänder:** Kurs unter dem unteren Band **+3**, über dem oberen Band **−3**.")
        st.markdown("- Summe begrenzt auf −8 bis +10, davon zählt die Hälfte, also höchstens **5** Punkte.")
        st.write("**Datenquelle:** Yahoo Finance (6 Monate Kurshistorie)")

    with st.expander("👔 Insider-Aktivität (max. 10)"):
        st.write("**Was es misst:** Kaufen Vorstände und Direktoren mit eigenem Geld Aktien ihrer Firma?")
        st.markdown("- Insider-Stimmung der letzten 3 Monate: viele Käufe **+10**, mehrere **+6**, ein Kauf **+4**.")
        st.markdown("- Mehr als doppelt so viele Verkäufe wie Käufe: **−3** (nicht unter 0).")
        st.write("**Datenquelle:** Finnhub (Insider Sentiment aus SEC-Form-4-Meldungen) mit Fallback auf Yahoo Finance. "
                 "Finnhub liefert die Netto-Veränderung je Monat, deshalb steht im Detail „Käufe über 100 Aktien“ statt einer Anzahl. "
                 "Aktienrückkäufe der Firma selbst zählen nicht als Insider-Kauf.")
        st.info("Insider verkaufen aus vielen Gründen (Steuern, Hauskauf), aber sie kaufen meist nur aus einem: Sie glauben an steigende Kurse.")

    with st.expander("💪 Relative Stärke (max. 5)"):
        st.write("**Was es misst:** Lief die Aktie im letzten Monat besser als ihr Heimatindex (z. B. S&P 500, DAX, Nikkei 225)?")
        st.markdown("- Mindestens 10 Prozentpunkte besser: **+5**, mindestens 5: **+3**, mindestens 2: **+1**.")
        st.write("**Datenquelle:** Yahoo Finance (`yfinance`)")

    with st.expander("📅 Event-Druck (max. 5)"):
        st.write("**Was es misst:** Steht bald ein Termin an, zum Beispiel Quartalszahlen?")
        st.markdown("- Nächster Termin in höchstens 7 Tagen: **+5**, in höchstens 14 Tagen: **+3**, in höchstens 30 Tagen: **+1**.")
        st.write("**Datenquelle:** Yahoo Finance (`yfinance`)")

    with st.expander("🔥 Short Interest (max. 5)"):
        st.write("**Was es misst:** Wetten viele Leerverkäufer auf fallende Kurse? Steigt der Kurs trotzdem, müssen sie teuer zurückkaufen (Short Squeeze).")
        st.markdown("- Nur wenn der Kurs über der 50-Tage-Linie liegt: Short-Anteil ab 20 % **+5**, ab 10 % **+3**, ab 5 % **+1**.")
        st.markdown("- Alternativ nach Tagen zum Eindecken: ab 5 Tagen **+4**, ab 3 Tagen **+2**.")
        st.markdown("- Unter der 50-Tage-Linie gibt es **0 Punkte**, denn dann haben die Leerverkäufer bisher recht.")
        st.write("**Datenquelle:** Yahoo Finance (`yfinance`)")

def _help_trades() -> None:
    st.markdown(
        "Jedes Depot startet mit **100.000 €** und kauft Aktien für je 5.000 €, höchstens 20 Stück. Es wird nur simuliert, es fließt kein echtes Geld."
    )
    st.table(pd.DataFrame([
        {"Depot": "Punkte-Score ab 60", "Kauft": "jede Aktie ab 60 Punkten, höchste zuerst", "Verkauft": "per Stop-Loss"},
        {"Depot": "Punkte-Score ab 60 ohne Stop-Loss", "Kauft": "dieselben Aktien", "Verkauft": "nie, zeigt, ob der Stop-Loss hilft"},
        {"Depot": "Rang-Score beste 2 %", "Kauft": "die besten 2 % des Tages, höchstens 5 pro Tag und 25 % je Sektor, nichts in der Woche vor Quartalszahlen",
         "Verkauft": "per Stop-Loss"},
        {"Depot": "MSCI World ETF", "Kauft": "einmal am Start", "Verkauft": "nie, die Messlatte"},
    ]))
    st.markdown(
        "**Stop-Loss:** 15 % unter dem Kaufkurs. Er steigt mit dem höchsten Schlusskurs mit und sinkt nie. "
        "Liegt der Höchststand 25 % über dem Kaufkurs, rückt er auf 10 % Abstand. Die genauen Regeln stehen auf der Seite **Trades**."
    )


def _help_research() -> None:
    render_truth_machine_help()
    st.markdown("### Weitere Werkzeuge auf der Seite Forschung")
    with st.expander("Event-Backtest: Punktebereich-Eintritt"):
        st.markdown(
            "Kauft alle Aktien an dem Tag, an dem ihr Punkte-Score in einen gewählten Bereich eintritt, "
            "teilt das Kapital gleichmäßig auf und zeigt den heutigen Wert des Depots. Grundlage sind die gespeicherten Snapshots."
        )
    with st.expander("Klassischer Rebalancing-Backtest"):
        st.markdown(
            "Hält die Aktien mit dem höchsten Punkte-Score und stellt das Depot in festen Abständen neu zusammen.\n\n"
            "- **Startkapital, Max. Positionen, Rebalancing (Tage):** die Spielregeln.\n"
            "- **Benchmark:** Vergleichsindex, zum Beispiel SPY oder DAX.\n"
            "- **Ergebnisse:** Rendite, Rendite pro Jahr (CAGR), Sharpe Ratio, größter Rückgang (Max Drawdown), Trefferquote und Vorsprung zur Benchmark (Alpha).\n\n"
            "Gekauft wird frühestens am nächsten Handelstag. Spreads und Kurslücken sind nicht vollständig abgebildet, echte Ausführungen können schlechter sein."
        )
    with st.expander("ML-Gewichtung"):
        st.markdown(
            "Verbindet die Snapshots mit der Rendite der folgenden 30 Tage und schätzt, welche Bausteine des Punkte-Scores mehr Gewicht verdienen.\n\n"
            "- Gelernt wird an den ältesten 70 % der Snapshot-Tage, geprüft an den jüngsten, mit 30 Tagen Abstand dazwischen. "
            "Diese Prüfung braucht mindestens 60 Snapshot-Tage.\n"
            "- Die Gewichte gelten nur, wenn sie im Prüfzeitraum besser sortieren als gleiche Gewichte. Bis dahin zeigt die Tabelle keinen ML-Score."
        )


def _help_data_sources() -> None:
    st.table(pd.DataFrame(HELP_DATA_SOURCE_ROWS))
    st.markdown(
        "- **Nachtlauf:** Jeden Werktag nach US-Börsenschluss rechnet GitHub alle Aktien neu und speichert einen **Snapshot**. "
        "Ein zweiter Lauf am nächsten Morgen springt ein, falls der erste ausfällt.\n"
        "- **Gedrosselte Daten:** Liefert Yahoo für eine Aktie nichts, wird sie im selben Lauf erneut abgefragt. "
        "Die Startseite zeigt, wie viele Aktien frische Daten haben.\n"
        "- **Wochencheck:** Jeden Sonntag prüft GitHub alle Verbindungen dieser Tabelle, die Läufe der Woche und die App. "
        "Bei einem Fehler kommt eine E-Mail mit einem Bericht als GitHub-Issue."
    )
    st.caption("Zwischengespeicherte Daten sparen Abrufe, können aber etwas älter sein als der Snapshot.")


def render_help_tab():
    st.subheader("Hilfe & Methodik")
    tabs = st.tabs(["Überblick", "Rang-Score", "Punkte-Score", "Spieldepots", "Forschung", "Datenquellen"])
    with tabs[0]:
        _help_overview()
    with tabs[1]:
        _help_rank_score()
    with tabs[2]:
        _help_points_score()
    with tabs[3]:
        _help_trades()
    with tabs[4]:
        _help_research()
    with tabs[5]:
        _help_data_sources()


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
        {"Kennzahl": "Rendite p. a.", "Strategie": pct(m["cagr"]), "ETF": pct(b["cagr"])},
        {"Kennzahl": "Volatilität p. a.", "Strategie": pct(m["volatility"]), "ETF": pct(b["volatility"])},
        {"Kennzahl": "Maximaler Verlust", "Strategie": pct(m["max_drawdown"]), "ETF": pct(b["max_drawdown"])},
        {"Kennzahl": "Sharpe Ratio", "Strategie": ratio(m["sharpe"]), "ETF": ratio(b["sharpe"])},
        {"Kennzahl": "Endvermögen", "Strategie": money(m["final_value"]), "ETF": money(b["final_value"])},
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
        "Testet kursbasierte Faktoren über bis zu 20 Jahre gegen einen ETF, ohne Gebühren und Steuern, mit Trendfilter für die Investitionsquote. "
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
    c4, c5 = st.columns(2)
    with c4:
        trend_filter = st.checkbox("Trendfilter (ETF unter 200-Tage-Linie)", value=True, key="truth_trend")
    with c5:
        risk_off = st.slider("Investitionsquote im Abwärtstrend", 0.0, 1.0, 0.5, 0.1, disabled=not trend_filter, key="truth_risk_off")

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


BRODEL_CHECK_VERSIONS = [("Punkte-Score", "brodel_score_v2")]


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
    st.subheader("🔬 Aktien-Score auf dem Prüfstand")
    st.write(
        "Misst, ob ein hoher Aktien-Score in den gespeicherten Snapshots tatsächlich höhere Folgerenditen gebracht hat. "
        "Gemessen wird der **Punkte-Score**. "
        "Überlappende Zeitfenster werden für den belastbaren t-Wert herausgerechnet."
    )
    st.caption(
        "Für ältere Snapshots wird der Punkte-Score aus den gespeicherten Einzelpunkten nachgerechnet, ohne Rückkauf-Daten."
    )
    horizon = st.select_slider("Horizont (Handelstage)", options=[5, 10, 21, 63], value=21, key="brodel_horizon")
    if st.button("Score messen", use_container_width=True):
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
        main = results["Punkte-Score"]
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
            st.success(f"Punkte-Score sortiert signifikant (t = {independent['t_stat']:.1f}).")
        else:
            st.info(f"Kein signifikanter Effekt für Punkte-Score (t = {independent['t_stat']:.1f}).")


def render_backtest_tab():
    with st.expander("⚙️ Datenpflege: Signal-Snapshot manuell erstellen", expanded=False):
        st.write(
            "Berechnet die aktuellen Frühsignale für alle Aktien der Hintergrund-Watchlist (`watchlists/meine_watchlist.txt`) "
            "und speichert einen tagesaktuellen Snapshot für die Marktbeobachtung, Backtests und ML-Training."
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
            "Punktebereich (Aktien-Score)",
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


BOT_SERIES = {
    "rank": "Rang-Score beste 2 %",
    "bot": "Punkte-Score ab 60",
    "no_stop": "Punkte-Score ohne Stop-Loss",
    "etf": "MSCI World ETF",
}


def build_bot_equity_frame(state: dict) -> pd.DataFrame:
    rows = state.get("equity", []) if state else []
    if not rows:
        return pd.DataFrame(columns=list(BOT_SERIES.values()))
    frame = pd.DataFrame(rows)
    frame["day"] = pd.to_datetime(frame["day"])
    return frame.set_index("day").rename(columns=BOT_SERIES).reindex(columns=list(BOT_SERIES.values()))


def build_bot_position_rows(portfolio: dict, config: dict) -> list[dict]:
    rows = []
    for position in portfolio.get("positions", []):
        entry, last, stop = position["entry_price"], position["last_price"], position["stop"]
        row = {
            "Symbol": position["symbol"],
            "Name": position.get("name", ""),
            "Gekauft am": position["entry_day"],
            "Score beim Kauf": position.get("score_at_buy"),
            "Kaufkurs": round(entry, 2),
            "Aktuell": round(last, 2),
            "Plus/Minus %": round((last / entry - 1) * 100, 1),
            "Wert €": position.get("last_value_eur", position["cost_eur"]),
            "Währung": position.get("currency", ""),
        }
        if portfolio.get("use_stop", True):
            row["Stop-Loss"] = round(stop, 2)
            row["Abstand zum Stop %"] = round((last / stop - 1) * 100, 1) if stop else None
            row["Stop-Abstand"] = f"{paper_bot.stop_distance(position, config) * 100:.0f} %"
        rows.append(row)
    return sorted(rows, key=lambda r: r["Plus/Minus %"], reverse=True)


def build_bot_trade_rows(portfolio: dict) -> list[dict]:
    rows = []
    for trade in reversed(portfolio.get("trades", [])):
        rows.append({
            "Datum": trade.get("day"),
            "Art": trade.get("side"),
            "Symbol": trade.get("symbol"),
            "Name": trade.get("name", ""),
            "Kurs": trade.get("price"),
            "Stück": trade.get("shares"),
            "Betrag €": trade.get("value_eur"),
            "Gewinn/Verlust €": trade.get("pnl_eur"),
            "Gewinn/Verlust %": trade.get("pnl_pct"),
            "Grund": trade.get("reason", ""),
        })
    return rows


def render_bot_tab():
    st.subheader("💼 Trades: drei Spieldepots im Vergleich")
    state = paper_bot.load_state()
    cfg = (state or {}).get("config", paper_bot.DEFAULT_CONFIG)
    with st.expander("Regeln des Bots", expanded=state is None):
        st.markdown(
            f"- Läuft einmal täglich nach dem letzten US-Lauf und nutzt nur den Snapshot dieses Tages.\n"
            f"- **Depot Punkte-Score:** kauft jede Aktie ab **{cfg['buy_threshold']} Punkten**, die höchsten zuerst.\n"
            f"- **Depot Rang-Score:** kauft die besten **{cfg['top_share'] * 100:.0f} % des Tages**, höchstens {cfg['max_buys_per_day']} Käufe pro Tag "
            f"und {cfg['sector_cap'] * 100:.0f} % des Depots je Sektor, keine Aktie in der Woche vor ihren Quartalszahlen.\n"
            f"- **Beide:** je **{cfg['position_budget']:,.0f} €**, höchstens **{cfg['max_positions']} Aktien**, Kauf zur Eröffnung am nächsten Handelstag "
            f"(1 € Gebühr, London {cfg['uk_stamp_duty'] * 100:.1f} % Stempelsteuer, Tokio in 100er-Stückelung).\n"
            f"- **Datenprüfung:** Neue Käufe nur, wenn mindestens {cfg['min_coverage'] * 100:.0f} % der Tagesdaten frisch sind.\n"
            f"- **Stop-Loss:** {cfg['initial_stop'] * 100:.0f} % unter dem Kaufkurs. Er wird jeden Tag zum höchsten Schlusskurs nachgezogen "
            f"und sinkt nie. Ab **+{cfg['tighten_after_gain'] * 100:.0f} %** Gewinn rückt er auf **{cfg['tight_stop'] * 100:.0f} %** heran.\n"
            f"- **Verkauf:** sobald der Tiefstkurs den Stop berührt, zum Stop-Kurs minus {cfg.get('stop_slippage', 0) * 100:.1f} % "
            "Slippage (eine ausgelöste Stop-Order wird zur Bestens-Order), aber nie unter dem Tagestief. "
            "Eröffnet die Aktie schon unter dem Stop, wird zur Eröffnung verkauft.\n"
            f"- **Sperre:** Eine verkaufte Aktie wird frühestens nach {cfg['cooldown_days']} Tagen wieder gekauft.\n"
            "- **Vergleich:** Dieselben Käufe ohne Stop-Loss und ein MSCI-World-ETF mit demselben Startkapital. "
            "So zeigt sich, ob der Stop-Loss und die Aktienauswahl etwas bringen."
        )
    if not state:
        st.info("Das Bot-Depot wird mit dem nächsten nächtlichen US-Lauf angelegt.")
        return

    last = state["equity"][-1] if state["equity"] else {}
    capital = cfg["capital"]
    cols = st.columns(len(BOT_SERIES))
    for col, (key, label) in zip(cols, BOT_SERIES.items()):
        value = last.get(key, capital)
        col.metric(label, f"{value:,.0f} €", f"{(value / capital - 1) * 100:+.2f} %")
    st.caption(f"Gestartet am {state['started']}, letzter Lauf {state['last_run']}, bewertet mit Schlusskursen bis {last.get('day', '-')}.")
    coverage = state.get("coverage") or {}
    if coverage and coverage.get("fresh", 0) < cfg["min_coverage"]:
        st.warning(f"Am {coverage['day']} waren nur {coverage['fresh'] * 100:.0f} % der Daten frisch. An diesem Tag gab es keine neuen Käufe.")

    equity = build_bot_equity_frame(state)
    if len(equity) > 1:
        st.line_chart(equity)

    depots = {meta["label"]: key for key, meta in paper_bot.PORTFOLIOS.items() if key in state["portfolios"]}
    choice = st.radio("Depot", list(depots), horizontal=True, key="bot_depot_choice")
    portfolio = state["portfolios"][depots[choice]]
    st.markdown(f"**Bestand** ({len(portfolio['positions'])} von {cfg['max_positions']} Plätzen, Cash {portfolio['cash']:,.0f} €)")
    position_rows = build_bot_position_rows(portfolio, cfg)
    if position_rows:
        st.dataframe(pd.DataFrame(position_rows), use_container_width=True, hide_index=True,
                     height=breakdown_table_height(len(position_rows)))
    else:
        st.caption("Noch keine Aktien im Depot.")
    if portfolio["pending"]:
        st.markdown("**Offene Kauforders** (werden zur nächsten Eröffnung ausgeführt)")
        st.dataframe(pd.DataFrame([
            {"Symbol": o["symbol"], "Name": o.get("name", ""), "Punkte-Score": o["score"], "Entschieden am": o["order_day"]}
            for o in portfolio["pending"]
        ]), use_container_width=True, hide_index=True)
    trades = build_bot_trade_rows(portfolio)
    if trades:
        st.markdown("**Käufe und Verkäufe**")
        st.dataframe(pd.DataFrame(trades), use_container_width=True, hide_index=True)


PAGE_START = "🏠 Start"
PAGE_MARKET = "📊 Marktbeobachtung"
PAGE_TRADES = "💼 Trades"
PAGE_RESEARCH = "🔬 Forschung"
PAGE_HELP = "❓ Hilfe"
PAGES = [PAGE_START, PAGE_MARKET, PAGE_TRADES, PAGE_RESEARCH, PAGE_HELP]


def go_to(page: str) -> None:
    st.session_state["page"] = page


def choose_start_page(prefs: dict | None, state) -> None:
    """Open the start page, unless this browser asked to skip it. Applied once per session."""
    if "page" not in state:
        state["page"] = PAGE_START
    if prefs is not None and not state.get("start_pref_applied"):
        state["start_pref_applied"] = True
        if prefs.get("skip_start") and state["page"] == PAGE_START:
            state["page"] = PAGE_MARKET


@st.cache_data(ttl=600, show_spinner=False)
def start_page_summary() -> dict:
    """Small status block for the start page: data date, coverage, best stocks, depot values."""
    history = load_signal_snapshot_history(DEFAULT_WATCHLIST_NAME)
    summary: dict = {"day": None, "items": 0, "fresh": 0, "top": [], "depots": {}}
    if history:
        latest = history[-1]
        items = latest.get("items", []) or []
        fresh = snapshot_store.fresh_items(items)
        ranked = sorted((i for i in fresh if i.get("brodel_score_v3") is not None), key=lambda i: -i["brodel_score_v3"])
        summary.update({
            "day": str(latest.get("timestamp", ""))[:10],
            "items": len(items),
            "fresh": len(fresh),
            "top": [{"Aktie": f"{i['symbol']} · {i.get('name', '')}", "Sektor": i.get("sector", ""), "Rang-Score": round(float(i["brodel_score_v3"]), 1)}
                    for i in ranked[:5]],
        })
    state = paper_bot.load_state()
    if state and state.get("equity"):
        summary["depots"] = state["equity"][-1]
    return summary


DEPOT_LABELS = {"bot": "Punkte-Score ab 60", "no_stop": "Punkte-Score ohne Stop-Loss", "rank": "Rang-Score beste 2 %"}


def best_depot(depots: dict) -> tuple[str, float]:
    """Name and value of the best bot depot, the start capital while none has traded yet."""
    values = {key: value for key, value in (depots or {}).items() if key in DEPOT_LABELS and isinstance(value, (int, float))}
    if not values:
        return "noch keine Werte", 100_000.0
    key = max(values, key=values.get)
    return DEPOT_LABELS[key], float(values[key])


def render_start_page(prefs: dict | None) -> None:
    summary = start_page_summary()
    count = f"{summary['items']:,}".replace(",", ".") if summary["items"] else "rund 1.400"
    st.markdown("## Willkommen bei StockWatcher")
    st.markdown(
        f"StockWatcher bewertet **jeden Werktag {count} Aktien** aus Amerika, Europa und Asien. "
        "Dann prüft die Seite mit **Spielgeld**, ob diese Bewertung im echten Börsenverlauf etwas taugt. "
        "Es fließt kein echtes Geld, und nichts hier ist eine Kaufempfehlung."
    )

    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown("#### 1. Daten sammeln")
        st.markdown(
            "Jeden Werktag nach US-Börsenschluss lädt die Seite Kurse, Bilanzkennzahlen, Analystenschätzungen und Insiderkäufe. "
            "Daraus entsteht pro Tag ein **Snapshot**, also ein Foto aller Aktien."
        )
    with col2:
        st.markdown("#### 2. Aktien vergleichen")
        st.markdown(
            "Jede Aktie bekommt zwei Werte:\n\n"
            "- **Rang-Score (0–100):** Wie gut steht die Aktie im Vergleich zu ähnlichen Aktien da? 80 heißt besser als 80 %.\n"
            "- **Punkte-Score (−30 bis 90):** feste Punkte für 11 Signale."
        )
    with col3:
        st.markdown("#### 3. Ehrlich prüfen")
        st.markdown(
            "Drei **Spieldepots** mit je 100.000 € kaufen nach festen Regeln, zwei davon verkaufen per Stop-Loss. "
            "Ein MSCI-World-ETF ist die Messlatte. Erst nach etwa 12 Monaten zeigt sich, ob sich der Aufwand lohnt."
        )

    st.markdown("---")
    st.markdown("#### Stand heute")
    if summary["day"]:
        status = st.columns(4)
        status[0].metric("Datenstand", summary["day"])
        status[1].metric("Aktien mit frischen Daten", f"{summary['fresh']} von {summary['items']}")
        depots = summary.get("depots") or {}
        best_name, best_value = best_depot(depots)
        status[2].metric("Bestes Spieldepot", f"{best_value:,.0f} €".replace(",", "."), help=best_name)
        status[2].caption(best_name)
        status[3].metric("MSCI World ETF", f"{depots.get('etf', 100_000):,.0f} €".replace(",", "."))
        if summary["top"]:
            st.markdown("**Die 5 Aktien mit dem höchsten Rang-Score**")
            st.dataframe(pd.DataFrame(summary["top"]), use_container_width=True, hide_index=True)
    else:
        st.info("Noch keine Daten vorhanden.")

    st.markdown("---")
    st.markdown("#### Wohin als Nächstes?")
    nav = st.columns(4)
    nav[0].button("📊 Marktbeobachtung", on_click=go_to, args=(PAGE_MARKET,), use_container_width=True,
                  help="Alle Aktien mit ihren Scores, Detailansicht je Aktie")
    nav[1].button("💼 Trades", on_click=go_to, args=(PAGE_TRADES,), use_container_width=True,
                  help="Die Spieldepots, ihre Käufe und Verkäufe")
    nav[2].button("🔬 Forschung", on_click=go_to, args=(PAGE_RESEARCH,), use_container_width=True,
                  help="Wahrheitsmaschine, Score-Prüfstand und Backtests")
    nav[3].button("❓ Hilfe", on_click=go_to, args=(PAGE_HELP,), use_container_width=True,
                  help="Wie die Scores genau berechnet werden")

    st.warning(
        "**Keine Anlageberatung.** Die Scores sind ein Werkzeug zum Recherchieren. Ob sie besser sind als ein ETF, ist nicht bewiesen."
    )
    st.checkbox(
        "Diese Startseite beim nächsten Besuch überspringen und direkt zur Marktbeobachtung gehen",
        value=bool(prefs and prefs.get("skip_start")),
        key="skip_start_box",
        help="Wird nur in diesem Browser gespeichert. Die Startseite erreichst du jederzeit über „🏠 Start“.",
    )


def render_app():
    st.title("📈 StockWatcher")
    st.caption("Aktien-Scores und Spieldepots für Aktien aus Amerika, Europa und Asien")

    prefs = visitor_prefs(st.session_state.get("skip_start_box"))
    choose_start_page(prefs, st.session_state)
    page = st.radio("Seite", PAGES, horizontal=True, key="page", label_visibility="collapsed")
    st.markdown("---")

    if page == PAGE_START:
        render_start_page(prefs)
    elif page == PAGE_MARKET:
        render_watchlist_signal_monitor(load_mapping_text())
    elif page == PAGE_TRADES:
        render_bot_tab()
    elif page == PAGE_RESEARCH:
        render_backtest_tab()
    else:
        render_help_tab()


def main():
    render_app()


if __name__ == "__main__":
    main()

from __future__ import annotations

from datetime import datetime
from html import escape
from time import perf_counter

import pandas as pd
import streamlit as st
import duckdb

from fuman_importer import create_fuman_schema, import_fuman_workbook
from supabase_client import (
    fetch_mobile_trade_records,
    fetch_strategy_summary,
    load_config,
)


st.set_page_config(
    page_title="輔滿快訊",
    page_icon="F",
    layout="centered",
    initial_sidebar_state="collapsed",
)

supabase_config = load_config(required=False)


def inject_style(mode: str) -> None:
    if mode == "陽光":
        theme = {
            "scheme": "light",
            "bg": "#f6f8fb",
            "panel": "#ffffff",
            "panel2": "#eef3f8",
            "input": "#ffffff",
            "hero": "linear-gradient(180deg, #ffffff, #f1f6fb)",
            "card": "linear-gradient(180deg, #ffffff, #f8fbff)",
            "mini": "rgba(255, 255, 255, .88)",
            "line": "rgba(15, 23, 42, .13)",
            "line_strong": "rgba(2, 132, 199, .45)",
            "selected": "rgba(14, 165, 233, .13)",
            "text": "#0f172a",
            "muted": "#536175",
            "faint": "#8290a3",
            "reason": "#46566b",
            "cyan": "#0284c7",
            "green": "#059669",
            "red": "#dc2626",
            "gold": "#b7791f",
            "pill_text": "#075985",
            "pill_bg": "rgba(14, 165, 233, .12)",
            "pill_border": "rgba(2, 132, 199, .22)",
        }
    else:
        theme = {
            "scheme": "dark",
            "bg": "#080d16",
            "panel": "#101827",
            "panel2": "#0d1421",
            "input": "#0d1421",
            "hero": "linear-gradient(180deg, rgba(15, 23, 42, .98), rgba(8, 13, 22, .96))",
            "card": "linear-gradient(180deg, rgba(16, 24, 39, .98), rgba(10, 16, 28, .98))",
            "mini": "rgba(15, 23, 42, .72)",
            "line": "rgba(148, 163, 184, .18)",
            "line_strong": "rgba(34, 211, 238, .38)",
            "selected": "rgba(8, 145, 178, .17)",
            "text": "#eef5ff",
            "muted": "#92a1b7",
            "faint": "#64748b",
            "reason": "#a8b3c5",
            "cyan": "#22d3ee",
            "green": "#34d399",
            "red": "#fb7185",
            "gold": "#fbbf24",
            "pill_text": "#bae6fd",
            "pill_bg": "rgba(14, 116, 144, .22)",
            "pill_border": "rgba(34, 211, 238, .25)",
        }

    style_tokens = f"""
        <style>
        :root {{
            color-scheme: {theme["scheme"]};
            --bg: {theme["bg"]};
            --panel: {theme["panel"]};
            --panel-2: {theme["panel2"]};
            --input: {theme["input"]};
            --hero-bg: {theme["hero"]};
            --card-bg: {theme["card"]};
            --mini-bg: {theme["mini"]};
            --line: {theme["line"]};
            --line-strong: {theme["line_strong"]};
            --selected-bg: {theme["selected"]};
            --text: {theme["text"]};
            --muted: {theme["muted"]};
            --faint: {theme["faint"]};
            --reason: {theme["reason"]};
            --cyan: {theme["cyan"]};
            --green: {theme["green"]};
            --red: {theme["red"]};
            --gold: {theme["gold"]};
            --pill-text: {theme["pill_text"]};
            --pill-bg: {theme["pill_bg"]};
            --pill-border: {theme["pill_border"]};
        }}
        """

    st.markdown(
        style_tokens
        + """
        html, body, [data-testid="stAppViewContainer"], [data-testid="stApp"] {
            background: var(--bg);
            color: var(--text);
        }

        [data-testid="stHeader"], [data-testid="stToolbar"],
        [data-testid="stDecoration"], #MainMenu, footer {
            display: none;
        }

        .block-container {
            max-width: 480px;
            padding: 18px 12px 40px;
        }

        .hero {
            border: 1px solid var(--line);
            background: var(--hero-bg);
            border-radius: 0;
            padding: 14px 14px 12px;
            margin-bottom: 10px;
        }

        .hero-top {
            display: flex;
            align-items: baseline;
            justify-content: space-between;
            gap: 12px;
        }

        .title {
            font-size: 21px;
            line-height: 1.1;
            font-weight: 850;
            letter-spacing: 0;
        }

        .live-dot {
            display: inline-block;
            width: 7px;
            height: 7px;
            border-radius: 999px;
            background: var(--green);
            margin-right: 6px;
            box-shadow: 0 0 0 4px rgba(52, 211, 153, .12);
        }

        .sub {
            color: var(--muted);
            font-size: 12px;
            margin-top: 7px;
        }

        .metric-grid {
            display: grid;
            grid-template-columns: repeat(3, minmax(0, 1fr));
            gap: 8px;
            margin-top: 13px;
        }

        .mini {
            border: 1px solid var(--line);
            background: var(--mini-bg);
            padding: 9px 8px;
        }

        .mini-label {
            color: var(--faint);
            font-size: 11px;
            line-height: 1;
        }

        .mini-value {
            color: var(--text);
            font-size: 17px;
            font-weight: 800;
            margin-top: 5px;
            line-height: 1;
        }

        .stRadio [role="radiogroup"] {
            display: flex;
            gap: 8px;
            overflow-x: auto;
            padding: 2px 0 8px;
            flex-wrap: nowrap;
        }

        .stRadio label {
            flex: 0 0 auto;
            border: 1px solid var(--line);
            background: var(--panel-2);
            padding: 8px 10px;
            min-height: 38px;
        }

        .stRadio label:has(input:checked) {
            border-color: var(--line-strong);
            background: var(--selected-bg);
        }

        .stRadio label p {
            color: var(--text);
            font-size: 13px;
            white-space: nowrap;
        }

        .stTextInput input {
            background: var(--input);
            border: 1px solid var(--line);
            color: var(--text);
            border-radius: 0;
            min-height: 42px;
        }

        .stButton > button {
            background: var(--input);
            color: var(--text);
            border: 1px solid var(--line);
            border-radius: 0;
            min-height: 38px;
        }

        .section-title {
            color: var(--muted);
            font-size: 12px;
            font-weight: 700;
            margin: 14px 0 8px;
            letter-spacing: 0;
        }

        .signal-card {
            border: 1px solid var(--line);
            background: var(--card-bg);
            padding: 12px;
            margin: 8px 0;
        }

        .signal-head {
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
            gap: 10px;
        }

        .stock-name {
            font-size: 18px;
            line-height: 1.15;
            font-weight: 850;
            color: var(--text);
        }

        .stock-meta {
            color: var(--muted);
            font-size: 12px;
            margin-top: 4px;
            line-height: 1.35;
        }

        .pnl {
            font-size: 18px;
            font-weight: 850;
            text-align: right;
            line-height: 1.1;
        }

        .pnl-pos { color: var(--red); }
        .pnl-neg { color: var(--green); }
        .pnl-flat { color: var(--muted); }

        .pill-row {
            display: flex;
            gap: 6px;
            flex-wrap: wrap;
            margin-top: 10px;
        }

        .pill {
            color: var(--pill-text);
            background: var(--pill-bg);
            border: 1px solid var(--pill-border);
            font-size: 11px;
            line-height: 1;
            padding: 6px 7px;
        }

        .reason {
            color: var(--reason);
            font-size: 12px;
            line-height: 1.55;
            margin-top: 9px;
        }

        .empty {
            border: 1px solid var(--line);
            color: var(--muted);
            padding: 18px 12px;
            background: var(--panel);
            font-size: 14px;
        }

        [data-testid="stExpander"] {
            border: 1px solid var(--line);
            background: var(--input);
            border-radius: 0;
        }

        [data-testid="stExpander"] summary p {
            color: var(--muted);
            font-size: 12px;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


@st.cache_data(ttl=20, show_spinner=False)
def load_local_bundle() -> tuple[pd.DataFrame, pd.DataFrame]:
    con = duckdb.connect(":memory:")
    create_fuman_schema(con)
    import_fuman_workbook(con)
    summary = con.execute("select * from fuman_scorecard_daily").df()
    records = con.execute(
        """
        select
            record_date,
            strategy,
            ticker,
            name,
            entry_time,
            entry_price,
            high_price,
            pnl,
            source_sheet,
            reason
        from fuman_trade_records
        order by try_strptime(record_date, '%Y-%m-%d') desc nulls last,
                 pnl desc nulls last,
                 strategy,
                 ticker
        """
    ).df()
    return summary, records


@st.cache_data(ttl=20, show_spinner=False)
def load_summary() -> pd.DataFrame:
    if supabase_config:
        summary = fetch_strategy_summary(supabase_config, days=30)
        if not summary.empty:
            summary = summary.sort_values(["summary_date", "strategy"], ascending=[False, True])
            return summary.drop_duplicates("strategy", keep="first")
        return summary

    summary, _ = load_local_bundle()
    return summary


@st.cache_data(ttl=20, show_spinner=False)
def load_records(strategy: str | None, limit: int) -> pd.DataFrame:
    if supabase_config:
        records = fetch_mobile_trade_records(supabase_config, strategy=strategy, limit=limit)
        if not records.empty:
            records = records.rename(columns={"source": "source_sheet"})
        return records

    _, records = load_local_bundle()
    if strategy:
        records = records[records["strategy"] == strategy].copy()
    return records.head(limit).copy()


def latest_only(records: pd.DataFrame) -> pd.DataFrame:
    if records.empty:
        return records
    frame = records.copy()
    frame["record_date"] = frame["record_date"].astype(str)
    latest_date = frame["record_date"].max()
    return frame[frame["record_date"] == latest_date].copy()


def strategy_options(summary: pd.DataFrame, records: pd.DataFrame) -> list[str]:
    names: list[str] = ["全策略"]
    if not summary.empty and "strategy" in summary:
        names.extend(summary["strategy"].dropna().astype(str).tolist())
    if not records.empty:
        names.extend(records["strategy"].dropna().astype(str).unique().tolist())
    cleaned = [
        name
        for name in dict.fromkeys(names)
        if name == "全策略" or "成績單" in name
    ]
    return cleaned


def strategy_label(value: str) -> str:
    if value == "全策略":
        return value
    return value.replace("成績單", "")


def summarize(frame: pd.DataFrame) -> dict[str, float]:
    if frame.empty:
        return {"rows": 0, "wins": 0, "win_rate": 0, "pnl": 0}
    pnl = pd.to_numeric(frame["pnl"], errors="coerce").fillna(0)
    rows = len(frame)
    wins = int((pnl > 0).sum())
    return {
        "rows": rows,
        "wins": wins,
        "win_rate": wins / rows * 100 if rows else 0,
        "pnl": float(pnl.sum()),
    }


def format_number(value: object, decimals: int = 2) -> str:
    if pd.isna(value):
        return "--"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "--"
    if decimals == 0:
        return f"{number:,.0f}"
    return f"{number:,.{decimals}f}"


def short_reason(value: object, max_len: int = 58) -> str:
    text = "" if pd.isna(value) else str(value).strip()
    if not text:
        return "尚無理由說明"
    return text if len(text) <= max_len else text[:max_len] + "..."


def render_hero(stats: dict[str, float], elapsed_ms: float, latest_date: str) -> None:
    source = "Supabase" if supabase_config else "本機"
    now_text = datetime.now().strftime("%H:%M")
    st.markdown(
        f"""
        <div class="hero">
          <div class="hero-top">
            <div>
              <div class="title"><span class="live-dot"></span>輔滿快訊</div>
              <div class="sub">{escape(latest_date)} · {now_text} 更新 · {elapsed_ms:.0f}ms · {source}</div>
            </div>
          </div>
          <div class="metric-grid">
            <div class="mini">
              <div class="mini-label">訊號</div>
              <div class="mini-value">{stats["rows"]:,.0f}</div>
            </div>
            <div class="mini">
              <div class="mini-label">勝率</div>
              <div class="mini-value">{stats["win_rate"]:.1f}%</div>
            </div>
            <div class="mini">
              <div class="mini-label">損益</div>
              <div class="mini-value">{stats["pnl"]:,.0f}</div>
            </div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_card(row: pd.Series) -> None:
    pnl = pd.to_numeric(pd.Series([row.get("pnl")]), errors="coerce").fillna(0).iloc[0]
    pnl_class = "pnl-pos" if pnl > 0 else "pnl-neg" if pnl < 0 else "pnl-flat"
    name = escape(str(row.get("name") or row.get("ticker") or "--"))
    ticker = escape(str(row.get("ticker") or "--"))
    strategy = escape(str(row.get("strategy") or "--"))
    entry_time = escape(str(row.get("entry_time") or "--"))
    entry_price = format_number(row.get("entry_price"))
    high_price = format_number(row.get("high_price"))
    reason = escape(short_reason(row.get("reason")))

    st.markdown(
        f"""
        <div class="signal-card">
          <div class="signal-head">
            <div>
              <div class="stock-name">{name}</div>
              <div class="stock-meta">{ticker} · {entry_time}</div>
            </div>
            <div class="pnl {pnl_class}">{format_number(pnl, 0)}</div>
          </div>
          <div class="pill-row">
            <span class="pill">{strategy}</span>
            <span class="pill">進 {entry_price}</span>
            <span class="pill">高 {high_price}</span>
          </div>
          <div class="reason">{reason}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def main() -> None:
    if "theme_mode" not in st.session_state:
        st.session_state.theme_mode = "夜幕"
    inject_style(st.session_state.theme_mode)

    start = perf_counter()
    summary = load_summary()
    first_records = load_records(strategy=None, limit=500)
    hero_slot = st.empty()
    options = strategy_options(summary, first_records)

    selected = st.radio(
        "策略",
        options,
        horizontal=True,
        label_visibility="collapsed",
        format_func=strategy_label,
    )
    selected_strategy = None if selected == "全策略" else selected
    limit = st.radio("筆數", [20, 40, 80], horizontal=True, index=0, label_visibility="collapsed")

    records = first_records if selected_strategy is None else load_records(selected_strategy, limit=500)
    records = latest_only(records)

    query = st.text_input("搜尋代號 / 名稱", placeholder="搜尋台股代號或名稱", label_visibility="collapsed")
    if query.strip() and not records.empty:
        q = query.strip()
        records = records[
            records["ticker"].astype(str).str.contains(q, case=False, na=False)
            | records["name"].astype(str).str.contains(q, case=False, na=False)
        ].copy()

    records = records.head(int(limit))
    latest_date = "--" if records.empty else str(records["record_date"].max())
    elapsed_ms = (perf_counter() - start) * 1000

    with hero_slot.container():
        render_hero(summarize(records), elapsed_ms, latest_date)

    st.radio("外觀", ["夜幕", "陽光"], horizontal=True, key="theme_mode", label_visibility="collapsed")

    if st.button("刷新", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

    st.markdown('<div class="section-title">最新訊號</div>', unsafe_allow_html=True)

    if records.empty:
        st.markdown('<div class="empty">目前沒有符合條件的訊號。</div>', unsafe_allow_html=True)
        return

    for _, row in records.iterrows():
        render_card(row)
        full_reason = "" if pd.isna(row.get("reason")) else str(row.get("reason")).strip()
        if full_reason and len(full_reason) > 58:
            with st.expander("完整理由"):
                st.write(full_reason)


if __name__ == "__main__":
    main()

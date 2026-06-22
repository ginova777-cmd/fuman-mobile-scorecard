from __future__ import annotations

import json
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from time import perf_counter
from urllib.error import URLError
from urllib.request import Request, urlopen

import streamlit as st


TERMINAL_BOOT_URL = "https://fuman-terminal.vercel.app/api/mobile-boot"
LOCAL_BOOT_FILES = [
    Path(r"C:\fuman-terminal\data\mobile-terminal-latest.json"),
    Path(r"C:\fuman-terminal\data\terminal-home-mobile-slim.json"),
]


st.set_page_config(
    page_title="輔滿終端",
    page_icon="F",
    layout="centered",
    initial_sidebar_state="collapsed",
)


def main() -> None:
    start = perf_counter()
    payload, source, error = load_terminal_payload()
    elapsed_ms = (perf_counter() - start) * 1000
    inject_style()

    if not payload:
        render_empty(error)
        return

    model = normalize_payload(payload)
    render_header(model, source, elapsed_ms)

    view = st.radio(
        "view",
        ["快訊", "策略", "籌碼", "權證", "個股"],
        horizontal=True,
        label_visibility="collapsed",
    )

    query = st.text_input("search", placeholder="搜尋代號或名稱", label_visibility="collapsed")

    if view == "快訊":
        render_brief(model, query)
    elif view == "策略":
        render_strategy(model, query)
    elif view == "籌碼":
        render_list("籌碼買超", model["chip"], query, mode="chip")
    elif view == "權證":
        render_list("權證熱度", model["warrant"], query, mode="warrant")
    else:
        render_list("成交熱點", model["stocks"], query, mode="stock")


@st.cache_data(ttl=20, show_spinner=False)
def load_terminal_payload() -> tuple[dict, str, str]:
    try:
        request = Request(
            TERMINAL_BOOT_URL,
            headers={
                "Accept": "application/json",
                "User-Agent": "fuman-streamlit-mobile-terminal/1.0",
                "Cache-Control": "no-store",
            },
        )
        with urlopen(request, timeout=4) as response:
            raw = response.read().decode("utf-8")
        return json.loads(raw), "終端 API", ""
    except (OSError, URLError, TimeoutError, json.JSONDecodeError) as exc:
        for file in LOCAL_BOOT_FILES:
            if not file.exists():
                continue
            try:
                return json.loads(file.read_text(encoding="utf-8")), "本機快取", ""
            except (OSError, json.JSONDecodeError):
                continue
        return {}, "", str(exc)


def normalize_payload(payload: dict) -> dict:
    mobile = as_dict(payload.get("mobile"))
    market = as_dict(mobile.get("market") or payload.get("market"))
    ai_panel = as_dict(payload.get("aiPanel") or mobile.get("aiPanel"))
    strategies = as_dict(payload.get("strategies") or mobile.get("strategies"))
    stocks = as_dict(payload.get("stocks") or mobile.get("stocks"))

    strategy4 = rows_from(strategies.get("strategy4"), keys=("top", "rows", "items"))
    strategy5 = rows_from(strategies.get("strategy5"), keys=("top", "rows", "items"))
    if not strategy5:
        strategy5 = rows_from(payload.get("strategy5"), keys=("top", "rows", "items"))

    return {
        "updated_at": first_text(
            payload.get("updatedAt"),
            mobile.get("updatedAt"),
            market.get("updatedAt"),
            payload.get("servedAt"),
        ),
        "market": market,
        "ai_panel": ai_panel,
        "strong_sectors": list_from(market.get("strongSectors") or ai_panel.get("strongSectors")),
        "weak_sectors": list_from(market.get("weakSectors") or ai_panel.get("weakSectors")),
        "priority": list_from(ai_panel.get("priorityStocks")),
        "risk": list_from(ai_panel.get("riskStocks")),
        "strategy4": strategy4,
        "strategy5": strategy5,
        "chip": rows_from(mobile.get("chip") or payload.get("institution"), keys=("top", "rows", "items")),
        "warrant": rows_from(mobile.get("warrant") or payload.get("warrant"), keys=("top", "rows", "items")),
        "stocks": rows_from(stocks, keys=("top", "rows", "items")),
        "status": as_dict(payload.get("status") or mobile.get("status")),
    }


def inject_style() -> None:
    st.markdown(
        """
        <style>
        :root {
          color-scheme: dark;
          --bg: #070b12;
          --panel: #0f1724;
          --panel2: #121c2b;
          --line: rgba(148, 163, 184, .18);
          --line2: rgba(56, 189, 248, .26);
          --text: #edf4ff;
          --muted: #94a3b8;
          --faint: #64748b;
          --green: #35d399;
          --red: #fb7185;
          --cyan: #22d3ee;
          --gold: #fbbf24;
        }
        html, body, [data-testid="stAppViewContainer"], [data-testid="stApp"] {
          background: radial-gradient(circle at top left, rgba(34,211,238,.09), transparent 30%), var(--bg);
          color: var(--text);
        }
        [data-testid="stHeader"], [data-testid="stToolbar"], [data-testid="stDecoration"],
        #MainMenu, footer { display: none; }
        .block-container { max-width: 520px; padding: 14px 12px 34px; }
        .hero, .section, .card {
          border: 1px solid var(--line);
          background: linear-gradient(180deg, rgba(15,23,36,.96), rgba(9,14,23,.96));
        }
        .hero { padding: 14px; margin-bottom: 10px; }
        .brand { display:flex; justify-content:space-between; align-items:flex-start; gap:10px; }
        .title { font-size: 22px; font-weight: 900; line-height: 1.05; letter-spacing: 0; }
        .live { width:8px; height:8px; border-radius:99px; display:inline-block; background:var(--green); margin-right:7px; box-shadow:0 0 0 5px rgba(53,211,153,.10); }
        .sub { color: var(--muted); font-size: 12px; margin-top: 7px; }
        .badge { border:1px solid var(--line2); color:#bff5ff; padding:5px 8px; font-size:12px; background:rgba(14,116,144,.17); white-space:nowrap; }
        .metrics { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:8px; margin-top:12px; }
        .metric { background:rgba(15,23,42,.74); border:1px solid var(--line); padding:9px 8px; min-height:58px; }
        .k { color:var(--faint); font-size:11px; }
        .v { color:var(--text); font-size:18px; font-weight:850; margin-top:4px; }
        .section { padding: 12px; margin: 12px 0 9px; }
        .section-title { font-size:14px; color:#cfe7ff; font-weight:850; margin-bottom:8px; }
        .card { padding: 12px; margin: 8px 0; }
        .rowtop { display:flex; justify-content:space-between; gap:10px; align-items:flex-start; }
        .name { font-size:18px; font-weight:900; color:var(--text); }
        .code { color:var(--muted); font-size:12px; margin-top:3px; }
        .price { text-align:right; font-size:16px; font-weight:850; }
        .up { color:var(--red); }
        .down { color:var(--green); }
        .flat { color:var(--muted); }
        .tags { display:flex; flex-wrap:wrap; gap:6px; margin-top:9px; }
        .tag { border:1px solid rgba(148,163,184,.18); background:rgba(15,23,42,.76); color:#cbd5e1; padding:4px 7px; font-size:12px; }
        .reason { color:#aebbd0; font-size:13px; line-height:1.45; margin-top:8px; }
        .empty { color:var(--muted); border:1px solid var(--line); background:rgba(15,23,42,.58); padding:16px; }
        .stRadio [role="radiogroup"] { display:flex; gap:8px; overflow-x:auto; padding:2px 0 8px; flex-wrap:nowrap; }
        .stRadio label { flex:0 0 auto; border:1px solid var(--line); background:var(--panel2); min-height:39px; padding:8px 10px; }
        .stRadio label:has(input:checked) { border-color:var(--line2); background:rgba(8,145,178,.18); }
        .stRadio label p { color:var(--text); font-size:13px; white-space:nowrap; }
        .stTextInput input {
          background:#0d1421; border:1px solid rgba(148,163,184,.24); color:var(--text);
          min-height:42px; border-radius:0;
        }
        .stTextInput input::placeholder { color:#526072; }
        div[data-testid="stVerticalBlock"] { gap: .45rem; }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_header(model: dict, source: str, elapsed_ms: float) -> None:
    market = model["market"]
    updated = format_time(model["updated_at"])
    up = number(market.get("up"))
    down = number(market.get("down"))
    sample = number(market.get("sample"))
    bias = as_dict(model["ai_panel"].get("summary")).get("bias") or "即時觀察"
    st.markdown(
        f"""
        <div class="hero">
          <div class="brand">
            <div>
              <div class="title"><span class="live"></span>輔滿終端</div>
              <div class="sub">{escape(updated)} 更新 · {elapsed_ms:.0f}ms · {escape(source)}</div>
            </div>
            <div class="badge">{escape(str(bias))}</div>
          </div>
          <div class="metrics">
            <div class="metric"><div class="k">樣本</div><div class="v">{sample}</div></div>
            <div class="metric"><div class="k">上漲</div><div class="v up">{up}</div></div>
            <div class="metric"><div class="k">下跌</div><div class="v down">{down}</div></div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_brief(model: dict, query: str) -> None:
    render_sector_section("強勢族群", model["strong_sectors"], positive=True)
    render_sector_section("弱勢族群", model["weak_sectors"], positive=False)
    priority = model["priority"] or model["risk"][:8]
    render_list("終端快訊", priority, query, mode="stock")


def render_strategy(model: dict, query: str) -> None:
    render_list("策略4 波段", model["strategy4"], query, mode="strategy")
    render_list("策略5 綜合", model["strategy5"], query, mode="strategy")


def render_sector_section(title: str, rows: list[dict], positive: bool) -> None:
    if not rows:
        return
    st.markdown(f'<div class="section"><div class="section-title">{escape(title)}</div>', unsafe_allow_html=True)
    for row in rows[:5]:
        name = escape(str(row.get("name") or "--"))
        up = number(row.get("up"))
        down = number(row.get("down"))
        pct = row.get("pct")
        if pct is None:
            pct = round(float(row.get("breadth") or 0) * 100, 1)
        tone = "up" if positive else "down"
        st.markdown(
            f"""
            <div class="card">
              <div class="rowtop">
                <div><div class="name">{name}</div><div class="code">上漲 {up} · 下跌 {down}</div></div>
                <div class="price {tone}">{escape(str(pct))}%</div>
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    st.markdown("</div>", unsafe_allow_html=True)


def render_list(title: str, rows: list[dict], query: str, mode: str) -> None:
    filtered = filter_rows(rows, query)
    st.markdown(f'<div class="section"><div class="section-title">{escape(title)} · {len(filtered)}</div>', unsafe_allow_html=True)
    if not filtered:
        st.markdown('<div class="empty">目前沒有符合條件的訊號。</div>', unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)
        return
    for row in filtered[:30]:
        render_card(row, mode)
    st.markdown("</div>", unsafe_allow_html=True)


def render_card(row: dict, mode: str) -> None:
    code = first_text(row.get("code"), row.get("underlyingCode"), row.get("ticker"))
    name = first_text(row.get("name"), row.get("underlyingName"), code, "--")
    close = row.get("close") or row.get("underlyingClose") or row.get("displayClose")
    percent = row.get("percent") or row.get("underlyingPercent") or row.get("displayPercent")
    tone = pct_class(percent)
    right = price_text(close, percent)
    tags = tags_for(row, mode)
    reason = first_text(row.get("reason"), row.get("strategy4Reason"), row.get("actionLabel"), "")
    st.markdown(
        f"""
        <div class="card">
          <div class="rowtop">
            <div>
              <div class="name">{escape(str(name))}</div>
              <div class="code">{escape(str(code))}</div>
            </div>
            <div class="price {tone}">{right}</div>
          </div>
          {render_tags(tags)}
          {f'<div class="reason">{escape(str(reason))}</div>' if reason else ''}
        </div>
        """,
        unsafe_allow_html=True,
    )


def tags_for(row: dict, mode: str) -> list[str]:
    tags: list[str] = []
    if mode == "chip":
        tags.extend([f"合計 {compact(row.get('total'))}", f"外資 {compact(row.get('foreign'))}", f"投信 {compact(row.get('trust'))}"])
    elif mode == "warrant":
        tags.extend([first_text(row.get("signalGrade"), "權證"), first_text(row.get("stockSetupLabel"), ""), f"分數 {compact(row.get('finalScore') or row.get('score'))}"])
    elif mode == "strategy":
        if row.get("swingZone"):
            tags.append(f"區 {row.get('swingZone')}")
        if row.get("score") is not None:
            tags.append(f"分數 {compact(row.get('score'))}")
        for signal in list_from(row.get("swingSignals") or row.get("matches"))[:3]:
            tags.append(first_text(signal.get("short"), signal.get("title"), signal.get("id")))
    else:
        if row.get("value"):
            tags.append(f"成交 {compact(row.get('value'))}")
        if row.get("tradeVolume"):
            tags.append(f"量 {compact(row.get('tradeVolume'))}")
        for tag in list_from(row.get("tags"))[:3]:
            tags.append(str(tag))
    return [tag for tag in tags if tag and tag != "--"]


def render_tags(tags: list[str]) -> str:
    if not tags:
        return ""
    return '<div class="tags">' + "".join(f'<span class="tag">{escape(str(tag))}</span>' for tag in tags[:5]) + "</div>"


def render_empty(error: str) -> None:
    st.markdown(
        f"""
        <div class="hero">
          <div class="title">輔滿終端</div>
          <div class="sub">資料暫時讀不到</div>
        </div>
        <div class="empty">{escape(error or "請稍後刷新。")}</div>
        """,
        unsafe_allow_html=True,
    )


def filter_rows(rows: list[dict], query: str) -> list[dict]:
    q = str(query or "").strip().lower()
    if not q:
        return rows
    result = []
    for row in rows:
        haystack = " ".join(str(row.get(key, "")) for key in ("code", "ticker", "name", "underlyingCode", "underlyingName")).lower()
        if q in haystack:
            result.append(row)
    return result


def rows_from(value: object, keys: tuple[str, ...]) -> list[dict]:
    value = as_dict(value)
    for key in keys:
        rows = list_from(value.get(key))
        if rows:
            return rows
    return []


def list_from(value: object) -> list[dict]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    return []


def as_dict(value: object) -> dict:
    return value if isinstance(value, dict) else {}


def first_text(*values: object) -> str:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def number(value: object) -> str:
    try:
        return f"{float(value):,.0f}"
    except (TypeError, ValueError):
        return "0"


def compact(value: object) -> str:
    try:
        num = float(value)
    except (TypeError, ValueError):
        return "--"
    sign = "-" if num < 0 else ""
    num = abs(num)
    if num >= 100_000_000:
        return f"{sign}{num / 100_000_000:.1f}億"
    if num >= 10_000:
        return f"{sign}{num / 10_000:.1f}萬"
    return f"{sign}{num:,.0f}"


def price_text(close: object, percent: object) -> str:
    close_text = "--" if close is None else compact(close)
    try:
        pct = float(percent)
        return f"{escape(close_text)}<br>{pct:+.2f}%"
    except (TypeError, ValueError):
        return escape(close_text)


def pct_class(percent: object) -> str:
    try:
        pct = float(percent)
    except (TypeError, ValueError):
        return "flat"
    if pct > 0:
        return "up"
    if pct < 0:
        return "down"
    return "flat"


def format_time(value: str) -> str:
    if not value:
        return "--"
    text = str(value)
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if dt.tzinfo:
            dt = dt.astimezone(timezone.utc)
        return dt.strftime("%m-%d %H:%M")
    except ValueError:
        return text[:16]


if __name__ == "__main__":
    main()

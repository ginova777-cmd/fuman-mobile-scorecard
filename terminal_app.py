from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, wait
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from time import perf_counter
from urllib.error import URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

import streamlit as st


TERMINAL_BOOT_URL = "https://fuman-terminal.vercel.app/api/mobile-boot"
TERMINAL_API_BASE = "https://fuman-terminal.vercel.app/api"
BOOT_TIMEOUT_SECONDS = 2.5
ENDPOINT_TIMEOUT_SECONDS = 1.8
ENDPOINT_TOTAL_WAIT_SECONDS = 3.4
DATA_CACHE_VERSION = "terminal-chip-cb-v2"
ENDPOINT_TIMEOUT_BY_KEY = {
    "cb": 2.8,
    "institution": 3.2,
    "strategy4": 3.2,
    "strategy5": 3.2,
    "warrant": 0.8,
}
TERMINAL_ENDPOINTS = {
    "strategy1": "open-buy-latest",
    "strategy2": "strategy2-latest",
    "strategy3": "strategy3-latest",
    "strategy4": "strategy4-latest",
    "strategy5": "strategy5-latest",
    "radar": "realtime-radar-latest",
    "institution": "institution-latest",
    "warrant": "warrant-flow-latest",
    "cb": "cb-detect-latest",
}
LOCAL_BOOT_FILES = [
    Path(r"C:\fuman-terminal\data\mobile-terminal-latest.json"),
    Path(r"C:\fuman-terminal\data\terminal-home-mobile-slim.json"),
]
LOCAL_DATA_DIRS = [
    Path(r"C:\fuman-terminal\data"),
    Path(r"C:\fuman-terminal-sync\data"),
]


st.set_page_config(
    page_title="輔滿終端",
    page_icon="F",
    layout="centered",
    initial_sidebar_state="collapsed",
)


def main() -> None:
    init_state()
    start = perf_counter()
    payload, source, error = load_terminal_payload(DATA_CACHE_VERSION)
    elapsed_ms = (perf_counter() - start) * 1000
    inject_style(st.session_state.theme)

    if not payload:
        render_empty(error)
        return

    model = normalize_payload(payload)
    render_header(model, source, elapsed_ms)

    query = st.text_input("search", placeholder="搜尋代號或名稱", label_visibility="collapsed")
    render_search_picker(model, query)
    group = st.radio(
        "group",
        ["快訊", "策略", "籌碼"],
        horizontal=True,
        label_visibility="collapsed",
    )
    if group == "策略":
        view = st.radio(
            "strategy-view",
            ["全策略", "策略1", "策略2", "策略3", "策略4", "策略5", "雷達"],
            horizontal=True,
            label_visibility="collapsed",
        )
    elif group == "籌碼":
        view = st.radio(
            "chip-view",
            ["買賣超", "權證", "CB", "自選股"],
            horizontal=True,
            label_visibility="collapsed",
        )
    else:
        view = "快訊"

    if view == "快訊":
        render_brief(model, "")
    elif view == "全策略":
        render_strategy(model, "")
    elif view == "策略1":
        render_list("策略1 明日開盤入", model["strategy1"], "", mode="strategy")
    elif view == "策略2":
        render_list("策略2 A區進場", model["strategy2"], "", mode="strategy")
    elif view == "策略3":
        render_list("策略3 資金快篩", model["strategy3"], "", mode="strategy")
    elif view == "策略4":
        render_strategy4_page(model["strategy4"], "")
    elif view == "策略5":
        render_strategy5_page(model["strategy5"], "")
    elif view == "雷達":
        render_list("即時雷達", model["radar"], "", mode="strategy")
    elif view == "買賣超":
        render_chip_strategy_page(model["chip"], "")
    elif view == "權證":
        render_list("權證熱度", model["warrant"], "", mode="warrant")
    elif view == "CB":
        render_list("CB 名單", model["cb"], "", mode="strategy")
    else:
        render_watchlist(model, query)


def init_state() -> None:
    if "watchlist_codes" not in st.session_state:
        st.session_state.watchlist_codes = []
    query_theme = first_query_value("theme")
    if query_theme in ("夜幕", "陽光"):
        st.session_state.theme = query_theme
    elif "theme" not in st.session_state:
        st.session_state.theme = "夜幕"
    selected = first_query_value("selected_stock")
    if selected:
        st.session_state.selected_stock_code = selected
    elif "selected_stock_code" not in st.session_state:
        st.session_state.selected_stock_code = ""


@st.cache_data(ttl=8, show_spinner=False)
def load_terminal_payload(cache_version: str) -> tuple[dict, str, str]:
    payload, api_payloads, boot_error = fetch_terminal_bundle()

    if not payload and api_payloads:
        payload = {
            "ok": True,
            "updatedAt": latest_updated_at(api_payloads),
            "aiPanel": {"summary": {"bias": "API 快取"}},
            "market": {"sample": total_api_rows(api_payloads), "up": 0, "down": 0},
        }

    if not payload:
        return {}, "", f"連不到電腦終端 API：{boot_error or '沒有任何策略 API 回應'}"

    payload["_api"] = api_payloads
    source = "電腦終端 API" if not boot_error else "電腦終端 API 快速模式"
    return payload, source, ""


def fetch_terminal_bundle() -> tuple[dict, dict[str, dict], str]:
    payload: dict = {}
    api_payloads: dict[str, dict] = {}
    boot_error = ""
    executor = ThreadPoolExecutor(max_workers=len(TERMINAL_ENDPOINTS) + 1)
    try:
        futures = {
            executor.submit(fetch_json, TERMINAL_BOOT_URL, BOOT_TIMEOUT_SECONDS): "boot",
            **{
                executor.submit(fetch_json, f"{TERMINAL_API_BASE}/{endpoint}", endpoint_timeout(key)): key
                for key, endpoint in TERMINAL_ENDPOINTS.items()
            },
        }
        done, pending = wait(futures, timeout=ENDPOINT_TOTAL_WAIT_SECONDS)
        for future in pending:
            future.cancel()
        for future in done:
            key = futures[future]
            try:
                result = future.result()
            except (OSError, URLError, TimeoutError, json.JSONDecodeError) as exc:
                if key == "boot":
                    boot_error = str(exc)
                continue
            if not isinstance(result, dict):
                continue
            if key == "boot":
                payload = result
            else:
                api_payloads[key] = result
    finally:
        executor.shutdown(wait=False, cancel_futures=True)
    if not payload and not boot_error:
        boot_error = "boot API 逾時"
    return payload, api_payloads, boot_error


def fetch_terminal_apis() -> dict[str, dict]:
    payloads: dict[str, dict] = {}
    executor = ThreadPoolExecutor(max_workers=6)
    try:
        futures = {
            executor.submit(fetch_json, f"{TERMINAL_API_BASE}/{endpoint}", endpoint_timeout(key)): key
            for key, endpoint in TERMINAL_ENDPOINTS.items()
        }
        done, pending = wait(futures, timeout=ENDPOINT_TOTAL_WAIT_SECONDS)
        for future in pending:
            future.cancel()
        for future in done:
            key = futures[future]
            try:
                payload = future.result()
            except Exception:
                payload = {}
            if isinstance(payload, dict):
                payloads[key] = payload
    finally:
        executor.shutdown(wait=False, cancel_futures=True)
    return payloads


def endpoint_timeout(key: str) -> float:
    return ENDPOINT_TIMEOUT_BY_KEY.get(key, ENDPOINT_TIMEOUT_SECONDS)


def fetch_json(url: str, timeout: int | float = 4) -> dict:
    request = Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "fuman-streamlit-mobile-terminal/1.0",
            "Cache-Control": "no-store",
        },
    )
    with urlopen(request, timeout=timeout) as response:
        raw = response.read().decode("utf-8")
    payload = json.loads(raw)
    return payload if isinstance(payload, dict) else {}


def total_api_rows(api_payloads: dict[str, dict]) -> int:
    return sum(len(api_rows(payload)) for payload in api_payloads.values())


def latest_updated_at(api_payloads: dict[str, dict]) -> str:
    values = [
        first_text(payload.get("updatedAt"), payload.get("generatedAt"), payload.get("timestamp"), payload.get("date"))
        for payload in api_payloads.values()
        if isinstance(payload, dict)
    ]
    values = [value for value in values if value]
    return max(values) if values else datetime.now(timezone.utc).isoformat()


def normalize_payload(payload: dict) -> dict:
    mobile = as_dict(payload.get("mobile"))
    api = as_dict(payload.get("_api"))
    market = as_dict(mobile.get("market") or payload.get("market"))
    ai_panel = as_dict(payload.get("aiPanel") or mobile.get("aiPanel"))
    strategies = as_dict(payload.get("strategies") or mobile.get("strategies"))
    stocks = as_dict(payload.get("stocks") or mobile.get("stocks"))

    strategy1 = api_rows(api.get("strategy1"), fallback=strategies.get("openBuy"))
    strategy2 = api_rows(api.get("strategy2"), fallback=mobile.get("strategy2") or strategies.get("strategy2"))
    strategy3 = api_rows(api.get("strategy3"), fallback=strategies.get("strategy3"))
    strategy4 = api_rows(api.get("strategy4"), fallback=strategies.get("strategy4"))
    strategy5 = api_rows(api.get("strategy5"), fallback=strategies.get("strategy5") or payload.get("strategy5"))
    radar = api_rows(api.get("radar"), fallback=payload.get("radar") or mobile.get("radar"))
    cb = api_rows(api.get("cb"), fallback=payload.get("cb") or mobile.get("cb"))
    warrant = api_rows(api.get("warrant"), fallback=mobile.get("warrant") or payload.get("warrant"))
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
        "strategy1": strategy1,
        "strategy2": strategy2,
        "strategy3": strategy3,
        "strategy4": strategy4,
        "strategy5": strategy5,
        "radar": radar,
        "cb": cb,
        "chip": api_rows(api.get("institution"), fallback=mobile.get("chip") or payload.get("institution")),
        "warrant": warrant,
        "stocks": rows_from(stocks, keys=("top", "rows", "items")),
        "status": as_dict(payload.get("status") or mobile.get("status")),
    }


def inject_style(theme: str = "夜幕") -> None:
    if theme == "陽光":
        palette = {
            "scheme": "light",
            "bg": "#f6f8fb",
            "panel": "#ffffff",
            "panel2": "#eef3f8",
            "line": "rgba(15, 23, 42, .14)",
            "line2": "rgba(249, 115, 22, .34)",
            "text": "#0f172a",
            "muted": "#475569",
            "faint": "#64748b",
            "green": "#059669",
            "red": "#e11d48",
            "cyan": "#0284c7",
            "gold": "#b45309",
            "orange": "#f97316",
            "app_bg": "linear-gradient(180deg, #fff7ed 0%, #f6f8fb 42%, #eef3f8 100%)",
            "panel_bg": "linear-gradient(180deg, rgba(255,255,255,.98), rgba(239,246,255,.96))",
            "metric_bg": "rgba(248,250,252,.92)",
            "tag_bg": "rgba(241,245,249,.92)",
            "input_bg": "#ffffff",
            "placeholder": "#94a3b8",
            "active_bg": "rgba(249,115,22,.12)",
            "active_text": "#9a3412",
            "badge_text": "#0f172a",
            "badge_bg": "rgba(255,237,213,.78)",
        }
    else:
        palette = {
            "scheme": "dark",
            "bg": "#070b12",
            "panel": "#0f1724",
            "panel2": "#121c2b",
            "line": "rgba(148, 163, 184, .18)",
            "line2": "rgba(56, 189, 248, .26)",
            "text": "#edf4ff",
            "muted": "#94a3b8",
            "faint": "#64748b",
            "green": "#35d399",
            "red": "#fb7185",
            "cyan": "#22d3ee",
            "gold": "#fbbf24",
            "orange": "#f97316",
            "app_bg": "radial-gradient(circle at top left, rgba(34,211,238,.09), transparent 30%), #070b12",
            "panel_bg": "linear-gradient(180deg, rgba(15,23,36,.96), rgba(9,14,23,.96))",
            "metric_bg": "rgba(15,23,42,.74)",
            "tag_bg": "rgba(15,23,42,.76)",
            "input_bg": "#0d1421",
            "placeholder": "#526072",
            "active_bg": "rgba(249,115,22,.13)",
            "active_text": "#fed7aa",
            "badge_text": "#bff5ff",
            "badge_bg": "rgba(14,116,144,.17)",
        }
    css = """
        <style>
        :root {
          color-scheme: {palette["scheme"]};
          --bg: {palette["bg"]};
          --panel: {palette["panel"]};
          --panel2: {palette["panel2"]};
          --line: {palette["line"]};
          --line2: {palette["line2"]};
          --text: {palette["text"]};
          --muted: {palette["muted"]};
          --faint: {palette["faint"]};
          --green: {palette["green"]};
          --red: {palette["red"]};
          --cyan: {palette["cyan"]};
          --gold: {palette["gold"]};
          --orange: {palette["orange"]};
          --app-bg: {palette["app_bg"]};
          --panel-bg: {palette["panel_bg"]};
          --metric-bg: {palette["metric_bg"]};
          --tag-bg: {palette["tag_bg"]};
          --input-bg: {palette["input_bg"]};
          --placeholder: {palette["placeholder"]};
          --active-bg: {palette["active_bg"]};
          --active-text: {palette["active_text"]};
          --badge-text: {palette["badge_text"]};
          --badge-bg: {palette["badge_bg"]};
        }
        html, body, [data-testid="stAppViewContainer"], [data-testid="stApp"] {
          background: var(--app-bg);
          color: var(--text);
        }
        [data-testid="stHeader"], [data-testid="stToolbar"], [data-testid="stDecoration"],
        #MainMenu, footer { display: none; }
        .block-container { max-width: 520px; padding: 14px 12px 34px; }
        .hero, .section, .card {
          border: 1px solid var(--line);
          background: var(--panel-bg);
          border-radius:8px;
          box-shadow:0 10px 28px rgba(2,6,23,.10);
        }
        .hero { padding: 14px; margin-bottom: 10px; position:relative; overflow:hidden; }
        .hero:after {
          content:"";
          position:absolute;
          left:0;
          right:0;
          bottom:0;
          height:2px;
          background:linear-gradient(90deg, var(--orange), transparent 70%);
        }
        .brand { display:flex; justify-content:space-between; align-items:flex-start; gap:10px; }
        .title { font-size: 22px; font-weight: 900; line-height: 1.05; letter-spacing: 0; }
        .live { width:8px; height:8px; border-radius:99px; display:inline-block; background:var(--green); margin-right:7px; box-shadow:0 0 0 5px rgba(53,211,153,.10); }
        .sub { color: var(--muted); font-size: 12px; margin-top: 7px; }
        .badge { border:1px solid var(--line2); color:var(--badge-text); padding:5px 8px; font-size:12px; background:var(--badge-bg); white-space:nowrap; }
        .hero-actions { display:flex; align-items:center; gap:6px; flex:0 0 auto; }
        .theme-mini {
          display:flex;
          align-items:center;
          gap:4px;
          border:1px solid var(--line);
          background:var(--metric-bg);
          padding:3px;
          border-radius:999px;
        }
        .theme-dot {
          width:28px;
          height:28px;
          display:flex;
          align-items:center;
          justify-content:center;
          color:var(--muted) !important;
          text-decoration:none !important;
          border:1px solid transparent;
          border-radius:999px;
          font-size:15px;
          font-weight:900;
          line-height:1;
          -webkit-tap-highlight-color:rgba(249,115,22,.18);
        }
        .theme-dot.active {
          border-color:var(--orange);
          background:var(--active-bg);
          color:var(--active-text) !important;
          box-shadow:inset 0 0 0 1px rgba(249,115,22,.28);
        }
        .metrics { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:8px; margin-top:12px; }
        .metric { background:var(--metric-bg); border:1px solid var(--line); padding:9px 8px; min-height:58px; border-radius:6px; }
        .k { color:var(--faint); font-size:11px; }
        .v { color:var(--text); font-size:18px; font-weight:850; margin-top:4px; }
        .section { padding: 12px; margin: 12px 0 9px; }
        .section-title { font-size:14px; color:var(--text); font-weight:850; margin-bottom:8px; }
        .card { padding: 12px; margin: 8px 0; }
        .card-link {
          display:block;
          text-decoration:none !important;
          color:inherit !important;
          -webkit-tap-highlight-color:rgba(249,115,22,.18);
          cursor:pointer;
        }
        .card-link:active .card {
          transform:scale(.995);
        }
        .card.selected,
        .stock-select:checked + .card-link .card {
          border-color:var(--orange);
          background:linear-gradient(180deg, var(--active-bg), transparent 180%), var(--panel-bg);
          box-shadow:inset 0 0 0 1px rgba(249,115,22,.48), 0 12px 30px rgba(249,115,22,.10);
        }
        .selected-chip {
          color:var(--active-text);
          border:1px solid var(--orange);
          background:var(--active-bg);
          padding:3px 6px;
          font-size:11px;
          font-weight:850;
          margin-left:6px;
        }
        .selected-chip.target-only { display:none; }
        .stock-select:checked + .card-link .selected-chip.target-only { display:inline; }
        .stock-select {
          position:absolute;
          opacity:0;
          width:0;
          height:0;
          pointer-events:none;
        }
        .rowtop { display:flex; justify-content:space-between; gap:10px; align-items:flex-start; }
        .name { font-size:18px; font-weight:900; color:var(--text); }
        .code { color:var(--muted); font-size:12px; margin-top:3px; }
        .price { text-align:right; font-size:16px; font-weight:850; }
        .up { color:var(--red); }
        .down { color:var(--green); }
        .flat { color:var(--muted); }
        .tags { display:flex; flex-wrap:wrap; gap:6px; margin-top:9px; }
        .tag { border:1px solid var(--line); background:var(--tag-bg); color:var(--muted); padding:4px 7px; font-size:12px; }
        .reason { color:var(--muted); font-size:13px; line-height:1.45; margin-top:8px; }
        .empty { color:var(--muted); border:1px solid var(--line); background:var(--metric-bg); padding:16px; }
        .pick-row {
          border:1px solid var(--line);
          background:var(--metric-bg);
          padding:10px 11px;
          min-height:48px;
          display:flex;
          align-items:center;
          border-radius:6px;
        }
        .pick-name { color:var(--text); font-weight:900; font-size:15px; }
        .pick-code { color:var(--muted); font-size:12px; margin-top:2px; }
        .chip-shell {
          border:1px solid var(--line);
          background:linear-gradient(180deg, rgba(249,115,22,.08), transparent 70%), var(--panel-bg);
          padding:10px 11px;
          margin:8px 0 4px;
          border-radius:8px;
        }
        .chip-shell-title {
          color:var(--text);
          font-size:14px;
          font-weight:900;
          letter-spacing:0;
        }
        .chip-shell-sub {
          color:var(--muted);
          font-size:11px;
          margin-top:3px;
          line-height:1.45;
        }
        .stRadio > label {
          display:none !important;
        }
        .stRadio [role="radiogroup"] {
          display:flex;
          gap:8px;
          overflow-x:auto;
          padding:2px 0 8px;
          flex-wrap:nowrap;
          scrollbar-width:none;
        }
        .stRadio [role="radiogroup"]::-webkit-scrollbar { display:none; }
        .stRadio label {
          flex:0 0 auto;
          border:1px solid var(--line);
          background:var(--panel2);
          min-height:39px;
          padding:8px 13px;
          display:flex;
          align-items:center;
          justify-content:center;
          gap:0 !important;
        }
        .stRadio [role="radiogroup"] label > div:first-child,
        .stRadio [role="radiogroup"] label input,
        .stRadio [role="radiogroup"] label svg {
          display:none !important;
        }
        .stRadio label:has(input:checked) {
          border-color:var(--orange);
          background:var(--active-bg);
          box-shadow:inset 0 0 0 1px rgba(249,115,22,.42);
        }
        .stRadio label p {
          color:var(--text);
          font-size:13px;
          font-weight:800;
          white-space:nowrap;
          margin:0;
        }
        .stRadio label:has(input:checked) p { color:var(--active-text); }
        .stTextInput input {
          background:var(--input-bg); border:1px solid var(--line); color:var(--text);
          min-height:42px; border-radius:0;
        }
        .stTextInput input::placeholder { color:var(--placeholder); }
        .stButton button {
          border:1px solid var(--orange);
          background:var(--active-bg);
          color:var(--active-text);
          border-radius:6px;
          min-height:42px;
          font-weight:850;
        }
        .stButton button:active { transform:scale(.99); }
        .stButton button:disabled {
          border-color:rgba(148,163,184,.20);
          background:var(--metric-bg);
          color:#64748b;
        }
        div[data-testid="stVerticalBlock"] { gap: .45rem; }
        @media (max-width: 520px) {
          .block-container { padding-left: 8px; padding-right: 8px; }
          .section { padding: 9px; }
          .card { padding: 10px; }
          .name { font-size: 16px; }
          .price { font-size: 14px; }
        }
        </style>
        """
    for key, value in palette.items():
        css = css.replace(f'{{palette["{key}"]}}', value)
    st.markdown(css, unsafe_allow_html=True)


def render_header(model: dict, source: str, elapsed_ms: float) -> None:
    market = model["market"]
    updated = format_time(model["updated_at"])
    taiex = market_metric(market, "taiex")
    otc = market_metric(market, "otc")
    night_future = market_metric(market, "night_future")
    bias = as_dict(model["ai_panel"].get("summary")).get("bias") or "即時觀察"
    theme = first_text(st.session_state.get("theme"), "夜幕")
    night_class = " active" if theme == "夜幕" else ""
    sun_class = " active" if theme == "陽光" else ""
    night_href = f"?theme={quote('夜幕')}"
    sun_href = f"?theme={quote('陽光')}"
    st.markdown(
        f"""
        <div class="hero">
          <div class="brand">
            <div>
              <div class="title"><span class="live"></span>輔滿終端</div>
              <div class="sub">{escape(updated)} 更新 · {elapsed_ms:.0f}ms · {escape(source)}</div>
            </div>
            <div class="hero-actions">
              <div class="badge">{escape(str(bias))}</div>
              <div class="theme-mini">
                <a class="theme-dot{night_class}" href="{night_href}" aria-label="切換夜幕">☾</a>
                <a class="theme-dot{sun_class}" href="{sun_href}" aria-label="切換陽光">☀</a>
              </div>
            </div>
          </div>
          <div class="metrics">
            {metric_html("↗ 加權指數", taiex)}
            {metric_html("↗ 櫃買指數", otc)}
            {metric_html("↕ 台指期夜盤", night_future)}
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def market_metric(market: dict, kind: str) -> dict:
    aliases = {
        "taiex": ("taiex", "twse", "weightedIndex", "weighted_index", "marketIndex", "index"),
        "otc": ("otc", "tpex", "otcIndex", "otc_index", "greTaiIndex"),
        "night_future": ("nightFuture", "night_future", "txfNight", "txf_night", "taiwanFutureNight", "futureNight"),
    }
    for key in aliases[kind]:
        candidate = as_dict(market.get(key))
        if candidate:
            return candidate
    return {
        "value": first_value(
            market.get(f"{kind}Value"),
            market.get(f"{kind}_value"),
            market.get(kind),
        ),
        "change": first_value(market.get(f"{kind}Change"), market.get(f"{kind}_change")),
        "percent": first_value(market.get(f"{kind}Percent"), market.get(f"{kind}_percent")),
    }


def metric_html(label: str, metric: dict) -> str:
    value = market_value_text(first_value(metric.get("value"), metric.get("close"), metric.get("price"), metric.get("last"), metric.get("index")))
    change = first_value(metric.get("change"), metric.get("diff"), metric.get("changeValue"), metric.get("point"))
    percent = first_value(metric.get("percent"), metric.get("changePercent"), metric.get("pct"), metric.get("rate"))
    detail = market_change_text(change, percent)
    tone = pct_class(percent if percent not in (None, "") else change)
    return (
        f'<div class="metric">'
        f'<div class="k">{escape(label)}</div>'
        f'<div class="v">{escape(value)}</div>'
        f'<div class="{tone}" style="font-size:11px;font-weight:800;margin-top:4px;">{escape(detail)}</div>'
        f'</div>'
    )


def market_value_text(value: object) -> str:
    if value in (None, ""):
        return "--"
    try:
        return f"{float(value):,.2f}"
    except (TypeError, ValueError):
        return str(value)


def market_change_text(change: object, percent: object) -> str:
    parts: list[str] = []
    try:
        parts.append(f"{float(change):+,.2f}")
    except (TypeError, ValueError):
        pass
    try:
        parts.append(f"({float(percent):+.2f}%)")
    except (TypeError, ValueError):
        pass
    return " ".join(parts) if parts else "--"


def render_brief(model: dict, query: str) -> None:
    render_sector_section("強勢族群", model["strong_sectors"], positive=True)
    render_sector_section("弱勢族群", model["weak_sectors"], positive=False)
    priority = model["priority"] or model["risk"][:8]
    render_list("終端快訊", priority, query, mode="stock")


def render_strategy(model: dict, query: str) -> None:
    render_list("策略1 明日開盤入", model["strategy1"], query, mode="strategy")
    render_list("策略2 A區進場", model["strategy2"], query, mode="strategy")
    render_list("策略3 資金快篩", model["strategy3"], query, mode="strategy")
    render_list("策略4 波段", model["strategy4"], query, mode="strategy")
    render_list("策略5 綜合", model["strategy5"], query, mode="strategy")
    render_list("即時雷達", model["radar"], query, mode="strategy")
    render_list("CB 名單", model["cb"], query, mode="strategy")


def render_strategy4_page(rows: list[dict], query: str) -> None:
    render_strategy_shell("策略4 波段策略頁", "依 A/B/C 區與波段訊號拆分，優先看可進場與關鍵突破。")
    view = st.radio(
        "strategy4-view",
        ["A區可進場", "B區觀察", "C區準備", "逃逸缺口", "量叉", "主力多"],
        horizontal=True,
        label_visibility="collapsed",
    )
    render_list(view, strategy4_rows(rows, view), query, mode="strategy")


def render_strategy5_page(rows: list[dict], query: str) -> None:
    render_strategy_shell("策略5 綜合策略頁", "依綜合模型拆分，快速看技術、籌碼、量價與突破型訊號。")
    view = st.radio(
        "strategy5-view",
        ["布林KDJ", "準突破", "漲停十字", "量價周轉", "籌碼老K"],
        horizontal=True,
        label_visibility="collapsed",
    )
    render_list(view, strategy5_rows(rows, view), query, mode="strategy")


def render_strategy_shell(title: str, subtitle: str) -> None:
    st.markdown(
        f"""
        <div class="chip-shell">
          <div class="chip-shell-title">{escape(title)}</div>
          <div class="chip-shell-sub">{escape(subtitle)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def strategy4_rows(rows: list[dict], view: str) -> list[dict]:
    zone_map = {
        "A區可進場": "A",
        "B區觀察": "B",
        "C區準備": "C",
    }
    if view in zone_map:
        selected = [row for row in rows if first_text(row.get("swingZone")) == zone_map[view]]
    else:
        selected = [row for row in rows if row_has_signal(row, view)]
    return sorted(selected, key=lambda row: num_value(row.get("score")), reverse=True)


def strategy5_rows(rows: list[dict], view: str) -> list[dict]:
    signal_map = {
        "布林KDJ": "bollinger_kdj_buy",
        "準突破": "foreign_trust_breakout",
        "漲停十字": "limit_up_doji",
        "量價周轉": "volume_turnover_breakout",
        "籌碼老K": "chip_k_confluence",
    }
    selected = [row for row in rows if row_has_signal(row, signal_map[view], view)]
    return sorted(selected, key=lambda row: num_value(row.get("score")), reverse=True)


def row_has_signal(row: dict, *needles: str) -> bool:
    haystack: list[str] = []
    for key in ("activeMatch",):
        value = row.get(key)
        if isinstance(value, dict):
            haystack.extend(str(value.get(field, "")) for field in ("id", "short", "label", "name", "reason"))
        elif value:
            haystack.append(str(value))
    for key in ("matches", "swingSignals", "strategy4Signals", "signals"):
        for item in row.get(key) or []:
            if isinstance(item, dict):
                haystack.extend(str(item.get(field, "")) for field in ("id", "short", "title", "label", "name", "reason"))
            else:
                haystack.append(str(item))
    text = " ".join(haystack)
    return any(needle and needle in text for needle in needles)


def render_chip_strategy_page(rows: list[dict], query: str) -> None:
    render_strategy_shell("買賣超策略頁", "依外資、投信與成交量條件切換，優先看籌碼集中與連續買盤。")
    view = st.radio(
        "chip-strategy-view",
        ["外資連3買 + 1000張連3週增", "外資+投信佔5日均量", "外資連買日", "投信連買日", "同買日"],
        horizontal=True,
        label_visibility="collapsed",
    )
    filtered = chip_strategy_rows(rows, view)
    render_list(view, filtered, query, mode="chip")


def chip_strategy_rows(rows: list[dict], view: str) -> list[dict]:
    if view == "外資連3買 + 1000張連3週增":
        selected = [row for row in rows if num_value(row.get("foreignStreak")) >= 3 and num_value(row.get("foreign")) >= 1_000_000]
        return sorted(selected, key=lambda row: (num_value(row.get("foreignStreak")), num_value(row.get("foreign"))), reverse=True)
    if view == "外資+投信佔5日均量":
        selected = [row for row in rows if num_value(row.get("foreign")) + num_value(row.get("trust")) > 0 and num_value(row.get("fiveDayAvgVolume")) > 0]
        return sorted(selected, key=foreign_trust_volume_ratio, reverse=True)
    if view == "外資連買日":
        selected = [row for row in rows if num_value(row.get("foreignStreak")) > 0 and num_value(row.get("foreign")) > 0]
        return sorted(selected, key=lambda row: (num_value(row.get("foreignStreak")), num_value(row.get("foreign"))), reverse=True)
    if view == "投信連買日":
        selected = [row for row in rows if num_value(row.get("trustStreak")) > 0 and num_value(row.get("trust")) > 0]
        return sorted(selected, key=lambda row: (num_value(row.get("trustStreak")), num_value(row.get("trust"))), reverse=True)
    if view == "同買日":
        selected = [row for row in rows if num_value(row.get("foreign")) > 0 and num_value(row.get("trust")) > 0]
        return sorted(selected, key=lambda row: (num_value(row.get("foreign")) + num_value(row.get("trust")), num_value(row.get("total"))), reverse=True)
    return sorted(rows, key=lambda row: num_value(row.get("total")), reverse=True)


def foreign_trust_volume_ratio(row: dict) -> float:
    volume = num_value(row.get("fiveDayAvgVolume"))
    if volume <= 0:
        return 0.0
    return (num_value(row.get("foreign")) + num_value(row.get("trust"))) / volume


def render_search_picker(model: dict, query: str) -> None:
    q = str(query or "").strip()
    if not q:
        return
    matches = search_all_rows(model, q)[:8]
    if not matches:
        return
    st.markdown(f'<div class="section"><div class="section-title">搜尋結果 · {len(matches)}</div>', unsafe_allow_html=True)
    for idx, row in enumerate(matches):
        code = stock_code(row)
        name = stock_name(row)
        close = first_value(row.get("close"), row.get("price"), row.get("underlyingClose"), row.get("displayClose"))
        percent = first_value(row.get("percent"), row.get("changePercent"), row.get("change_percent"), row.get("underlyingPercent"), row.get("displayPercent"))
        already = code in st.session_state.watchlist_codes
        left, right = st.columns([5, 2])
        with left:
            st.markdown(
                f"""
                <div class="pick-row">
                  <div>
                    <div class="pick-name">{escape(name)}</div>
                    <div class="pick-code">{escape(code)} · {price_text(close, percent)}</div>
                  </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
        with right:
            label = "已加入" if already else "加入"
            if st.button(label, key=f"watch-add-{code}-{idx}", disabled=already, use_container_width=True):
                st.session_state.watchlist_codes.append(code)
                st.rerun()
    st.markdown("</div>", unsafe_allow_html=True)


def render_watchlist(model: dict, query: str) -> None:
    codes = list(dict.fromkeys(st.session_state.watchlist_codes))
    rows = [row for row in search_all_rows(model, "") if stock_code(row) in codes]
    rows_by_code = {stock_code(row): row for row in rows}
    ordered = [rows_by_code[code] for code in codes if code in rows_by_code]
    filtered = filter_rows(ordered, query)
    st.markdown(f'<div class="section"><div class="section-title">自選股 · {len(filtered)}</div>', unsafe_allow_html=True)
    if not codes:
        st.markdown('<div class="empty">先在上方搜尋代號或名稱，按「加入」後會出現在這裡。</div>', unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)
        return
    if not filtered:
        st.markdown('<div class="empty">自選股目前沒有符合搜尋條件的項目。</div>', unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)
        return
    for row in filtered[:50]:
        render_card(row, "stock")
    st.markdown("</div>", unsafe_allow_html=True)


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
    code = first_text(row.get("code"), row.get("symbol"), row.get("underlyingCode"), row.get("ticker"))
    name = first_text(row.get("name"), row.get("stockName"), row.get("underlyingName"), code, "--")
    close = first_value(row.get("close"), row.get("price"), row.get("underlyingClose"), row.get("displayClose"))
    percent = first_value(row.get("percent"), row.get("changePercent"), row.get("change_percent"), row.get("underlyingPercent"), row.get("displayPercent"))
    tone = pct_class(percent)
    right = price_text(close, percent)
    tags = tags_for(row, mode)
    reason = first_text(row.get("reason"), row.get("blockReason"), row.get("strategy4Reason"), row.get("actionLabel"), row.get("summary"), "")
    selected = code and st.session_state.selected_stock_code == code
    card_class = "card selected" if selected else "card"
    selected_chip = '<span class="selected-chip">已選取</span>' if selected else '<span class="selected-chip target-only">已選取</span>'
    target_id = stock_target_id(mode, code, row) if code else ""
    checked = " checked" if selected else ""
    st.markdown(
        f"""
        <input id="{target_id}" class="stock-select" type="radio" name="selected-stock"{checked}>
        <label class="card-link" for="{target_id}">
          <div class="{card_class}">
            <div class="rowtop">
              <div>
                <div class="name">{escape(str(name))}{selected_chip}</div>
                <div class="code">{escape(str(code))}</div>
              </div>
              <div class="price {tone}">{right}</div>
            </div>
            {render_tags(tags)}
            {f'<div class="reason">{escape(str(reason))}</div>' if reason else ''}
          </div>
        </label>
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
        if row.get("decision"):
            tags.append(str(row.get("decision")))
        if row.get("setupType"):
            tags.append(str(row.get("setupType")))
        if row.get("swingZone"):
            tags.append(f"區 {row.get('swingZone')}")
        if row.get("zone"):
            tags.append(f"區 {row.get('zone')}")
        if row.get("score") is not None:
            tags.append(f"分數 {compact(row.get('score'))}")
        for signal in list_from(row.get("swingSignals") or row.get("matches") or row.get("signals"))[:3]:
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


def search_all_rows(model: dict, query: str) -> list[dict]:
    pool: list[dict] = []
    for key in ("priority", "risk", "strategy1", "strategy2", "strategy3", "strategy4", "strategy5", "radar", "chip", "warrant", "cb", "stocks"):
        pool.extend(model.get(key) or [])

    by_code: dict[str, dict] = {}
    no_code: list[dict] = []
    for row in pool:
        code = stock_code(row)
        if not code:
            no_code.append(row)
            continue
        current = by_code.get(code)
        if current is None or row_score(row) > row_score(current):
            by_code[code] = row

    rows = list(by_code.values()) + no_code
    return filter_rows(rows, query)


def load_local_rows(*patterns: str) -> list[dict]:
    rows: list[dict] = []
    seen_files: set[Path] = set()
    for data_dir in LOCAL_DATA_DIRS:
        if not data_dir.exists():
            continue
        for pattern in patterns:
            for file in sorted(data_dir.glob(pattern)):
                if file in seen_files:
                    continue
                seen_files.add(file)
                try:
                    payload = json.loads(file.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                rows.extend(api_rows(payload))
    return dedupe_rows(rows)


def dedupe_rows(rows: list[dict]) -> list[dict]:
    result: list[dict] = []
    seen: set[str] = set()
    for row in rows:
        code = stock_code(row)
        key = code or json.dumps(row, ensure_ascii=False, sort_keys=True)[:160]
        if key in seen:
            continue
        seen.add(key)
        result.append(row)
    return result


def stock_code(row: dict) -> str:
    return first_text(row.get("code"), row.get("symbol"), row.get("underlyingCode"), row.get("ticker"))


def stock_name(row: dict) -> str:
    return first_text(row.get("name"), row.get("stockName"), row.get("underlyingName"), stock_code(row), "--")


def row_score(row: dict) -> int:
    score = 0
    for key in ("name", "stockName", "close", "price", "percent", "changePercent", "reason", "score", "total"):
        if row.get(key) not in (None, ""):
            score += 1
    return score


def stock_href(code: str) -> str:
    theme = first_text(st.session_state.get("theme"), "夜幕")
    return f"?selected_stock={escape(code)}&theme={escape(theme)}"


def stock_target_id(mode: str, code: str, row: dict) -> str:
    raw = f"{mode}-{code}-{abs(hash(first_text(row.get('reason'), row.get('date'), row.get('updatedAt'), code))) % 100000}"
    return "stock-" + "".join(ch if ch.isalnum() else "-" for ch in raw.lower())


def rows_from(value: object, keys: tuple[str, ...]) -> list[dict]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    value = as_dict(value)
    for key in keys:
        rows = list_from(value.get(key))
        if rows:
            return rows
        mapped_rows = mapped_rows_from(value.get(key))
        if mapped_rows:
            return mapped_rows
    mapped_rows = mapped_rows_from(value)
    if mapped_rows:
        return mapped_rows
    return []


def api_rows(value: object, fallback: object = None) -> list[dict]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    value = as_dict(value)
    candidates = [
        value,
        value.get("data"),
        value.get("payload"),
        value.get("result"),
        value.get("results"),
        value.get("report"),
    ]
    keys = (
        "top",
        "rows",
        "items",
        "events",
        "records",
        "signals",
        "results",
        "matches",
        "candidates",
        "stocks",
        "entries",
        "volumeMatches",
        "singleSignals",
        "observationStocks",
        "recommendations",
        "list",
    )
    for candidate in candidates:
        rows = rows_from(candidate, keys=keys)
        if rows:
            return rows
    return rows_from(fallback, keys=("top", "rows", "items", "signals", "results", "matches", "candidates", "stocks"))


def list_from(value: object) -> list[dict]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    return []


def mapped_rows_from(value: object) -> list[dict]:
    value = as_dict(value)
    if not value:
        return []
    rows = [item for item in value.values() if isinstance(item, dict)]
    if not rows:
        return []
    useful = [
        row
        for row in rows
        if first_text(row.get("code"), row.get("symbol"), row.get("ticker"), row.get("name"), row.get("stockName"))
    ]
    return useful if len(useful) >= max(1, len(rows) // 2) else []


def as_dict(value: object) -> dict:
    return value if isinstance(value, dict) else {}


def first_query_value(key: str) -> str:
    try:
        value = st.query_params.get(key, "")
    except Exception:
        return ""
    if isinstance(value, list):
        return first_text(*value)
    return first_text(value)


def first_text(*values: object) -> str:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def first_value(*values: object) -> object:
    for value in values:
        if value not in (None, ""):
            return value
    return None


def num_value(value: object) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


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

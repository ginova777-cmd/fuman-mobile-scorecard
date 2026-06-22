from __future__ import annotations

import pandas as pd
import streamlit as st

from backtest_engine import connect
from supabase_client import fetch_strategy_summary, fetch_trade_records, load_config


st.set_page_config(page_title="Fuman Trade Records", layout="wide")

con = connect()
supabase_config = load_config(required=False)


@st.cache_data(ttl=30)
def load_records() -> tuple[pd.DataFrame, pd.DataFrame]:
    if supabase_config:
        records_df = fetch_trade_records(supabase_config, days=30).rename(
            columns={"source": "source_sheet"}
        )
        summary_df = fetch_strategy_summary(supabase_config, days=30)
        if not summary_df.empty:
            summary_df = summary_df.sort_values(["summary_date", "strategy"], ascending=[False, True])
            summary_df = summary_df.drop_duplicates("strategy", keep="first")
        return records_df, summary_df

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
        order by try_strptime(record_date, '%Y-%m-%d') desc nulls last, strategy, ticker
        """
    ).df()
    summary = con.execute("select * from fuman_scorecard_daily").df()
    return records, summary


def display_records(frame: pd.DataFrame) -> None:
    view = frame[
        [
            "record_date",
            "ticker",
            "name",
            "entry_time",
            "entry_price",
            "high_price",
            "pnl",
        ]
    ].rename(
        columns={
            "record_date": "日期",
            "ticker": "台股代號",
            "name": "台股名稱",
            "entry_time": "進場時間",
            "entry_price": "進場價格",
            "high_price": "最高價",
            "pnl": "損益",
        }
    )
    view["進場時間"] = view["進場時間"].replace("", "--").fillna("--")
    st.dataframe(
        view,
        column_config={
            "日期": st.column_config.TextColumn("日期"),
            "台股代號": st.column_config.TextColumn("台股代號"),
            "台股名稱": st.column_config.TextColumn("台股名稱"),
            "進場時間": st.column_config.TextColumn("進場時間"),
            "進場價格": st.column_config.NumberColumn("進場價格", format="%.2f"),
            "最高價": st.column_config.NumberColumn("最高價", format="%.2f"),
            "損益": st.column_config.NumberColumn("損益", format="%d"),
        },
        use_container_width=True,
        hide_index=True,
    )


def metric_row(frame: pd.DataFrame) -> None:
    rows = len(frame)
    total_pnl = frame["pnl"].fillna(0).sum() if rows else 0
    wins = (frame["pnl"].fillna(0) > 0).sum() if rows else 0
    losses = (frame["pnl"].fillna(0) < 0).sum() if rows else 0
    win_rate = wins / rows * 100 if rows else 0

    cols = st.columns(4)
    cols[0].metric("逐筆筆數", f"{rows:,}")
    cols[1].metric("勝率", f"{win_rate:.1f}%")
    cols[2].metric("獲利 / 虧損", f"{wins:,} / {losses:,}")
    cols[3].metric("損益", f"{total_pnl:,.0f}")


records, summary = load_records()

st.title("輔滿逐筆紀錄")
st.caption("當天逐筆與歷史紀錄分開看；策略4 保留 1 個月，其他策略保留 7 天。")
st.caption("資料來源：" + ("Supabase" if supabase_config else "本機 DuckDB / Google Sheet 匯入"))

if records.empty:
    st.warning("目前沒有逐筆紀錄。請先重新匯入 Google Sheet 或寫入 DuckDB。")
    st.stop()

records["record_date"] = records["record_date"].astype(str)
latest_date = records["record_date"].max()
strategies = sorted(records["strategy"].dropna().unique())

with st.sidebar:
    st.header("篩選")
    selected_strategies = st.multiselect("策略", strategies, default=strategies)
    result_filter = st.radio("結果", ["全部", "獲利", "虧損", "平盤"], horizontal=True)
    query = st.text_input("台股代號 / 名稱")
    st.divider()
    st.caption("保留規則")
    st.write("策略4：30 天")
    st.write("其他策略：7 天")

filtered = records[records["strategy"].isin(selected_strategies)].copy()
if result_filter == "獲利":
    filtered = filtered[filtered["pnl"].fillna(0) > 0]
elif result_filter == "虧損":
    filtered = filtered[filtered["pnl"].fillna(0) < 0]
elif result_filter == "平盤":
    filtered = filtered[filtered["pnl"].fillna(0) == 0]

if query.strip():
    q = query.strip()
    filtered = filtered[
        filtered["ticker"].astype(str).str.contains(q, case=False, na=False)
        | filtered["name"].astype(str).str.contains(q, case=False, na=False)
    ]

today_records = filtered[filtered["record_date"] == latest_date].copy()

today_tab, history_tab, strategy_tab = st.tabs(["當天逐筆", "歷史紀錄", "策略概況"])

with today_tab:
    st.subheader(f"當天逐筆紀錄：{latest_date}")
    metric_row(today_records)
    display_records(today_records)

with history_tab:
    st.subheader("歷史紀錄")
    date_options = sorted(filtered["record_date"].dropna().unique(), reverse=True)
    selected_dates = st.multiselect("日期", date_options, default=date_options)
    history = filtered[filtered["record_date"].isin(selected_dates)].copy()
    metric_row(history)
    display_records(history)

with strategy_tab:
    st.subheader("策略概況")
    if summary.empty:
        st.info("目前沒有策略摘要資料。")
    else:
        strategy_summary = summary[
            [
                "strategy",
                "signals",
                "backtestable",
                "wins",
                "losses",
                "flats",
                "win_rate_pct",
                "total_pnl",
                "status",
            ]
        ].rename(
            columns={
                "strategy": "策略",
                "signals": "訊號",
                "backtestable": "可回測",
                "wins": "獲利",
                "losses": "虧損",
                "flats": "平盤",
                "win_rate_pct": "勝率",
                "total_pnl": "總損益",
                "status": "口徑",
            }
        )
        st.dataframe(
            strategy_summary.style.format(
                {
                    "訊號": "{:,.0f}",
                    "可回測": "{:,.0f}",
                    "獲利": "{:,.0f}",
                    "虧損": "{:,.0f}",
                    "平盤": "{:,.0f}",
                    "勝率": "{:.1f}%",
                    "總損益": "{:,.0f}",
                },
                na_rep="--",
            ),
            use_container_width=True,
            hide_index=True,
        )

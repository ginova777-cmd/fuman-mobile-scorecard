from __future__ import annotations

from pathlib import Path
import re

import duckdb
import pandas as pd

from xlsx_reader import read_workbook


WORKBOOK_PATH = Path(__file__).with_name("data") / "fuman-scorecard.xlsx"
SUMMARY_SHEET = "回測摘要"
LEDGER_SHEET = "近7日進出紀錄"


STRATEGY_SHEETS = [
    "交易管家成績單",
    "即時雷達成績單",
    "策略1成績單",
    "策略2成績單",
    "策略2-A區進場",
    "策略3成績單",
    "策略4成績單",
    "策略5成績單",
    "買賣超成績單",
    "權證成績單",
    "CB成績單",
]


def create_fuman_schema(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(
        """
        create table if not exists fuman_scorecard_daily (
            strategy varchar,
            signals double,
            backtestable double,
            wins double,
            losses double,
            flats double,
            win_rate_pct double,
            total_pnl double,
            avg_pnl double,
            max_profit double,
            max_loss double,
            status varchar,
            note varchar,
            source_sheet varchar
        )
        """
    )
    con.execute(
        """
        create table if not exists fuman_trade_ledger (
            trade_date varchar,
            scorecard varchar,
            block_name varchar,
            ticker varchar,
            name varchar,
            entry_time varchar,
            entry_price varchar,
            exit_time varchar,
            exit_price varchar,
            pnl double,
            result varchar,
            status varchar,
            reason varchar
        )
        """
    )
    con.execute(
        """
        create table if not exists fuman_strategy_details (
            strategy varchar,
            row_no integer,
            ticker varchar,
            name varchar,
            pnl double,
            result varchar,
            status varchar,
            score double,
            entry_text varchar,
            exit_text varchar,
            reason varchar
        )
        """
    )
    con.execute(
        """
        create table if not exists fuman_data_quality (
            strategy varchar,
            status varchar,
            note varchar,
            backtest_policy varchar,
            source_sheet varchar
        )
        """
    )
    con.execute(
        """
        create table if not exists fuman_trade_records (
            record_id varchar,
            record_date varchar,
            strategy varchar,
            ticker varchar,
            name varchar,
            entry_time varchar,
            entry_price double,
            high_price double,
            pnl double,
            source_sheet varchar,
            reason varchar
        )
        """
    )


def import_fuman_workbook(con: duckdb.DuckDBPyConnection, path: Path = WORKBOOK_PATH) -> None:
    if not path.exists():
        return

    workbook = read_workbook(path)
    create_fuman_schema(con)
    summary = parse_summary(workbook.get(SUMMARY_SHEET, []))
    ledger = parse_ledger(workbook.get(LEDGER_SHEET, []))
    details = parse_strategy_details(workbook)
    trade_records = parse_trade_records(workbook)
    quality = build_quality(summary)

    for table in [
        "fuman_scorecard_daily",
        "fuman_trade_ledger",
        "fuman_strategy_details",
        "fuman_data_quality",
    ]:
        con.execute(f"delete from {table}")

    _insert_df(con, "fuman_scorecard_daily", summary)
    _insert_df(con, "fuman_trade_ledger", ledger)
    _insert_df(con, "fuman_strategy_details", details)
    _insert_df(con, "fuman_data_quality", quality)
    upsert_trade_records(con, trade_records)


def upsert_trade_records(con: duckdb.DuckDBPyConnection, records: pd.DataFrame) -> None:
    if records.empty:
        return

    con.register("incoming_records", records)
    con.execute(
        """
        delete from fuman_trade_records
        where record_id in (select record_id from incoming_records)
        """
    )
    con.execute("insert into fuman_trade_records select * from incoming_records")
    con.unregister("incoming_records")
    con.execute(
        """
        delete from fuman_trade_records
        where try_strptime(record_date, '%Y-%m-%d') is not null
          and (
            (strategy = '策略4成績單' and try_strptime(record_date, '%Y-%m-%d') < current_date - interval 30 day)
            or
            (strategy <> '策略4成績單' and try_strptime(record_date, '%Y-%m-%d') < current_date - interval 7 day)
          )
        """
    )


def parse_summary(rows: list[list[object]]) -> pd.DataFrame:
    header_index = _find_row(rows, "策略/籌碼")
    if header_index is None:
        return pd.DataFrame()

    headers = [_clean(cell) for cell in rows[header_index]]
    records = []
    for row in rows[header_index + 1 :]:
        values = dict(zip(headers, row))
        strategy = _clean(values.get("策略/籌碼"))
        if not strategy:
            continue
        records.append(
            {
                "strategy": strategy,
                "signals": _number(values.get("訊號筆數")),
                "backtestable": _number(values.get("可回測筆數")),
                "wins": _number(values.get("獲利")),
                "losses": _number(values.get("虧損")),
                "flats": _number(values.get("平盤")),
                "win_rate_pct": _percent(values.get("勝率")),
                "total_pnl": _number(values.get("總損益")),
                "avg_pnl": _number(values.get("平均損益")),
                "max_profit": _number(values.get("最大獲利")),
                "max_loss": _number(values.get("最大虧損")),
                "status": _clean(values.get("狀態")),
                "note": _clean(values.get("備註")),
                "source_sheet": SUMMARY_SHEET,
            }
        )
    return pd.DataFrame(records)


def parse_ledger(rows: list[list[object]]) -> pd.DataFrame:
    header_index = _find_row(rows, "日期")
    if header_index is None:
        return pd.DataFrame()

    headers = [_clean(cell) for cell in rows[header_index]]
    records = []
    for row in rows[header_index + 1 :]:
        values = dict(zip(headers, row))
        trade_date = _clean(values.get("日期"))
        ticker = _clean(values.get("股票代碼"))
        if not trade_date or not ticker:
            continue
        records.append(
            {
                "trade_date": trade_date,
                "scorecard": _clean(values.get("成績單")),
                "block_name": _clean(values.get("區塊")),
                "ticker": ticker,
                "name": _clean(values.get("股票名稱")),
                "entry_time": _clean(values.get("進場時間")),
                "entry_price": _clean(values.get("進場價")),
                "exit_time": _clean(values.get("出場時間")),
                "exit_price": _clean(values.get("出場價")),
                "pnl": _number(values.get("損益")),
                "result": _clean(values.get("結果")),
                "status": _clean(values.get("狀態")),
                "reason": _clean(values.get("原因")),
            }
        )
    return pd.DataFrame(records)


def parse_strategy_details(workbook: dict[str, list[list[object]]]) -> pd.DataFrame:
    records = []
    for sheet in STRATEGY_SHEETS:
        rows = workbook.get(sheet, [])
        header_index = _best_detail_header(rows)
        if header_index is None:
            continue
        headers = [_clean(cell) for cell in rows[header_index]]
        for offset, row in enumerate(rows[header_index + 1 :], 1):
            values = dict(zip(headers, row))
            ticker = _clean(_first(values, ["股票代碼", "股票代號", "標的代碼"]))
            name = _clean(_first(values, ["股票名稱", "標的名稱"]))
            if not ticker and not name:
                continue
            pnl = _number(_first(values, ["損益", "預計損益", "訊號日損益"]))
            records.append(
                {
                    "strategy": sheet,
                    "row_no": offset,
                    "ticker": ticker,
                    "name": name,
                    "pnl": pnl,
                    "result": _result_from_pnl(pnl),
                    "status": _clean(_first(values, ["操作狀態", "狀態", "行動"])),
                    "score": _number(_first(values, ["分數", "總分"])),
                    "entry_text": _clean(_first(values, ["進場", "進場時間", "參考進場價", "建議進場"])),
                    "exit_text": _clean(_first(values, ["出場", "計畫出場", "目標1"])),
                    "reason": _clean(_first(values, ["原因", "理由", "判斷原因", "訊號/理由"])),
                }
            )
    return pd.DataFrame(records)


def parse_trade_records(workbook: dict[str, list[list[object]]]) -> pd.DataFrame:
    records = []

    for sheet in STRATEGY_SHEETS:
        rows = workbook.get(sheet, [])
        header_index = _best_detail_header(rows)
        if header_index is None:
            continue

        sheet_date = _sheet_date(rows)
        headers = [_clean(cell) for cell in rows[header_index]]
        for offset, row in enumerate(rows[header_index + 1 :], 1):
            values = dict(zip(headers, row))
            ticker = _clean(_first(values, ["股票代碼", "股票代號", "標的代碼"]))
            name = _clean(_first(values, ["股票名稱", "標的名稱"]))
            if not ticker and not name:
                continue

            record_date = _record_date(values, sheet_date)
            entry_time, entry_price = _entry_fields(values, sheet)
            high_price = _number(_first(values, ["盤中最高價", "最高價", "目標1"]))
            pnl = _number(_first(values, ["損益", "預計損益", "訊號日損益"]))
            record_id = "|".join([record_date, sheet, ticker, str(offset)])
            records.append(
                {
                    "record_id": record_id,
                    "record_date": record_date,
                    "strategy": sheet,
                    "ticker": ticker,
                    "name": name,
                    "entry_time": entry_time,
                    "entry_price": entry_price,
                    "high_price": high_price,
                    "pnl": pnl,
                    "source_sheet": sheet,
                    "reason": _clean(_first(values, ["原因", "理由", "判斷原因", "訊號/理由"])),
                }
            )

    ledger_rows = parse_ledger(workbook.get(LEDGER_SHEET, []))
    if not ledger_rows.empty:
        for offset, row in enumerate(ledger_rows.to_dict("records"), 1):
            record_date = _date_text(row.get("trade_date"))
            ticker = _clean(row.get("ticker"))
            strategy = _clean(row.get("scorecard"))
            if not record_date or not ticker:
                continue
            records.append(
                {
                    "record_id": "|".join([record_date, strategy, ticker, "ledger", str(offset)]),
                    "record_date": record_date,
                    "strategy": strategy,
                    "ticker": ticker,
                    "name": _clean(row.get("name")),
                    "entry_time": _clean(row.get("entry_time")),
                    "entry_price": _number(row.get("entry_price")),
                    "high_price": None,
                    "pnl": _number(row.get("pnl")),
                    "source_sheet": LEDGER_SHEET,
                    "reason": _clean(row.get("reason")),
                }
            )

    return pd.DataFrame(records)


def build_quality(summary: pd.DataFrame) -> pd.DataFrame:
    if summary.empty:
        return pd.DataFrame()
    records = []
    for row in summary.to_dict("records"):
        status = row.get("status", "")
        note = row.get("note", "")
        policy = "實際/表內回測"
        if "不可" in status or "缺少" in note:
            policy = "不可計算勝率"
        elif "訊號日" in status:
            policy = "訊號日估算"
        elif "模型" in status:
            policy = "模型估算"
        records.append(
            {
                "strategy": row["strategy"],
                "status": status,
                "note": note,
                "backtest_policy": policy,
                "source_sheet": row["source_sheet"],
            }
        )
    return pd.DataFrame(records)


def _insert_df(con: duckdb.DuckDBPyConnection, table: str, df: pd.DataFrame) -> None:
    if df.empty:
        return
    con.register("incoming_df", df)
    con.execute(f"insert into {table} select * from incoming_df")
    con.unregister("incoming_df")


def _find_row(rows: list[list[object]], label: str) -> int | None:
    for index, row in enumerate(rows):
        if label in [_clean(cell) for cell in row]:
            return index
    return None


def _best_detail_header(rows: list[list[object]]) -> int | None:
    candidates = []
    for index, row in enumerate(rows):
        labels = {_clean(cell) for cell in row}
        score = 0
        if labels & {"股票代碼", "股票代號", "標的代碼"}:
            score += 2
        if labels & {"損益", "預計損益", "訊號日損益"}:
            score += 2
        if labels & {"原因", "理由", "判斷原因", "訊號/理由"}:
            score += 1
        if score:
            candidates.append((score, index))
    if not candidates:
        return None
    return sorted(candidates, reverse=True)[0][1]


def _sheet_date(rows: list[list[object]]) -> str:
    date_labels = ["成績單日期", "資料日期", "日期", "標的日", "成績日", "偵測日", "市場資料日"]
    for row in rows[:8]:
        labels = [_clean(cell) for cell in row]
        for index, label in enumerate(labels[:-1]):
            if label in date_labels:
                candidate = _date_text(labels[index + 1])
                if candidate:
                    return candidate
    return ""


def _record_date(values: dict[str, object], sheet_date: str) -> str:
    return (
        _date_text(_first(values, ["日期", "成績日", "訊號日", "偵測日", "資料日期"]))
        or sheet_date
    )


def _date_text(value: object) -> str:
    text = _clean(value)
    if not text:
        return ""
    match = re.search(r"(20\d{2})[-/](\d{1,2})[-/](\d{1,2})", text)
    if match:
        year, month, day = match.groups()
        return f"{year}-{int(month):02d}-{int(day):02d}"
    if re.fullmatch(r"\d{8}", text):
        return f"{text[:4]}-{text[4:6]}-{text[6:8]}"
    return text


def _entry_fields(values: dict[str, object], strategy: str) -> tuple[str, float | None]:
    entry_time = _clean(_first(values, ["進場時間", "計畫進場時間", "掃描時間"]))
    entry_price = _number(_first(values, ["進場價格", "進場價", "參考進場價", "建議進場", "收盤價", "股價"]))
    combined = _clean(_first(values, ["進場"]))
    if combined:
        match = re.search(r"([^@]+)@\s*([\d.]+)", combined)
        if match:
            entry_time = entry_time or match.group(1).strip()
            entry_price = entry_price if entry_price is not None else _number(match.group(2))
    entry_time = entry_time or _entry_time_fallback(strategy)
    return entry_time, entry_price


def _entry_time_fallback(strategy: str) -> str:
    if strategy == "策略1成績單":
        return "09:00"
    if strategy == "策略3成績單":
        return "13:00"
    if strategy == "策略4成績單":
        return "訊號日"
    if strategy == "策略5成績單":
        return "未觸發"
    if strategy in {"買賣超成績單", "權證成績單"}:
        return "收盤價"
    if strategy == "CB成績單":
        return "模型進場"
    return "--"


def _first(values: dict[str, object], keys: list[str]) -> object:
    for key in keys:
        if key in values and values[key] not in ("", None):
            return values[key]
    return ""


def _clean(value: object) -> str:
    if value is None:
        return ""
    return str(value).replace("\u2009", " ").strip()


def _number(value: object) -> float | None:
    text = _clean(value).replace(",", "").replace("%", "")
    if not text or text == "--":
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _percent(value: object) -> float | None:
    number = _number(value)
    if number is None:
        return None
    return number * 100 if 0 < number <= 1 else number


def _result_from_pnl(pnl: float | None) -> str:
    if pnl is None:
        return ""
    if pnl > 0:
        return "獲利"
    if pnl < 0:
        return "虧損"
    return "平盤"

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import duckdb
import pandas as pd

from fuman_importer import create_fuman_schema, import_fuman_workbook


DB_PATH = Path(__file__).with_name("scorecard.duckdb")


@dataclass(frozen=True)
class BacktestConfig:
    holding_days: int = 5
    initial_capital: float = 100_000
    trade_notional: float = 10_000


def connect(db_path: Path = DB_PATH) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(str(db_path))
    create_schema(con)
    create_fuman_schema(con)
    import_fuman_workbook(con)
    return con


def create_schema(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(
        """
        create table if not exists prices (
            trade_date date not null,
            ticker varchar not null,
            open double not null,
            high double not null,
            low double not null,
            close double not null,
            volume bigint not null,
            primary key (trade_date, ticker)
        )
        """
    )
    con.execute(
        """
        create table if not exists signals (
            signal_date date not null,
            ticker varchar not null,
            strategy varchar not null,
            score double not null,
            reason varchar,
            primary key (signal_date, ticker, strategy)
        )
        """
    )
    con.execute(
        """
        create table if not exists trades (
            signal_date date not null,
            entry_date date not null,
            exit_date date not null,
            ticker varchar not null,
            strategy varchar not null,
            score double not null,
            entry_price double not null,
            exit_price double not null,
            shares double not null,
            pnl double not null,
            return_pct double not null,
            holding_days integer not null
        )
        """
    )


def run_backtest(con: duckdb.DuckDBPyConnection, config: BacktestConfig) -> pd.DataFrame:
    con.execute("delete from trades")
    trades = con.execute(
        """
        with price_rows as (
            select
                trade_date,
                ticker,
                close,
                row_number() over (partition by ticker order by trade_date) as rn
            from prices
        ),
        entries as (
            select
                s.signal_date,
                p.trade_date as entry_date,
                p.ticker,
                s.strategy,
                s.score,
                p.close as entry_price,
                p.rn as entry_rn
            from signals s
            join price_rows p
                on p.ticker = s.ticker
               and p.trade_date = s.signal_date
        ),
        exits as (
            select
                e.signal_date,
                e.entry_date,
                x.trade_date as exit_date,
                e.ticker,
                e.strategy,
                e.score,
                e.entry_price,
                x.close as exit_price
            from entries e
            join price_rows x
                on x.ticker = e.ticker
               and x.rn = e.entry_rn + ?
        )
        select
            signal_date,
            entry_date,
            exit_date,
            ticker,
            strategy,
            score,
            entry_price,
            exit_price,
            ? / entry_price as shares,
            (? / entry_price) * (exit_price - entry_price) as pnl,
            (exit_price / entry_price - 1) * 100 as return_pct,
            ? as holding_days
        from exits
        order by entry_date, ticker, strategy
        """,
        [
            config.holding_days,
            config.trade_notional,
            config.trade_notional,
            config.holding_days,
        ],
    ).df()

    if not trades.empty:
        con.register("new_trades", trades)
        con.execute("insert into trades select * from new_trades")
        con.unregister("new_trades")

    return trades


def load_table(con: duckdb.DuckDBPyConnection, table: str) -> pd.DataFrame:
    return con.execute(f"select * from {table}").df()


def strategy_summary(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    return con.execute(
        """
        select
            strategy,
            count(*) as trades,
            sum(case when pnl > 0 then 1 else 0 end) * 100.0 / count(*) as win_rate_pct,
            avg(return_pct) as avg_return_pct,
            median(return_pct) as median_return_pct,
            sum(pnl) as total_pnl,
            avg(pnl) as avg_pnl,
            min(pnl) as worst_trade,
            max(pnl) as best_trade,
            sum(case when pnl > 0 then pnl else 0 end)
                / nullif(abs(sum(case when pnl < 0 then pnl else 0 end)), 0) as profit_factor
        from trades
        group by strategy
        order by total_pnl desc
        """
    ).df()


def equity_curve(
    con: duckdb.DuckDBPyConnection,
    initial_capital: float,
    strategies: list[str] | None = None,
) -> pd.DataFrame:
    strategy_filter = ""
    params: list[object] = []

    if strategies:
        placeholders = ", ".join(["?"] * len(strategies))
        strategy_filter = f"where strategy in ({placeholders})"
        params.extend(strategies)

    return con.execute(
        f"""
        select
            exit_date,
            sum(pnl) as daily_pnl
        from trades
        {strategy_filter}
        group by exit_date
        order by exit_date
        """,
        params,
    ).df().assign(
        equity=lambda df: initial_capital + df["daily_pnl"].cumsum()
        if not df.empty
        else pd.Series(dtype=float)
    )

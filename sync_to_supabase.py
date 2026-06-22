from __future__ import annotations

import duckdb
import pandas as pd

from fuman_importer import create_fuman_schema, import_fuman_workbook
from supabase_client import load_config, prune_trade_records, upsert_strategy_summary, upsert_trade_records


def main() -> None:
    config = load_config(required=True)
    con = duckdb.connect(":memory:")
    create_fuman_schema(con)
    import_fuman_workbook(con)

    records = con.execute(
        """
        select
            record_id,
            record_date,
            strategy,
            ticker,
            name,
            entry_time,
            entry_price,
            high_price,
            pnl,
            source_sheet as source,
            reason
        from fuman_trade_records
        """
    ).df()

    summary = con.execute(
        """
        select
            current_date as summary_date,
            strategy,
            signals,
            backtestable,
            wins,
            losses,
            flats,
            win_rate_pct,
            total_pnl,
            avg_pnl,
            max_profit,
            max_loss,
            status,
            note,
            source_sheet as source
        from fuman_scorecard_daily
        """
    ).df()

    upsert_trade_records(config, _normalize_for_json(records))
    upsert_strategy_summary(config, _normalize_for_json(summary))
    prune_trade_records(config)
    print(f"Synced {len(records):,} trade records and {len(summary):,} strategy summaries.")


def _normalize_for_json(frame: pd.DataFrame) -> pd.DataFrame:
    normalized = frame.copy()
    for column in normalized.columns:
        if pd.api.types.is_datetime64_any_dtype(normalized[column]):
            normalized[column] = normalized[column].dt.strftime("%Y-%m-%d")
        else:
            normalized[column] = normalized[column].map(
                lambda value: value.isoformat() if hasattr(value, "isoformat") else value
            )
    return normalized


if __name__ == "__main__":
    main()

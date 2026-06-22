from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass
from datetime import date, timedelta
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pandas as pd


@dataclass(frozen=True)
class SupabaseConfig:
    url: str
    key: str

    @property
    def rest_url(self) -> str:
        return self.url.rstrip("/") + "/rest/v1"


def load_config(required: bool = False) -> SupabaseConfig | None:
    url = (os.getenv("SUPABASE_URL", "").strip() or _secret("SUPABASE_URL"))
    key = (
        os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
        or os.getenv("SUPABASE_ANON_KEY", "").strip()
        or _secret("SUPABASE_SERVICE_ROLE_KEY")
        or _secret("SUPABASE_ANON_KEY")
    )
    if url and key:
        return SupabaseConfig(url=url, key=key)
    if required:
        raise RuntimeError("Missing SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY or SUPABASE_ANON_KEY.")
    return None


def is_configured() -> bool:
    return load_config(required=False) is not None


def _secret(name: str) -> str:
    try:
        import streamlit as st

        value = st.secrets.get(name, "")
    except Exception:
        return ""
    return str(value).strip() if value else ""


def fetch_trade_records(config: SupabaseConfig, days: int = 30) -> pd.DataFrame:
    start = date.today() - timedelta(days=days)
    params = {
        "select": "record_id,record_date,strategy,ticker,name,entry_time,entry_price,high_price,pnl,source,reason",
        "record_date": f"gte.{start.isoformat()}",
        "order": "record_date.desc,strategy.asc,ticker.asc",
    }
    rows = _request_json(config, "GET", "trade_records", params=params)
    return pd.DataFrame(rows)


def fetch_mobile_trade_records(
    config: SupabaseConfig,
    strategy: str | None = None,
    days: int = 30,
    limit: int = 80,
) -> pd.DataFrame:
    start = date.today() - timedelta(days=days)
    params = {
        "select": "record_id,record_date,strategy,ticker,name,entry_time,entry_price,high_price,pnl,source,reason",
        "record_date": f"gte.{start.isoformat()}",
        "order": "record_date.desc,pnl.desc.nullslast,strategy.asc,ticker.asc",
        "limit": str(limit),
    }
    if strategy:
        params["strategy"] = f"eq.{strategy}"
    rows = _request_json(config, "GET", "trade_records", params=params)
    return pd.DataFrame(rows)


def fetch_strategy_summary(config: SupabaseConfig, days: int = 30) -> pd.DataFrame:
    start = date.today() - timedelta(days=days)
    params = {
        "select": "*",
        "summary_date": f"gte.{start.isoformat()}",
        "order": "summary_date.desc,strategy.asc",
    }
    rows = _request_json(config, "GET", "strategy_daily_summary", params=params)
    return pd.DataFrame(rows)


def upsert_trade_records(config: SupabaseConfig, records: pd.DataFrame) -> None:
    if records.empty:
        return
    frame = records[
        [
            "record_id",
            "record_date",
            "strategy",
            "ticker",
            "name",
            "entry_time",
            "entry_price",
            "high_price",
            "pnl",
            "source",
            "reason",
        ]
    ]
    for payload in _record_batches(frame, size=300):
        _request_json(
            config,
            "POST",
            "trade_records",
            payload=payload,
            query="on_conflict=record_id",
            extra_headers={"Prefer": "resolution=merge-duplicates"},
        )


def upsert_strategy_summary(config: SupabaseConfig, summary: pd.DataFrame) -> None:
    if summary.empty:
        return
    for payload in _record_batches(summary, size=300):
        _request_json(
            config,
            "POST",
            "strategy_daily_summary",
            payload=payload,
            query="on_conflict=summary_date,strategy",
            extra_headers={"Prefer": "resolution=merge-duplicates"},
        )


def prune_trade_records(config: SupabaseConfig) -> None:
    _request_json(config, "POST", "rpc/prune_trade_records", payload={})


def _request_json(
    config: SupabaseConfig,
    method: str,
    path: str,
    params: dict[str, str] | None = None,
    payload: object | None = None,
    query: str = "",
    extra_headers: dict[str, str] | None = None,
) -> object:
    query_parts = []
    if params:
        query_parts.append(urlencode(params))
    if query:
        query_parts.append(query)
    suffix = "?" + "&".join(query_parts) if query_parts else ""
    url = f"{config.rest_url}/{path}{suffix}"
    body = None if payload is None else json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
    headers = {
        "apikey": config.key,
        "Authorization": f"Bearer {config.key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if extra_headers:
        headers.update(extra_headers)

    request = Request(url, data=body, headers=headers, method=method)
    try:
        with urlopen(request, timeout=30) as response:
            raw = response.read().decode("utf-8")
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Supabase {method} {path} failed: {exc.code} {detail}") from exc

    if not raw:
        return []
    return json.loads(raw)


def _record_batches(frame: pd.DataFrame, size: int) -> list[list[dict[str, object]]]:
    rows = [_clean_record(row) for row in frame.to_dict("records")]
    return [rows[index : index + size] for index in range(0, len(rows), size)]


def _clean_record(record: dict[str, object]) -> dict[str, object]:
    return {key: _json_value(value) for key, value in record.items()}


def _json_value(value: object) -> object:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value

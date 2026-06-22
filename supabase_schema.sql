create table if not exists public.trade_records (
    record_id text primary key,
    record_date date not null,
    strategy text not null,
    ticker text not null,
    name text,
    entry_time text,
    entry_price numeric,
    high_price numeric,
    pnl numeric,
    source text,
    reason text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table if not exists public.strategy_daily_summary (
    summary_date date not null,
    strategy text not null,
    signals numeric,
    backtestable numeric,
    wins numeric,
    losses numeric,
    flats numeric,
    win_rate_pct numeric,
    total_pnl numeric,
    avg_pnl numeric,
    max_profit numeric,
    max_loss numeric,
    status text,
    note text,
    source text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    primary key (summary_date, strategy)
);

create index if not exists trade_records_date_idx
    on public.trade_records (record_date desc);

create index if not exists trade_records_strategy_date_idx
    on public.trade_records (strategy, record_date desc);

create index if not exists trade_records_ticker_idx
    on public.trade_records (ticker);

create or replace function public.touch_updated_at()
returns trigger
language plpgsql
as $$
begin
    new.updated_at = now();
    return new;
end;
$$;

drop trigger if exists trade_records_touch_updated_at on public.trade_records;
create trigger trade_records_touch_updated_at
before update on public.trade_records
for each row execute function public.touch_updated_at();

drop trigger if exists strategy_daily_summary_touch_updated_at on public.strategy_daily_summary;
create trigger strategy_daily_summary_touch_updated_at
before update on public.strategy_daily_summary
for each row execute function public.touch_updated_at();

create or replace function public.prune_trade_records()
returns void
language sql
as $$
    delete from public.trade_records
    where
        (strategy = '策略4成績單' and record_date < current_date - interval '30 days')
        or
        (strategy <> '策略4成績單' and record_date < current_date - interval '7 days');
$$;

alter table public.trade_records enable row level security;
alter table public.strategy_daily_summary enable row level security;

drop policy if exists "public read trade records" on public.trade_records;
create policy "public read trade records"
on public.trade_records
for select
using (true);

drop policy if exists "public read strategy summaries" on public.strategy_daily_summary;
create policy "public read strategy summaries"
on public.strategy_daily_summary
for select
using (true);

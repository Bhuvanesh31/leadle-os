-- schemas/0007_client_dashboard_snapshots.sql
-- One row per (client, cadence, period). metrics kept as jsonb (explore-first;
-- typed columns earned later). Powers WoW/MoM deltas in v1 and cross-client
-- percentile benchmarks in v2.
create table if not exists client_dashboard_snapshots (
    client       text not null,
    period_kind  text not null,          -- 'weekly' | 'monthly'
    period_end   date not null,
    rendered_at  timestamptz not null default now(),
    metrics      jsonb not null,
    primary key (client, period_kind, period_end)
);

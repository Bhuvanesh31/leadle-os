# Supabase migrations

Per the *explore-first schema* principle, migrations are added **per phase**, not upfront. We do not commit to typed schemas before observation.

## Convention

Migrations are numbered sequentially: `001_<topic>.sql`, `002_<topic>.sql`, etc. Each is forward-only; we don't write down-migrations because the data is replayable from raw_* if anything goes wrong.

## Planned migrations (per phase)

| File | Phase | What it does |
|---|---|---|
| `001_raw_landing.sql` | P0 | Five `raw_<source>` JSONB tables, identical shape: `(id, payload jsonb, ingested_at)` |
| `002_admin_scaffolding.sql` | P0 | `sync_state`, `unmatched_review`, `config_*` placeholders |
| `003_hubspot_typed.sql` | P1 | `stg_hubspot_*` and the first cut of `unified_account / contact / deal` — designed *after* `docs/data-shape/hubspot.md` is written |
| `004_lemlist_typed.sql` | P3 | `stg_lemlist_*` + extensions to `unified_touchpoint`, `unified_campaign` |
| `005_instantly_typed.sql` | P4 | Same shape |
| `006_aimfox_typed.sql` | P5 | Same shape, plus `unified_signal` table |
| `007_fathom_typed.sql` | P6 | `stg_fathom_*` and `unified_call` (transcripts heavy by token volume — chunking strategy decided in P6) |
| `008_dashboard_views.sql` | P7 | Materialized views feeding dashboard sections |

## Schema namespace

Decision deferred to P1: `public.*` if Supabase is empty, `leadle_os.*` if it's shared with other Leadle work. All migrations after P0 use schema-qualified names so this is easy to switch.

## Don't write migrations ahead of their phase

A migration without observation context tends to be wrong. The phases earn their schemas.

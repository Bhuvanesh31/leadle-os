# Leadle OS

[![CI](https://github.com/Bhuvanesh31/leadle-os/actions/workflows/ci.yml/badge.svg)](https://github.com/Bhuvanesh31/leadle-os/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/)
[![License: Proprietary](https://img.shields.io/badge/license-Proprietary-red)](LICENSE)

Internal RevOps operating system for Leadle — a Chennai-based B2B GTM agency. Reads
HubSpot, Instantly, Fathom, Aimfox, and Lemlist; runs 17 repeatable analytics processes;
renders a live dashboard and daily Slack brief for the sales and RevOps team.

## What's working now

- **17 analytics processes** — lead scoring, deal rotting, pipeline leakage, lost-deal
  clustering, ICP correction, source attribution, campaign performance, CRM gap detection
- **Dashboard renderer** — Jinja2 template with 4 LLM-written narrative sections,
  hosted as a Supabase Storage signed URL
- **Client report renderer** — per-engagement deliverable from the same pipeline
- **Slash commands** — every process is callable as a `/command` in Claude Code

See [`CHANGELOG.md`](CHANGELOG.md) for the full history.

## Quick start

```bash
cp .env.example .env      # fill in credentials (HubSpot, Slack, Instantly, Fathom)
uv sync --extra dev       # install dependencies
python -m analytics.lead_rotting --period last-month   # run your first analysis
```

Required env vars: `HUBSPOT_PRIVATE_TOKEN`, `SLACK_BOT_TOKEN`, `SUPABASE_URL`,
`SUPABASE_KEY`, `INSTANTLY_API_KEY`, `FATHOM_API_KEY`

## Architecture

Analytics scripts pull live from source APIs on demand. Four LLM agents (Claude Sonnet)
handle narrative reasoning; the remaining 13 processes are deterministic Python scripts.
A custom local-stdio MCP server (`leadle_os_mcp`) exposes semantic analytics tools to
Claude. Scheduling via Claude Code CronCreate — no Leadle-hosted compute.

Supabase is used for dashboard hosting (Storage signed URLs). Raw data sync to Supabase
was evaluated and deliberately deferred — see
[`docs/decisions/2026-06-22-supabase-raw-sync-deferred.md`](docs/decisions/2026-06-22-supabase-raw-sync-deferred.md).

## Documentation

- [`CLAUDE.md`](CLAUDE.md) — conventions and architectural principles (read first)
- [`docs/superpowers/specs/2026-05-05-leadle-os-design.md`](docs/superpowers/specs/2026-05-05-leadle-os-design.md) — full design spec
- [`docs/decisions/`](docs/decisions/) — architecture decision records
- [`docs/data-shape/`](docs/data-shape/) — per-source field observations
- [`config/`](config/) — operational rules in YAML (signals, ICP, thresholds)

## Analytics processes

| Command | Script | Purpose |
|---|---|---|
| `/inbound-lead-analysis` | `analytics/inbound_lead_analysis.py` | Lead health by stage, age, owner |
| `/inbound-lead-scoring` | `analytics/inbound_lead_scoring.py` | ICP score — 4 dimensions, 100pt |
| `/outbound-lead-analysis` | `analytics/outbound_lead_analysis.py` | Outbound pipeline health |
| `/outbound-lead-scoring` | `analytics/outbound_lead_scoring.py` | ICP score outbound leads |
| `/source-attribution` | `analytics/source_attribution.py` | Lead source mix and conversion |
| `/lead-rotting` | `analytics/lead_rotting.py` | Two-signal rot: activity + stage |
| `/lead-pipeline-leakage` | `analytics/lead_pipeline_leakage.py` | Stage drop-off funnel |
| `/lead-pipeline-rotting` | `analytics/lead_pipeline_rotting.py` | Aggregate rot by stage |
| `/deal-rotting` | `analytics/deal_rotting.py` | Deal rot (activity + stage) |
| `/deal-pipeline-leakage` | `analytics/deal_pipeline_leakage.py` | Deal stage drop-off |
| `/deal-pipeline-rotting` | `analytics/deal_pipeline_rotting.py` | Deal rot by stage |
| `/outbound-campaign-perf` | `analytics/outbound_campaign_perf.py` | Aimfox + Instantly metrics |
| `/inbound-perf` | `analytics/inbound_perf.py` | Inbound funnel conversion |
| `/hubspot-dedupe-find` | `analytics/hubspot_dedupe_find.py` | Duplicate contact/company finder |
| `/icp-corrector` | `analytics/icp_corrector.py` | Flag mis-staged leads |
| `/lost-deals` | `analytics/lost_deals.py` | Lost deal clusters + stage-of-loss |
| `/fathom-crm-gap` | `analytics/fathom_crm_gap.py` | Calls with no CRM record |

All scripts accept `--period last-month`, `--period last-quarter`, or `--start`/`--end`.

## Phase progression

Core phases P0–P8, then extensions E1–E3. Phase-gated, not time-gated — each phase has
explicit "done when" criteria in the spec.

**Current:** P7 (dashboard renderer) complete. P8 (automation + Sai brief) next.

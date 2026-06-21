# Changelog

All notable changes to Leadle OS are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

---

## [Unreleased]

### In progress
- P8 Automation — CronCreate for 08:00 IST daily brief + dashboard render
- `/brief-sai` — Slack DM to Sai with 5 prioritized opportunities

---

## [0.3.0] — 2026-06-21

### Added — 17 repeatable analytics processes

All processes have a matching `.claude/commands/` slash command and output
HTML to `reports/` plus optional `--json FILE` for machine use.

| Command | What it does |
|---|---|
| `/inbound-lead-analysis` | Lead health by stage, age, owner |
| `/inbound-lead-scoring` | ICP score all inbound leads (4 dimensions, 100pt) |
| `/outbound-lead-analysis` | Pipeline health for outbound leads |
| `/outbound-lead-scoring` | ICP score outbound leads |
| `/source-attribution` | Lead source mix and conversion by source |
| `/lead-rotting` | Two-signal rot: activity_stalled + stage_stuck |
| `/lead-pipeline-leakage` | Stage drop-off funnel, where leads die |
| `/lead-pipeline-rotting` | Aggregate rot by pipeline stage |
| `/deal-rotting` | Same two-signal rot model for deals |
| `/deal-pipeline-leakage` | Stage drop-off for deals |
| `/deal-pipeline-rotting` | Aggregate rot by deal stage |
| `/outbound-campaign-perf` | Aimfox (LinkedIn) + Instantly (email) campaign metrics |
| `/inbound-perf` | Inbound funnel conversion over a window |
| `/hubspot-dedupe-find` | Duplicate contacts/companies finder |
| `/icp-corrector` | Flag HOT_UNDERSTAGED, COLD_OVERSTAGED, ENRICHMENT_GAP leads |
| `/lost-deals` | Lost deal volume, reason clusters, stage-of-loss, avg days in pipe |
| `/fathom-crm-gap` | Fathom discovery calls with no HubSpot contact/lead/deal |

### Added — Dashboard renderer
- Jinja2 template (`dashboard/templates/dashboard-v2.html`) with 12 data blocks
- Four LLM agents (Sonnet) for narrative sections: pipeline health, engagement, signals, actions
- `/render-dashboard` command — regenerates and uploads to Supabase Storage
- `/render-client-report` command — per-client deliverable renderer

### Architectural decision
- **Supabase raw data sync deferred** — analytics scripts pull live from source APIs.
  Rationale: CRM data changes continuously (stale cache = wrong signals), scripts run
  in under 30s, single-user context. Supabase retained for dashboard hosting (Storage)
  only. See `docs/decisions/2026-06-22-supabase-raw-sync-deferred.md`.

---

## [0.2.0] — 2026-05-09

### Added — Dashboard fasttrack
- Dashboard design spec + implementation plan
- Jinja2 template scaffolding
- Compute modules for each dashboard block

---

## [0.1.0] — 2026-05-05

### Added — Foundation
- Full design spec: `docs/superpowers/specs/2026-05-05-leadle-os-design.md`
- Repo scaffold: agents/, analytics/, connectors/, dashboard/, identity/, leadle_os_mcp/
- Config system: YAML files for signals, ICP definitions, phantom rules, voice
- `pyproject.toml` with full dependency manifest
- `CLAUDE.md` — conventions and architectural principles

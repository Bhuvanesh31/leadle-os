# Leadle OS

Internal RevOps operating system for Leadle. Reads HubSpot, Lemlist, Aimfox, Instantly, Fathom into Supabase, runs analyses, ships a daily Slack brief to Sai and a live dashboard for the team.

## Status

Phase 0 (Foundation) — scaffolding. Active design spec at [`docs/superpowers/specs/2026-05-05-leadle-os-design.md`](docs/superpowers/specs/2026-05-05-leadle-os-design.md).

## Quick start

```bash
# Once Phase 0 is implemented:
cp .env.example .env        # fill in credentials
uv sync                      # or: pip install -e .
python -m smoke.test         # verifies Supabase, Slack, HubSpot MCP connectivity
```

## Architecture in one paragraph

Five connectors land raw JSONB into Supabase. Eight agents (Claude reasoning) and six scripts (deterministic Python) read the unified tables. A custom local-stdio MCP server (`leadle_os_mcp`) exposes semantic analytics tools to Claude. Scheduled runs via Claude Code `/schedule` (CronCreate) post the daily brief to Sai's Slack DM and regenerate the dashboard. No Leadle-hosted compute beyond Supabase.

## Documentation

- [`CLAUDE.md`](CLAUDE.md) — conventions and principles for any Claude session in this repo
- [`docs/superpowers/specs/2026-05-05-leadle-os-design.md`](docs/superpowers/specs/2026-05-05-leadle-os-design.md) — full design spec
- [`docs/data-shape/`](docs/data-shape/) — per-source data observations (added per phase)
- [`config/`](config/) — operational rules in YAML

## Phase progression

Core build P0 → P8, then extensions E1–E3. Each phase has explicit "done when" criteria in the spec; the progression is intentionally phase-gated rather than time-bound.

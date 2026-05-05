# Slash commands

User-facing entry points for Claude Code sessions. Each command is a markdown file that Claude treats as a prompt + permitted tool calls.

## Conventions

- One verb per command. `/sync-all`, `/brief-sai`, `/dashboard`, `/stuck`, `/signals` — each does one clear thing.
- Optional arguments refine, never expand: `/stuck --owner=Sai --stage=proposal`.
- Commands that mutate state (e.g., sync) should be safely re-runnable (idempotent).
- Commands compose: `/sync-all` then `/brief-sai` is a valid manual flow before P8 automation lands.

## Planned commands (added per phase)

| Command | Phase | What it does |
|---|---|---|
| `/sync-all` | P0/P1 | Run all 5 connector syncs in parallel; advance cursors; report freshness |
| `/sync-<source>` | per-source phase | Sync a single source — useful while iterating on one connector |
| `/brief-sai` | P1 | Compose and post the daily brief to Sai's Slack DM |
| `/dashboard` | P7 | Regenerate the dashboard, upload to Supabase Storage, return signed URL |
| `/stuck` | P2 | List stuck/rotting deals with reasoning |
| `/phantoms` | P1 | Surface phantom-pipeline deals with kill/keep recommendations |
| `/signals` | P5 | Show the current 48-hr hot signal feed |
| `/insights` | P6 | Trigger the weekly Sales Insight Digest on demand |
| `/freshness` | P0 | Report `data_freshness()` per source |

Slash commands are scaffolding for human use. Scheduled runs (P8) call the underlying agents/scripts directly via CronCreate, not via slash commands.

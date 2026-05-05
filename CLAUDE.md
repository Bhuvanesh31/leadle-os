# CLAUDE.md — Leadle OS project memory

This file is loaded into every Claude Code session in this repo. It establishes the conventions, principles, and quick-reference details a session needs before touching anything.

## What this project is

Leadle OS is the internal RevOps operating system for Leadle (a Chennai-based B2B GTM agency transitioning into RevOps-as-a-Service). It reads from Leadle's tool stack — HubSpot, Lemlist, Aimfox, Instantly, Fathom — into Supabase, runs analyses, and delivers a daily Slack brief to Sai (Sales Head) plus a live dashboard for Bhuvanesh and Akil.

The canonical design lives at `docs/superpowers/specs/2026-05-05-leadle-os-design.md`. **Read it before making any architectural change.** This file is the executive summary, that file is the spec.

## Who uses this

- **Bhuvanesh** (RevOps Architect, the user) — operates the system in Claude Code.
- **Sai** (Sales Head) — passive consumer; receives the daily brief in Slack DM.
- **Akil** (Head of RevOps) — consumes the regenerated dashboard URL.
- **Bhuvaneswari** (Head of Marketing), **Harinie** (Founder), **Suraj** (COO) — peripheral consumers via the Sales Insight Digest weekly post.

Phase 1 is single-user (Bhuvanesh). Don't add user-management complexity.

## Architectural principles (non-negotiable)

These are stated more fully in the spec; this is the operational summary you must follow when proposing changes.

1. **Impact-based agent vs. script.** New component is an *agent* (uses Claude reasoning) iff inputs include unstructured text or judgment, or output requires narrative reasoning, or misclassification has high revenue cost. Otherwise it's a *script* (deterministic Python). Don't invert this — agents on deterministic problems waste tokens, scripts on judgment problems produce sharp-edged garbage.
2. **Explore-first schema.** Never propose a typed schema for a new data source before someone has pulled real data and produced `docs/data-shape/<source>.md`. Raw JSONB landing zones first, typed tables earned in-context.
3. **Claude Code as compute.** No hosted services beyond Supabase. Compute is on-demand (interactive session) or scheduled (Claude Code `/schedule` running on Anthropic infra). Don't propose Fly.io, Railway, VMs, Docker hosting.
4. **Two MCP layers, distinct roles.** HubSpot MCP (vendor, claude.ai-managed) is the *ingestion* path for HubSpot — required because Marketing Hub Starter + Sales Hub Pro tier limits make programmatic API scripts insufficient. leadle-os MCP (custom, local stdio) is the *analytics* surface.
5. **Config-driven, not hard-coded.** Brief sections, signal triggers, ICP definitions, phantom thresholds — all live in `config/*.yaml`. Editing operational behavior should never require a code change.
6. **Phase-gated, not time-gated.** Each phase has explicit "done when" criteria in the spec. Don't half-finish a phase to start the next.
7. **Read-only against source systems.** No writes to HubSpot, Lemlist, Aimfox, Instantly, or Fathom. The system observes; humans act.
8. **Signal-to-Motion is the modeling vocabulary.** 4 buying postures, 8 action types, account tiers (Suspect / Prospect / High Priority Prospect). Use these terms in agent prompts and config — they're Leadle's IP.

## Repo layout

```
agents/                Agent implementations (Claude reasoning + Python orchestration)
analytics/             Script-based queries (deterministic, pure Python/SQL)
connectors/<source>/   Per-source ingestion. HubSpot is special: agent-orchestrated via MCP.
identity/              Identity resolution (Clay-IDs script + edge-case agent)
leadle_os_mcp/         Local stdio MCP server exposing semantic analytics tools
dashboard/templates/   Jinja templates for the regenerated dashboard
config/                YAML config files (brief_sections, signals, phantom_rules, icp_per_offer, voice)
schemas/               Supabase migrations — added per phase, not upfront
docs/data-shape/       Per-source data observations (P1 deliverable per source)
docs/superpowers/      Design specs and implementation plans
reports/               Generated outputs (gitignored except .gitkeep)
.claude/commands/      Slash commands (markdown files)
.claude/skills/        Local Leadle OS skills
smoke/                 Smoke tests for end-to-end plumbing
tests/                 Unit + integration tests
```

## How to think about adding things

| Want to add | Right place | Right type | Note |
|---|---|---|---|
| A new analysis on existing data | `agents/<name>/` if narrative/judgment; `analytics/` if pure SQL | Match the impact rule | Don't reach for an agent because it's more interesting |
| A new source | `connectors/<source>/` after producing `docs/data-shape/<source>.md` | Script (REST APIs); agent-orchestrated only for tier-restricted vendors like HubSpot | Land raw JSONB first; design typed schemas only after observation |
| A new threshold or rule | `config/<file>.yaml` | Config | Code changes for rules are a smell — they belong in YAML |
| A new dashboard section | `dashboard/templates/` + `config/dashboard_layout.yaml` | Template + config | Layout is `dashboard-v2.html` — respect the existing structure |
| A new slash command | `.claude/commands/<name>.md` | Markdown | Keep one verb per command; arg-light surfaces get used, arg-heavy ones don't |
| A new scheduled routine | Claude Code `/schedule` (CronCreate) | Anthropic-hosted cron | No Leadle-hosted compute |

## Tool stack quick reference

| Tool | Role at Leadle | Access |
|---|---|---|
| HubSpot | CRM (system of record). Marketing Hub Starter + Sales Hub Pro. | **HubSpot MCP** (claude.ai vendor MCP). NOT private app token — tier limits force MCP. |
| Lemlist | Multi-channel orchestration; account-based outbound campaigns | REST API |
| Aimfox | LinkedIn-only outbound | REST API + webhooks (existing Clay→HubSpot pipeline uses webhooks) |
| Instantly | Email-only outbound | REST API; surfaces inbox-placement signal (unique) |
| Fathom | Call recording (Leadle's own + client delivery review calls) | REST API; transcripts heavy by token volume |
| Clay / Claygent | Enrichment + signal detection. **Injects HubSpot company_id + contact_id as custom fields** into Lemlist/Aimfox/Instantly leads — this is the identity resolution backbone. | (External — Leadle ops, not in this repo) |
| Slack | Internal comms; brief delivery; ops heartbeat | Slack Bot Token via env |
| Supabase | Storage + state + dashboard hosting (Storage signed URLs) | env vars |

## Identity resolution shape

The 5%-edge-case path is a small agent. **The 95% path is a script** that reads `hubspot_company_id` and `hubspot_contact_id` from custom fields injected by Clay during enrichment. Don't reinvent this — Leadle has done the upstream work to make matching trivial. Only fall through to fuzzy matching when Clay IDs are absent.

## Read-only invariant

This system **never writes** to HubSpot or any source tool in Phase 1. Composed signals (engagement scores, buying posture, recommended action) live in Supabase and surface in the dashboard + brief — they do *not* propagate back to HubSpot custom properties. If you find yourself proposing a write, check the spec — it's deliberate.

## Cost discipline

We use Sonnet for narrative reasoning, Haiku for pre-filtering and high-volume light classification. **Don't reach for Sonnet on Haiku-class problems.** The cost envelope is in the spec; HubSpot MCP orchestration is the single biggest line item, so reducing sync frequency is the first lever to pull if costs surprise.

## Voice and tone (for agent outputs)

Per `LEADLE_CONTEXT.md`, Leadle's tone is conversational, thinking-out-loud, dry humor, short sentences. **Forbidden patterns** in any user-facing output (brief, digest, dashboard copy):

- AI-sounding phrases (delve, leverage, unlock, ecosystem, etc.)
- Listy structure where prose would be sharper
- Preachy endings
- Em dashes (use parens, colons, or new sentences)
- Micro-sentences as filler
- Captions that summarize instead of adding POV

The Sai brief and Sales Insight Digest both pass through these constraints. Agent prompts should encode them; downstream we may add an AI-Pattern Sniffer (Extension E3) to enforce them automatically.

## Where to start (if you're new to this repo)

1. Read this file (you're here).
2. Read `docs/superpowers/specs/2026-05-05-leadle-os-design.md` end-to-end.
3. Read `LEADLE_CONTEXT.md` (kept by the user at `/home/bhuvanesh/Downloads/LEADLE_CONTEXT.md`) for the agency context.
4. Look at the dashboard mock — `/home/bhuvanesh/Downloads/leadle-dashboard-v2.html` — to see the output structure we're producing.
5. Check the current phase. P0 is foundation; everything else assumes P0 is done.

## Things that look wrong but aren't

- **Agents and scripts side by side in the same flow.** Yes, on purpose. Per the impact rule, mixing is correct.
- **Two MCP servers when one would seem enough.** Yes, on purpose. Different roles (ingest vs. analytics).
- **Raw JSONB tables as first-class storage.** Yes, on purpose. Schema-on-read first, schema-on-write earned.
- **No write-back to HubSpot.** Yes, deliberate Phase 1 constraint. Will be reconsidered after Phase 1.
- **No always-on hosting.** Yes, by design. CronCreate covers scheduling; nothing else needs hosting.

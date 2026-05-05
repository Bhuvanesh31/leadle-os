# Leadle OS — Design Specification

| | |
|---|---|
| **Status** | Draft v1 — approved for implementation planning |
| **Date** | 2026-05-05 |
| **Owner** | Bhuvanesh (revops@leadle.in) |
| **Scope** | Phase 1 of the Leadle internal RevOps operating system |
| **Source docs** | `LEADLE_CONTEXT.md`, `leadle-revenue-engine-onepager.html`, `leadle-dashboard-v2.html`, `leadle-pipeline-action-plan.html` |

---

## 0. Why this exists

Leadle's pipeline accuracy, signal response, and revenue intelligence currently depend on manual processes that don't scale past one busy week. The April-30 Pipeline Action Plan diagnosed the cost: of ~20 active discovery calls, only 4–5 are genuine opportunities. Site-visitor ICP fitment sits at 30%, discovery-call revenue match at 40–45%, RevOps-intent discoveries at zero in the last 20.

This OS automates the highest-impact reads and analyses across HubSpot, Lemlist, Aimfox, Instantly, and Fathom — surfacing what matters to the right person at the right time, without writing back to source systems.

The product is two things, working together:

1. **A daily Slack brief to Sai** — the 5 real opportunities, what changed since yesterday, what to act on today.
2. **A live dashboard for Bhuvanesh and Akil** — the structure already designed in `dashboard-v2.html`, regenerated daily from current data.

Phase 1 success metric: revenue match rate on booked calls from 40–45% → 75%+ by end of May, with every 48-hr hot signal surfaced automatically.

---

## 1. Scope

### 1.1 In scope (Phase 1 Core Build)

- Read-only ingestion from HubSpot, Lemlist, Aimfox, Instantly, Fathom.
- Identity resolution via Clay-injected HubSpot company/contact IDs (primary path).
- 8 agents (high-impact + judgment) and 6 deterministic scripts, plus 1 hybrid (HubSpot connector — agent-orchestrated via MCP).
- 2 MCP layers: HubSpot vendor MCP for ingest, leadle-os custom MCP for analytics.
- Daily Sai brief to Slack.
- Live dashboard rendered to Supabase Storage with signed URL.
- Scheduled automation via Claude Code `/schedule` (CronCreate).
- Single user: Bhuvanesh. Sai is a consumer-only via Slack.

### 1.2 Out of scope (Phase 1)

- Writing to HubSpot or any source system (read-only).
- Always-on hosting — no Fly.io, Railway, VMs.
- Real-time webhooks (revisit post-P8 only if necessary).
- Multi-user authoring access.
- Live client data — deferred to Extension E2.
- Marketing tab and asset generators — Extensions E1, E3.
- Mobile UI.
- Bidirectional sync of any kind.

### 1.3 Decisions deferred to specific phases

- Existing Supabase namespace (decided at P1 schema-design step).
- Time budget (no commitment; phase-by-phase progression).
- Webhook reintroduction (revisit only if 24-hr cadence proves insufficient).

---

## 2. Architectural principles

Non-negotiable across all phases:

1. **Impact-based agent vs. script.** Component is an *agent* (uses Claude reasoning) iff (a) inputs include unstructured text or judgment-bearing data, (b) output requires narrative or contextual reasoning, or (c) misclassification has high revenue cost. Otherwise it's a *script* (deterministic Python).
2. **Explore-first schema.** New data sources land into raw JSONB tables. Typed staging and unified schemas are designed *only after* observation, documented in `docs/data-shape/<source>.md`.
3. **Claude Code as compute.** No hosted services beyond Supabase. Compute is on-demand (interactive Claude Code session) or scheduled (Claude Code `/schedule` running on Anthropic infrastructure).
4. **Two MCP layers.** HubSpot MCP (vendor, claude.ai-managed) is the data ingestion path for HubSpot due to tier-imposed API limits. leadle-os MCP (custom, local stdio) is the analytics surface Claude reads through.
5. **Config-driven over hard-coded.** Operational rules — brief sections, signal triggers, ICP definitions, phantom thresholds — live in YAML files Bhuvanesh edits without touching code.
6. **Phase-gated, not time-gated.** Each phase has explicit "done when" criteria. No deadlines.
7. **Read-only against source systems.** Writes back are out of scope for Phase 1.
8. **Signal-to-Motion is the modeling vocabulary.** Account postures (4), action types (8), and segmentation tiers (Suspect / Prospect / High Priority Prospect) are the conceptual primitives.
9. **Three Engines is the output framing.** Volume Engine, Trust Engine, Conversion Engine — agents tag outputs with engine context where it shapes interpretation.

---

## 3. Architecture

```
                        ┌─ DATA INGESTION ─────────────────┐
                        │                                   │
HubSpot ─── HubSpot MCP ◄── orchestrated by Claude          │
            (vendor; bypasses tier-locked APIs)             │
Lemlist  ─┐                                                  │
Aimfox   ─┼─ Python connector scripts                        │
Instantly┤   (REST APIs, no tier issues)                     │
Fathom   ─┘                                                  │
                                                             │
            Sync Coordinator script orchestrates all 5       │
                        └────────────┬─────────────────────┘
                                     ▼
                ┌───────────────────────────────────────┐
                │ SUPABASE                               │
                │  raw_*           JSONB landing zones   │
                │  stg_*           typed staging         │
                │  unified_*       Account, Contact,     │
                │                  Deal, Touchpoint,     │
                │                  Call, Campaign, Signal│
                │  unmatched_review identity edge cases  │
                │  sync_state      per-source cursors    │
                │  config_*        YAML loaded on read   │
                └───────────────┬───────────────────────┘
                                ▼
   ┌────────────────────────────────────────────────────────┐
   │ ANALYTICAL LAYER                                        │
   │                                                         │
   │  Agents (Claude reasoning, judgment-bearing):           │
   │   • Phantom Detector                                    │
   │   • Signal Detector                                     │
   │   • CRM Hygiene Auditor                                 │
   │   • Outreach Health Monitor                             │
   │   • Funnel Leak Detector                                │
   │   • Identity Resolver (edge cases only)                 │
   │   • Sai Daily Brief Composer                            │
   │   • Sales Insight Digest (weekly)                       │
   │                                                         │
   │  Scripts (deterministic):                               │
   │   • Sync Coordinator                                    │
   │   • Identity Resolver (Clay-IDs path)                   │
   │   • Channel Attribution Analyzer                        │
   │   • Lemlist / Aimfox / Instantly / Fathom connectors    │
   │   • Dashboard Renderer (Jinja templating)               │
   │                                                         │
   │  ◄── leadle-os MCP server (custom, local stdio) ──►    │
   │       Tools: pipeline_health(), phantom_deals(),        │
   │       signal_to_motion_score(account_id),               │
   │       stuck_deals(stage, days), data_freshness(), ...   │
   └────────────────────┬──────────────────────────────────┘
                        ▼
        ┌─────────────────────────────────────────────────┐
        │ COMPOSITION & DELIVERY                            │
        │  • Sai Daily Brief (agent) → Slack DM             │
        │  • Dashboard rebuild (script) → Supabase Storage  │
        │  • Ops heartbeat (script) → #leadle-os-ops Slack  │
        └────────────────────┬────────────────────────────┘
                             ▼
        ┌─────────────────────────────────────────────────┐
        │ SCHEDULING                                        │
        │  Claude Code /schedule → CronCreate:              │
        │   08:00 IST daily — full sync + brief + dashboard │
        │   Mondays 09:00 IST — Sales Insight Digest        │
        │  Anthropic-hosted; no Leadle compute.             │
        └─────────────────────────────────────────────────┘
```

---

## 4. Component inventory

### 4.1 Agents (8 components)

| Agent | Purpose | Primary inputs | Primary output | Model class | Cadence |
|---|---|---|---|---|---|
| **Phantom Detector** | Surface deals that look real but aren't (revenue mismatch, evaluator-only, below ICP, stalled at proposal) | unified_deal, unified_contact, Fathom transcripts | Ranked list with reasoning per deal | Sonnet | Daily |
| **Signal Detector** | Detect 48-hr hot signals: RevOps/Sales-Ops hires, VP Sales hires, funding rounds; classify ICP fit per offer | LinkedIn job-post feeds, news APIs, Aimfox profile data | Prioritized account list with hours-since-signal | Haiku pre-filter + Sonnet for final classification | Daily (twice if cost permits) |
| **CRM Hygiene Auditor** | Detect duplicates, judge master record, flag stale/missing-field deals, identify CRM-Fathom gaps | unified_contact, unified_company, unified_deal, unified_call | Hygiene report with recommendations and confidence tiers | Sonnet | Weekly + on-demand |
| **Outreach Health Monitor** | Narrate campaign anomalies with root-cause hypotheses (reply-rate dips, inbox-placement decay, sequence stalls, follow-up gaps) | unified_campaign, unified_touchpoint | Per-campaign narrative + recommended actions | Sonnet | Daily |
| **Funnel Leak Detector** | Interpret stage-by-stage drop-off in context (transient vs. structural; likely cause) | unified_deal, unified_touchpoint | Leak narrative with actionable hypothesis | Sonnet | Weekly |
| **Identity Resolver (edge cases)** | Resolve unmatched records via fuzzy matching when Clay-injected IDs are absent | unmatched_review queue | Resolved or escalated records | Haiku | On-demand (low volume) |
| **Sai Daily Brief Composer** | Synthesize the morning brief in voice; prioritize by impact; surface "ONE THING TODAY" | All agent outputs from preceding day | Slack-formatted markdown brief, ≤ 500 words | Sonnet | Daily 08:00 IST |
| **Sales Insight Digest** | Mine Fathom transcripts + Lemlist replies for top objections, language patterns, what messaging resonates | unified_call (transcripts), unified_touchpoint | Weekly cross-pollination digest for marketing+sales channel | Sonnet (large context) | Weekly Monday 09:00 IST |

### 4.2 Scripts (6 components)

| Script | Purpose | Inputs | Output |
|---|---|---|---|
| **Sync Coordinator** | Orchestrate all 5 connectors with parallel dispatch, handle per-source failure isolation | sync_state cursors | Per-source completion records, dead-letter rows |
| **Identity Resolver (Clay-IDs path)** | Read Clay-injected `hubspot_company_id` + `hubspot_contact_id` from custom fields, populate unified IDs (HIGH confidence) | raw_<source> JSONB | unified_account / unified_contact rows + unmatched_review for misses |
| **Channel Attribution Analyzer** | Tag deals with channel-of-origin, sum revenue/pipeline by channel, compute ACV per channel | unified_deal, unified_touchpoint | Channel-level rollups feeding Tab 1 §04, §05 |
| **Lemlist / Aimfox / Instantly / Fathom connectors** | Pull incremental data via REST, write to raw_<source>, advance cursor | API tokens | raw_<source> rows + sync_state update |
| **Dashboard Renderer** | Jinja-template `dashboard-v2.html` against unified data, upload to Supabase Storage with signed URL | All unified_* tables, agent outputs | HTML file with bookmark-able URL |
| **Ops Heartbeat** | Post run-completion + freshness summary to #leadle-os-ops; alert on missed delivery | sync_state, run logs | Slack messages |

### 4.3 MCP servers (2)

| Server | Origin | Role | Why |
|---|---|---|---|
| **HubSpot MCP** | Vendor (claude.ai-managed) | Data *ingestion* layer for HubSpot. Reads contacts, companies, deals, engagements, properties, pipelines | Marketing Hub Starter + Sales Hub Pro tier-imposed API limits make programmatic scripts insufficient for the breadth of read access required |
| **leadle-os MCP** | Custom, local stdio | *Analytics* layer. Exposes semantic tools (`pipeline_health`, `phantom_deals`, `signal_to_motion_score`, `stuck_deals`, `data_freshness`) that read from Supabase | Stable interface for Claude reasoning; future-proofs against multi-consumer (Slack bot, Cursor, etc.) |

### 4.4 HubSpot connector (1 hybrid component)

The HubSpot connector is neither a pure agent nor a pure script — it's **agent-orchestrated**. Claude calls HubSpot MCP tools to read contacts/companies/deals/engagements with full property coverage, then a deterministic post-step writes the payloads to `raw_hubspot` and advances `sync_state`. It's documented separately because (a) the orchestration uses Claude reasoning (which a pure script wouldn't), but (b) the reasoning is mechanical (decide what to fetch next), not narrative. This hybrid shape exists only because the tier-imposed HubSpot API constraints force the MCP path; the other four sources are pure scripts.

---

## 5. Data flow

### 5.1 Phase 1 (HubSpot only)

```
HubSpot ── Claude orchestrates HubSpot MCP ──► raw_hubspot (JSONB)
                                                    │
              docs/data-shape/hubspot.md ◄── observation step
                                                    │
                                              (decision)
                                                    ▼
                            unified_account / unified_contact / unified_deal
                                                    │
                                                    ▼
                            Phantom Detector + Sai Brief Composer
                                                    │
                                                    ▼
                                          Slack DM to Sai
```

### 5.2 Phase 3+ (multi-source, identity-resolved)

```
HubSpot ─┐
Lemlist ─┤                     ┌─ raw_<source> (JSONB landing) ─┐
Aimfox  ─┼─► Sync Coordinator ─┤                                │
Instantly┤                     └────────────┬────────────────────┘
Fathom  ─┘                                  │
                                            ▼
                              Identity Resolver (Clay-IDs script
                                + edge-case agent for unmatched)
                                            │
                                            ▼
                              stg_<source>_* → unified_*
                                            │
                              ┌─────────────┴──────────────┐
                              ▼                            ▼
                         Agents                       Scripts
                              │                            │
                              └─────────────┬──────────────┘
                                            ▼
                              Sai Brief / Dashboard / Insight Digest
```

---

## 6. Storage model

### 6.1 Phase 0 — minimal foundation

```sql
-- One per source, identical shape
raw_hubspot (
  id            text primary key,
  payload       jsonb not null,
  ingested_at   timestamptz default now()
);
raw_lemlist (...same...);
raw_aimfox (...same...);
raw_instantly (...same...);
raw_fathom (...same...);

-- Admin scaffolding
sync_state (
  source        text primary key,
  cursor        text,
  last_synced_at timestamptz,
  last_status   text,
  last_error    text
);

unmatched_review (
  id            uuid primary key default gen_random_uuid(),
  source        text not null,
  payload       jsonb not null,
  match_keys    jsonb not null,    -- linkedin_slug, email_domain, etc.
  match_attempt jsonb,             -- what we tried
  resolved      boolean default false,
  resolved_to   uuid,              -- → unified_account.id when resolved
  flagged_at    timestamptz default now()
);

config_brief_sections (...)         -- loaded from YAML; values mirror file
config_signals (...)
config_phantom_rules (...)
config_icp_per_offer (...)
config_dashboard_layout (...)
```

### 6.2 Phase 1+ — typed schemas (designed in-context)

`stg_*` and `unified_*` schemas are *not* designed in this spec. They are designed in their respective phases after observation of real source data. The unified model will likely include:

- `unified_account` — the spine; HubSpot company is the canonical source
- `unified_contact` — people across all sources
- `unified_deal` — HubSpot deals with denormalized stage/owner/source
- `unified_touchpoint` — every email send/open/click/reply, every LinkedIn message, every meeting invite, normalized
- `unified_call` — Fathom recordings + transcripts + AI summaries
- `unified_campaign` — Lemlist/Aimfox/Instantly campaigns with metadata
- `unified_signal` — detected hot signals (RevOps hiring, funding, etc.) with TTL countdown

The exact column set is *deferred to its phase*.

### 6.3 Namespace decision

- If Supabase is empty: leadle-os tables live in `public.*`.
- If Supabase is shared with other Leadle work: leadle-os tables live in a dedicated `leadle_os.*` schema to avoid collision.

Decision made at P1 schema-design step.

---

## 7. Identity resolution

### 7.1 Primary path (Clay-injected IDs) — script

Lemlist, Aimfox, Instantly leads arrive with `hubspot_company_id` and `hubspot_contact_id` populated as custom fields by Clay during enrichment. The script:

1. Reads custom fields from raw_<source>.payload JSONB.
2. If both IDs present → write to unified_contact / unified_account with `match_method = 'clay_injected'`, `match_confidence = 'HIGH'`.
3. If IDs absent → write record to `unmatched_review` queue with all known keys (linkedin_slug, email, email_domain, normalized_company_name, country).

### 7.2 Fallback (waterfall) — small agent

For records in `unmatched_review`, the Identity Resolver agent (small, low-volume, Haiku-class) attempts:

1. Match on `linkedin_company_slug` (normalized, case-insensitive).
2. Match on `email_domain_root` (e.g., `acme.co.uk` → `acme`).
3. Fuzzy match on `company_name_normalized` (Inc./Ltd./Pvt stripped) + country, requiring confidence ≥ 0.85.
4. If no match → flag for manual review (Slack notification).

Confidence tiers: HIGH (Clay), MEDIUM (deterministic waterfall), LOW (fuzzy ≥ 0.85), UNMATCHED.

### 7.3 Volume expectation

Per LEADLE_CONTEXT, Clay-driven pipelines are the default. Expect ≥95% HIGH-confidence matches via primary path; the agent fires only on the residual.

---

## 8. Configuration model

Operational behavior lives in YAML files Bhuvanesh edits without touching code. On change, files are re-loaded on next run (no restart needed for scheduled runs).

| File | Controls |
|---|---|
| `config/brief_sections.yaml` | Sections in the Sai daily brief, their order, their producer functions |
| `config/signals.yaml` | Signal Detector triggers — keywords, ICP filters per offer, time windows |
| `config/phantom_rules.yaml` | Phantom Detector thresholds — revenue band per offer, days-stuck cutoffs, evaluator-keyword list |
| `config/icp_per_offer.yaml` | ICP definitions (mirrors Pipeline Action Plan §04): Founder on Call / Outbound OS / RevOps as a Service |
| `config/dashboard_layout.yaml` | Dashboard sections to show per tab, ordering, freshness banner thresholds |
| `config/voice.yaml` | Voice and tone references for brief composer |

YAML is the source of truth. The corresponding `config_*` Supabase tables are mirrors loaded at run start for queryability.

---

## 9. Reliability

### 9.1 Failure modes and mitigations

| Failure | Detection | Mitigation |
|---|---|---|
| Source API down (Lemlist 5xx) | Connector exception caught | Per-source isolation; record dead-letter row; alert to #leadle-os-ops; other sources continue |
| Webhook drops | N/A (no webhooks Phase 1) | — |
| Container restart / deploy | N/A (no hosted compute) | — |
| Database outage | Connection error in any agent/script | Supabase managed; retry with backoff; alert if > 5 min |
| Schema drift in source API | Field missing or type mismatch on staging transform | raw_<source>.payload preserved as JSONB; staging fix is a single PR; historical data intact |
| Long sync exceeds Claude Code session limits | Run incomplete | Connectors checkpoint to sync_state every N records; next run resumes |
| Bhuvanesh forgets to sync | data_freshness() reports staleness | Scheduled CronCreate run handles it; Bhuvanesh sees freshness banner if running interactively |
| Sai's brief fails to post | Slack 5xx, OAuth expiry | Retry once; on second failure, post to #leadle-os-ops; brief markdown saved to reports/ |
| Brief becomes noise | Sai stops engaging | Track Slack reactions/replies on brief; weekly usage report to Bhuvanesh |
| Cron run aborts mid-flight | Run not marked complete in sync_state | Heartbeat-style: every successful step posts to #leadle-os-ops; missing posts trigger investigation |

### 9.2 Observability

- `data_freshness()` MCP tool surfaces last-sync time per source.
- `#leadle-os-ops` Slack channel receives heartbeat messages on every scheduled run (success or failure).
- Missed-delivery alert if no successful run in 36 hours.
- Brief usage tracking: Slack reaction count, replies count surfaced weekly.

---

## 10. Cost envelope

| Line item | Reasoning | Monthly |
|---|---|---|
| Supabase free tier (months 1–3) | Until Fathom transcripts hit 500MB cap | $0 |
| Supabase Pro (month 4+) | Storage + compute headroom | $25 |
| HubSpot MCP daily sync (Sonnet orchestration) | ~50–200 MCP calls/day | $30–80 |
| Daily Sai brief composition (Sonnet) | One narrative per day | $3–9 |
| Weekly Sales Insight Digest (Sonnet, transcript-heavy) | ~$2–5 per run | $8–20 |
| Per-day agent runs (Phantom, Signal, Hygiene, Outreach, Funnel) | Mix of Haiku + Sonnet | $15–35 |
| Slack workspace | Existing | $0 |
| **Total months 1–3** | | **$55–145** |
| **Total month 4+** | | **$80–170** |

Cost reduction levers: Haiku pre-filtering for Signal Detector, twice-daily HubSpot sync instead of hourly, transcript embedding cache.

---

## 11. Phases

Each phase is independently mergeable; stopping after any phase leaves a coherent system.

### CORE BUILD

**P0 — Minimal foundation.** Repo, Python project, Supabase connection, 5 empty `raw_<source>` tables, `sync_state`, `unmatched_review`, `config_*` placeholders, HubSpot MCP connection verified, leadle-os MCP skeleton, Slack integration. **Done when:** smoke test posts "hello" to Slack and inserts a dummy row into `raw_hubspot`.

**P1 — HubSpot end-to-end.** Pull HubSpot data via MCP into `raw_hubspot`. Observe and document in `docs/data-shape/hubspot.md`. Design typed `stg_hubspot_*` and `unified_account / contact / deal` tables. Build Phantom Detector agent + Sai Brief Composer (one section: "THE 5 REAL DEALS"). Manual `/sync-all` and `/brief-sai` slash commands. **Done when:** Bhuvanesh runs `/sync-all` then `/brief-sai`, Sai's Slack DM gets the day's brief naming the 5 real opportunities.

**P2 — More HubSpot agents.** CRM Hygiene Auditor agent. Funnel Leak Detector agent. Channel Attribution script. **Done when:** Brief contains rotting-deals, follow-up-gaps, and stage-drop-off sections.

**P3 — Lemlist.** Connector → raw_lemlist → observe → schema → extend `unified_touchpoint` and `unified_campaign` → Outreach Health Monitor agent (Lemlist-only first). **Done when:** Brief includes Lemlist outreach-health section with reply-rate deltas.

**P4 — Instantly.** Same explore-first pattern. Outreach Health Monitor extends to multi-tool campaigns; inbox-placement decay surfaces. **Done when:** Brief includes inbox-placement alerts.

**P5 — Aimfox + Signal Detector.** Aimfox connector. Signal Detector agent (LinkedIn job posts + funding feeds + ICP-fit classification). **Done when:** Brief contains "new high-priority signals" with 48-hr countdown.

**P6 — Fathom + transcript intelligence.** Fathom connector with transcript chunking strategy. Phantom Detector upgraded to read transcripts (evaluator vs. decision-maker). Sales Insight Digest agent. **Done when:** Phantom detection accuracy improves measurably; weekly Sales Insight Digest posts.

**P7 — Dashboard renderer.** Jinja templating against `dashboard-v2.html`. Tabs 1, 2, 4 (Revenue Engine / Activity & Rot / Outreach Analytics). Output to Supabase Storage with signed URL. **Done when:** Bookmark-able URL renders with current data, regeneratable via `/dashboard` slash command.

**P8 — Automation.** Claude Code `/schedule` (CronCreate) routines: 08:00 IST daily full pipeline, Mondays 09:00 IST Sales Insight Digest. Ops heartbeat. Missed-delivery alert. Brief usage tracking. **Done when:** Bhuvanesh stops manually running anything; system posts to Sai every morning regardless of presence.

### EXTENSIONS

**E1 — Marketing tab (Bhuvaneswari).** Connect website analytics (GA4 or Clay Pixel) + inbound forms. Tab 5 of dashboard fills in. Inbound Quality Reporter agent. **Done when:** Tab 5 is live; weekly inbound-quality report posts to Bhuvaneswari's Slack.

**E2 — Live client data.** Multi-tenant per-client Supabase schemas (or per-client Supabase projects if isolation matters). Per-client API credential vault. Client Engagement Monitor agent. **Done when:** Bhuvanesh runs `/client <name> /pipeline` and sees live data from that client's CRM, isolated from Leadle's data.

**E3 — Marketing asset generators.** Use Case Generator agent. Case Study Builder agent. Pattern Library Maintainer. Voice/glossary/forbidden-pattern stewards. **Done when:** Drafts produced from anonymized historical engagement data, in correct voice, with AI-pattern sniffer flagging issues before publish.

---

## 12. Open questions and decisions deferred

| Item | Decided in | Notes |
|---|---|---|
| Existing Supabase namespace | P1 schema-design step | Empty → `public.*`; shared → `leadle_os.*` |
| Time budget | Not committed | Phase-by-phase progression at user's pace |
| Webhook reintroduction | Post-P8 if needed | Only if 24-hr brief cadence proves insufficient |
| Slack channels | P0 environment setup | Sai's DM ID, `#leadle-os-ops`, sales+marketing insights channel |
| Dashboard URL hosting | P7 | Supabase Storage with signed URL, regenerated daily |
| Transcript chunking strategy | P6 | Depends on observed transcript volume |
| Specific ICP thresholds in `config/phantom_rules.yaml` | P1 | Mirrors Pipeline Action Plan §04 |

---

## 13. References

- `LEADLE_CONTEXT.md` — comprehensive Leadle profile (`/home/bhuvanesh/Downloads/LEADLE_CONTEXT.md`)
- Revenue Engine one-pager — ownership and metrics
- `dashboard-v2.html` — presentation-layer spec (5 tabs)
- Pipeline Action Plan — April 30, 2026 diagnosis and action items
- `CLAUDE.md` (this repo) — project-level conventions for future sessions

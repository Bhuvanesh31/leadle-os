# Client-facing outreach dashboard — design

Date: 2026-06-17 (updated 2026-06-18 to match approved layout mock)
Status: Draft for review
Author: Bhuvanesh (RevOps Architect) + Claude
Sample client: **UPSTA**
Layout reference: 4 mock screenshots (Northwind/ASU "campaign report", weekly + monthly).

## 1. Purpose

A per-client, on-demand outreach **campaign report** Leadle generates to show the outreach
run for a client and how it is performing. The approved layout is metric-dense: KPI tiles,
benchmark grades, per-campaign and per-content breakdowns, sender + deliverability health,
timing, a written narrative, recommended actions, and forward targets.

It is distinct from the internal HubSpot/Fathom dashboard (`dashboard/render.py`). It is
built **once** but rendered for **two audiences** (see §3.1): an internal full-depth review
and a client-safe subset.

## 2. Scope

### In scope (v1)
- One report per client, scoped by campaign/sequence name key (`Upsta_*` / "UPSTA").
- **On-demand render only** — a command produces a point-in-time HTML snapshot. No live
  refresh, no scheduling.
- **Two cadences**: `--period weekly` (WoW deltas) and `--period monthly` (MoM deltas).
- **Two audiences**: `--audience internal` (everything) and `--audience client` (subset
  with operator-internal blocks hidden). Block visibility is config-driven (§3.1).
- **Source = the client's Google "Prospect list" workbook** (v1). It already holds the
  hand-exported Aimfox + Instantly event tables and the human Responses tracker, so v1 needs
  no new API integration.
- **Snapshot persistence**: every render writes its computed aggregates to a Supabase table.
  Powers WoW/MoM deltas (diff vs prior snapshot) AND accumulates the per-client history that
  v2 cross-client benchmarks will need.
- **Grading**: letter grades from a fixed rubric in `config/` (no cross-client compare yet).
- **Meetings booked / positive replies**: ground truth = the human Responses tracker.
- Output: static HTML per (client, period, audience); optional Supabase upload for a link.
- First deliverable: render the UPSTA sample for the team.

### Out of scope (v2+)
- **Real benchmark scorecard + Targets vs portfolio segment** (median/quartile across
  Leadle's clients). v1 uses a config rubric; v2 computes percentiles from the accumulated
  snapshot history. The snapshot schema is designed now so v2 is a read, not a backfill.
- **Live API ingestion** (Instantly + Aimfox direct) replacing the Sheet, behind the same
  source interface.
- Multi-tenant client auth / login. Phase 1 stays single-operator.
- Write-back to source systems (read-only invariant holds).
- HeyReach source (no UPSTA usage; add behind the source interface when a client uses it).

## 3. Architecture

```
On-demand:  python -m dashboard.client.render --client UPSTA --period monthly --audience client
            (and a /render-client-report slash-command wrapper)
        │
        ▼
dashboard/client/
  sources/
    base.py          # ClientSource protocol: read(client) -> ClientData
    sheet_source.py  # v1: parse Google workbook tabs -> ClientData
    live_source.py   # v2 placeholder: Instantly + Aimfox MCP, same ClientData shape
  model.py           # normalized dataclasses (§5)
  compute.py         # pure script: funnels, rates, grades, sender/timing, deltas, coverage
  snapshots.py       # read/write snapshot rows (Supabase) + diff vs prior
  agents/
    narrative.py     # Sonnet: prose narrative (client-safe voice)
    actions.py       # Sonnet: "actions this period" (internal audience only)
  render.py          # CLI: source -> compute -> (agents) -> Jinja -> HTML (+ upload)
  templates/
    report_base.html.j2
    report.html.j2          # renders blocks; each block gated by audience + availability
    blocks/*.html.j2        # one partial per block (kpis, scorecard, campaigns, content,
                            #   senders, timing, deliverability, leads, narrative, actions,
                            #   targets)
config/
  client_report_layout.yaml # block order + per-block audience visibility (internal|client|both)
  client_report_rubric.yaml # grade thresholds, KPI definitions, channel labels, toggles
schemas/
  NNNN_client_dashboard_snapshots.sql
docs/data-shape/
  prospect-list-sheet.md    # already written
        │
        ▼
reports/client/UPSTA-2026-06-monthly-client.html   (gitignored)
+ Supabase: client_dashboard_snapshots row
```

### 3.1 Two-audience rendering
Blocks are declared in `config/client_report_layout.yaml` with a `visibility` of
`internal`, `client`, or `both`. `render.py --audience` filters blocks accordingly. Default
mapping (reviewer can adjust):

| Block | internal | client |
|---|:-:|:-:|
| KPI tiles | ✓ | ✓ |
| Benchmark scorecard (grades) | ✓ | ✓ |
| Which campaign performed | ✓ | ✓ |
| Content performance (steps/templates) | ✓ | ✓ (softened) |
| Sender-wise health | ✓ | ✗ |
| Timing heatmap | ✓ | ✓ |
| Deliverability flags | ✓ | ✗ |
| Warm & named leads (drill-down) | ✓ | ✓ |
| Narrative | ✓ | ✓ (client voice) |
| Actions this period | ✓ | ✗ |
| Targets (next period) | ✓ | ✓ |

Two template trees are NOT needed — one template, config-gated blocks. Client-safe tone is
enforced by (a) hiding internal blocks and (b) the narrative agent receiving an
`audience=client` instruction.

### 3.2 Why not extend `dashboard/render.py`
That pipeline serves the internal HubSpot/Fathom brief and shares no data with outreach
reporting. We reuse conventions (Jinja env, Supabase helpers, config-driven layout) but keep
a separate module to prevent data coupling and tone/IP leakage.

## 4. Data sources (v1)

From workbook `1GgFeDdXpy1ZlDjH8bTWNL_c7m0ihSSO_-iYNyzadCQg`; shapes in
`docs/data-shape/prospect-list-sheet.md`. Tabs consumed:

| Tab | Feeds |
|---|---|
| Email event export (Instantly) | KPIs, campaign table, sender-wise, timing, deliverability |
| LinkedIn event export (Aimfox) | KPIs, campaign table (accept/reply); templates (unranked) |
| Responses tracker (human) | positive replies, meetings booked, named-lead drill-down |
| Prospect spine (target lists, per-prospect) | coverage denominator (by segment); cadence IDs → channel reach |
| Onboarding + ICP | campaign-live dates, channels, segment context |

UPSTA observed (2026-06-17): LinkedIn invite 239 / accept 42 / reply 3; Email sent 224 /
opened 129 / clicked 41 / bounced 16; tracker ~1 disposition logged (campaign young).

**Verification needed during build**: whether Instantly events carry the sequence-step index
(gates per-step content reply rates). If absent, the Content block shows step *sends* and an
unranked note, mirroring the mock's own LinkedIn caveat.

## 5. Normalized model (`model.py`)

```
EmailEvent(company, to_name, event_type, campaign, ts, from_email, step?)
LinkedInEvent(event_type, company, profile_url, prospect_name, title, ts?)
WarmLead(channel, account, response_date, status, response_text, linkedin_url,
         name, title, company, company_url, location)   # status drives positive/meeting
TargetCo(name, country, location, linkedin_url, industry, size, segment, domain,
         aimfox_id, aimfox_urn, instantly_id)   # one row per PROSPECT; IDs = cadence entry

Context(client, channels[], campaign_live_dates{}, icp{})
ClientData(emails[], linkedin[], warm_leads[], targets[], context)

Snapshot(client, period_kind, period_end, rendered_at, metrics{json})
```

`ClientData` is the contract every source returns. `Snapshot.metrics` is the flat KPI bag
used for deltas and (v2) cross-client percentiles.

## 6. Compute (`compute.py`) — deterministic script

- **KPIs**: emails sent/opened/clicked/bounced + rates; invites/accepted/replied + rates;
  positive replies and meetings (from tracker status); within the selected period window.
- **Deltas**: each KPI vs the matching prior snapshot (same client + cadence). First render
  → `baseline` (no arrow).
- **Benchmark scorecard**: per-metric letter grade from `client_report_rubric.yaml`
  thresholds (e.g. reply ≥7% = A). `Overall` = weighted roll-up. (v2: replace thresholds
  with portfolio percentiles.)
- **Campaign table**: per `Upsta_*` campaign — channel, sends, reply/accept rate, positives,
  grade.
- **Sender-wise**: group email by `from_email` — volume, reply/accept, bounce rate + flag.
- **Timing heatmap (engagement, not reply)**: email **open/click** activity by weekday ×
  **day-part** bucket. Relabelled from the mock's "reply rate" because the Instantly export
  carries no reply event (sent/opened/clicked/bounced/auto-reply only); genuine replies live
  in the human tracker as **date-only**, so they cannot be hour-bucketed. Verified on UPSTA:
  170 timestamped engagement events, clearly clustered (Tue/Thu, 13:00–18:00 UTC). Bucket by
  the **campaign's configured timezone** (`campaign_schedule.timezone`, e.g. America/Detroit,
  Asia/Brunei); fall back to UTC with a stated caveat if absent. Use weekday × day-part
  (~4–5 columns) — 170 events is too thin for a 24-hour grid. LinkedIn timing = N/A (Aimfox
  export has no timestamp column) — rendered as a stated gap, matching the mock.
- **Coverage**: distinct companies contacted vs target universe, by segment.
- **Channel reach (cadence IDs)**: from the prospect spine's `Aimfox ID` / `Instantly ID`
  columns — unique prospects reached on LinkedIn (distinct non-empty `Aimfox ID`), on email
  (distinct non-empty `Instantly ID`), and on **both** (rows holding both). Deterministic, no
  event join; a blank ID means the prospect has not entered that cadence. Dedupe on the ID
  value. Spine parsing is **header-name-aware** (the table is per-prospect, wide, and varies
  in width), and reads **all paginated blocks** under the header.
- **Lead ladder**: classify known people Hot / Warm / Reached (Hot = positive reply or
  meeting from tracker; Warm = accepted invite / clicked / 2+ opens; else Reached). Join on
  LinkedIn URL then Name+Company; human tracker status wins.

## 7. Agents (judgment — Sonnet)

- **narrative.py**: writes the prose summary (mock's "Narrative"). Inputs = computed
  aggregates + deltas + grades. Receives `audience`; for `client` it applies
  `LEADLE_CONTEXT.md` client-safe voice and omits internal mechanics (mailbox warming, etc.).
- **actions.py** (internal only): derives "actions this period" (scale X, swap subject,
  pause/warm inbox). Never rendered for `audience=client`.

Both degrade gracefully: if the agent fails, its block renders a neutral fallback and the
rest of the report still renders.

## 8. Dashboard content & layout (matches mock)

Order: KPI tiles → Benchmark scorecard → Which campaign performed → Content performance
(email steps + LinkedIn templates) → Sender-wise → Engagement-timing heatmap → Deliverability flags →
Channel reach → Warm & named leads → Narrative → Actions → Targets. "Channel reach" (unique
prospects reached per channel + both-channel overlap, from the spine cadence IDs) is visible
to both audiences (config flag flips it to internal-only if desired). Header carries client name, report kind,
period label, and a `sample data` tag when applicable. Each KPI tile shows value + delta.

### Tone constraints
`LEADLE_CONTEXT.md` voice: conversational, dry, short sentences, no em dashes, no AI filler,
no captions that merely summarize. Client render additionally forbids internal vocabulary
(Signal-to-Motion, buying posture, funnel leak, hygiene) and self-critical operator framing.

### Data-quality display
Bounces/gaps shown as a small soft footnote on the client render
(`rubric.yaml: show_data_quality_notes`, default true); full deliverability block on internal.

## 9. Error handling & degradation

- Missing/unparseable tab → that block renders "not available this period"; report still
  renders.
- Empty Responses tracker → leads block falls back to the engaged tier (clicked/accepted) so
  it is never blank while a campaign is live; meetings/positives show 0 honestly.
- First render (no prior snapshot) → deltas show `baseline`, not fake zeros.
- `--client` matches nothing → abort with the campaign-name prefixes actually found.
- Agent failure → neutral fallback for that block only.

## 10. Snapshot store (`schemas/NNNN_client_dashboard_snapshots.sql`)

Supabase table `client_dashboard_snapshots(client, period_kind, period_end, rendered_at,
metrics jsonb, primary key (client, period_kind, period_end))`. Upsert per render. Deltas
read the prior `period_end`. v2 benchmarks read across `client` for a given `period_kind`.
(Schema added now per the phase-gated migration rule; one table, no premature typing of
`metrics`.)

## 11. Sample plan (first deliverable)

1. `model.py`, `sheet_source.py`, `config/*.yaml`, `compute.py`.
2. `snapshots.py` + migration (local-JSON fallback acceptable for the very first sample if
   Supabase write is friction).
3. `render.py` + templates/blocks; start styling from the internal dashboard base.
4. `agents/narrative.py` (actions.py can follow).
5. Render UPSTA monthly, both audiences → `reports/client/`.
6. Show the team; collect layout/tone/metric feedback.

Success = the team can say "ship this to clients" or give concrete changes.

## 12. v2 path (not now)
- Replace rubric grades + Targets with real percentiles from accumulated snapshots.
- `live_source.py` (Instantly + Aimfox MCP) and optional HeyReach source. **Identity backbone:
  the spine's per-prospect `Instantly ID` / `Aimfox ID` / `Aimfox URN` are the deterministic
  join keys** — `Instantly ID` → Instantly lead's email events; `Aimfox ID`/URN → Aimfox
  lead's invite/accept/reply events. This replaces v1's company-name + `Upsta_*` campaign
  matching. Verify the API round-trip (IDs resolve to live records) before relying on it; the
  v1 event dumps do not carry these IDs.
- Optional scheduled regeneration / per-client signed-URL hosting.

## 13. Decisions captured
- Audience: one pipeline, two config-gated renders (internal full, client subset).
- Benchmarks: config rubric in v1; real cross-client in v2 (snapshot history banked now).
- Deltas: persist a snapshot every render; first render = baseline.
- Meetings + positive replies: human Responses tracker is ground truth.

## 14. Open for reviewer
- Per-block client visibility table in §3.1 — adjust any rows.
- Keep the "Warm & named leads" drill-down (not in the mock but earlier agreed) on the client
  render, or internal-only?
- Sample hosting: local HTML enough, or upload to Supabase immediately?

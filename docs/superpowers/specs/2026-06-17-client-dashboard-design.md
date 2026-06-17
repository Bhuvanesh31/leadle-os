# Client-facing outreach dashboard — design

Date: 2026-06-17
Status: Draft for review
Author: Bhuvanesh (RevOps Architect) + Claude
Sample client: **UPSTA**

## 1. Purpose

A per-client, on-demand dashboard Leadle can share with a client to show the outreach
run on their behalf and the leads it is producing. It answers four questions in one view:
proof of work (what we ran), ROI (what it produced), channel performance (LinkedIn vs Email
vs Warm Calling), and a named-lead drill-down ("show me who is interested").

This is distinct from the existing internal dashboard (`dashboard/render.py`), which reads
HubSpot + Fathom and editorializes for Sai's brief. The client dashboard is proof-first,
non-self-critical, and must not surface internal IP or tone (Signal-to-Motion vocabulary,
"funnel leak", "hygiene gaps").

## 2. Scope

### In scope (v1)
- One dashboard per client, scoped by campaign/sequence name key (`Upsta_*` / "UPSTA").
- **On-demand render only** — a command produces a point-in-time HTML snapshot. No live
  refresh, no scheduling.
- **Source = the client's Google "Prospect list" workbook** for v1. The workbook already
  contains hand-exported Aimfox (LinkedIn) and Instantly (email) event tables plus a
  human-curated Responses tracker, so v1 needs zero new API integrations.
- Output: a static HTML file per client, optionally uploaded to Supabase for a signed URL.
- First deliverable: render the UPSTA sample to show the team.

### Out of scope (v2+)
- **Live API ingestion** (Instantly + Aimfox direct) replacing the Sheet as the quant source.
  Designed-for via a source interface, not built now.
- Multi-tenant auth / client login. Phase 1 stays single-operator (Bhuvanesh renders + shares).
- Write-back to any source system (read-only invariant holds).
- HeyReach (not used by UPSTA; add when a client uses it, behind the same source interface).

## 3. Architecture

```
On-demand:  python -m dashboard.client.render --client UPSTA
            (and/or a /render-client-dashboard slash command wrapper)
        │
        ▼
dashboard/client/
  sources/
    base.py          # ClientSource protocol: read(client) -> ClientData
    sheet_source.py  # v1: parse the Google workbook tabs -> ClientData
    live_source.py   # v2 placeholder: Instantly + Aimfox MCP, same ClientData shape
  model.py           # normalized dataclasses (see §5)
  compute.py         # pure script: funnel math, rates, lead ladder, coverage
  render.py          # CLI: source -> compute -> Jinja -> HTML (+ optional Supabase upload)
  templates/
    client_base.html.j2        # client-safe styling, no internal IP/tone
    client_dashboard.html.j2   # the four content sections
config/
  client_dashboard.yaml        # lead-ladder thresholds, channel labels, toggles
docs/data-shape/
  prospect-list-sheet.md       # observed shape of the workbook (already written)
        │
        ▼
reports/client/UPSTA-2026-06-17.html   (gitignored)
```

### Boundaries
- `sources/*` is the **only** layer that knows where data physically lives. This is the
  v1→v2 seam: swapping `sheet_source` for `live_source` must not touch compute or templates.
- `compute.py` is deterministic Python (counts/rates/classification by fixed rule) — a
  **script**, per the impact rule. No agent: inputs are structured, output is arithmetic.
- `templates/` is a **separate tree** from the internal dashboard so client-safe tone is
  structurally enforced, not relied upon by discipline.

### Why not extend `dashboard/render.py`
That pipeline (raw.json → compute pages 1-4 → narrative agents → windows) is built for the
internal HubSpot/Fathom brief and shares no data with client outreach reporting. Folding
client output into it would couple a client artifact to internal machinery and risk tone/IP
leakage. We reuse only conventions (Jinja env, Supabase upload helper), not the pipeline.

## 4. Data sources (v1)

All from the workbook `1GgFeDdXpy1ZlDjH8bTWNL_c7m0ihSSO_-iYNyzadCQg`. Shapes recorded in
`docs/data-shape/prospect-list-sheet.md`. Tabs consumed:

| Tab | Role | Layer |
|---|---|---|
| Email event export (Instantly) | sent/opened/clicked/bounced events, keyed by `Upsta_*` campaign | quantitative |
| LinkedIn event export (Aimfox) | connect/accepted/reply events | quantitative |
| Responses tracker (human) | named dispositions ("Long follow up"), warm-call outcomes, response text | qualitative |
| Target company lists | addressable universe per segment (US / Singapore) | coverage denominator |
| Onboarding checklist + ICP | campaign-live dates, channels, segment context | context |

The workbook is large (~600k chars all tabs); the source reads it once and splits by header
signature. Never load the whole thing into a model context for analysis — parse to records.

UPSTA observed tallies (2026-06-17): LinkedIn invites 239 / accepted 42 / replied 3;
Email sent 224 / opened 129 / clicked 41 / bounced 16 / auto-reply 1 / OOO 1; Responses
tracker ~1 logged disposition (campaign young).

## 5. Normalized model (`model.py`)

```
EmailEvent(company, to_name, event_type, campaign, ts, from_email)
LinkedInEvent(event_type, company, profile_url, prospect_name, title)
WarmLead(channel, account, response_date, status, response_text,
         linkedin_url, name, title, company, company_url, location)
TargetCo(name, country, location, linkedin_url, industry, size, segment, domain)
Context(client, channels[], campaign_live_dates{}, icp{})
ClientData(emails[], linkedin[], warm_leads[], targets[], context)
```

`ClientData` is the contract every source returns and compute consumes.

## 6. Compute (`compute.py`)

Pure functions over `ClientData`:
- `email_funnel` — sent, opened, clicked, bounced + open%/click%/bounce%.
- `li_funnel` — invites (connect), accepted, replied + accept%/reply%.
- `channel_table` — per channel: reached, engaged, engagement-rate, positive replies.
- `lead_ladder` — classify each known person into **Hot / Warm / Reached** by config rule:
  - **Hot**: replied (positive) OR warm-call booked/positive disposition.
  - **Warm**: accepted LinkedIn invite OR clicked an email link OR opened 2+ times.
  - **Reached**: contacted, no engagement yet.
  Join people across event tables + tracker on LinkedIn URL, then Name+Company. Human
  tracker status overrides derived status.
- `coverage` — distinct companies contacted vs target universe, broken down by segment.

Thresholds and channel labels live in `config/client_dashboard.yaml`.

## 7. Dashboard content & layout

Order: hero → ① funnel → ② channels → ③ named leads → ④ coverage.

- **Hero strip**: client name, reporting window, campaign-live dates, 3-4 headline tiles
  (prospects contacted, engaged, warm/hot leads, channels).
- **① Outcome funnel (proof of work)**: LinkedIn and Email funnels side by side (they are
  structurally different and must not be summed into one misleading funnel). Warm-calling
  shows a "just kicked off" state until the tracker fills.
- **② Channel performance**: compact comparison table across LinkedIn / Email / Warm Calls.
- **③ Warm & engaged leads (named drill-down)**: table of real people — Name · Title ·
  Company · Channel · Status (Hot/Warm + human disposition) · response text. This is the
  payoff section. Populated from tracker + engaged tier.
- **④ Reach & coverage (collapsible context)**: target universe by segment, top industries,
  "X of Y target accounts contacted", optional onboarding-health line.

### Tone constraints (client-safe)
Proof-first, plain, honest. Apply `LEADLE_CONTEXT.md` voice (conversational, dry, short
sentences, no em dashes, no AI-sounding filler). Forbidden: internal vocabulary
(Signal-to-Motion, buying posture, funnel leak, hygiene), self-critical framing, captions
that merely summarize.

### Data-quality display (resolved default)
Bounces and gaps shown to the client as a small soft footnote (e.g. "16 emails bounced —
list being cleaned"), honest but not alarming. Toggleable via
`config/client_dashboard.yaml: show_data_quality_notes` (default: true). Flip if the team
prefers internal-only.

## 8. Error handling & degradation

- **Missing tab / unparseable table**: that section renders a neutral "not available for
  this period" state; the rest of the dashboard still renders. Never hard-fail the whole page.
- **Empty Responses tracker**: section ③ falls back to the engaged tier (clicked/accepted)
  so it is never blank while a campaign is live.
- **Client key matches nothing** (e.g. wrong `--client`): render aborts with a clear message
  listing the campaign-name prefixes actually found, rather than emitting an empty dashboard.
- **Bounce/auto-reply events**: excluded from "engaged"; bounces surfaced only in the data-
  quality footnote.

## 9. Sample plan (first deliverable)

1. Implement `model.py`, `sheet_source.py`, `compute.py`, `config/client_dashboard.yaml`.
2. Implement `render.py` + the two templates (start from the internal dashboard's base
   styling, stripped of internal sections).
3. Render UPSTA → `reports/client/UPSTA-2026-06-17.html`.
4. Show the team. Collect feedback on layout, tone, and which numbers matter most.

Success = the team looks at the UPSTA HTML and can say "yes, ship this to clients" or gives
concrete layout/tone changes.

## 10. v2 path (not now)

- Implement `live_source.py` against Instantly + Aimfox MCP, returning the same `ClientData`.
  Quant funnel becomes live at render time; tracker/ICP/coverage may stay sheet-sourced or
  move to their own stores. No change to compute or templates.
- Optional: HeyReach source for clients who use it.
- Optional: schedule/regenerate on a cadence, or per-client signed-URL hosting.

## 11. Open questions for reviewer
- Section order: lead with funnel (current) or with named leads? (Current: funnel-first.)
- Data-quality footnote: show to client (current default) or internal-only?
- Hosting for the sample: local HTML file is enough, or upload to Supabase for a shareable
  link immediately?

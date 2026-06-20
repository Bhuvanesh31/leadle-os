# Client Dashboard Productization — Design

**Date:** 2026-06-21
**Status:** Approved (brainstorming), pending implementation plan
**Supersedes layout/metrics of:** `2026-06-17-client-dashboard-design.md` (extends, does not replace, the `dashboard/client/` pipeline)

## Problem

The client campaign dashboard built this session (`reports/client/upsta-monthly-full.html`)
is a **one-time, hand-built artifact**: numbers are hardcoded into the HTML, extraction lives
in `/tmp` scratch scripts, and everything is UPSTA-specific. It proves the layout and the data
story but is **not a repeatable function** — there is no `render(...)` that regenerates it from
live data.

Separately, a real pipeline already exists under `dashboard/client/` (model, sheet source,
compute, snapshots/deltas, narrative+actions agents, Jinja templates, render CLI; 115 tests
green) — but it produces the *earlier* layout and ingests a **silently-truncated Drive text
dump** (returned 261 of 1,229 prospects). Two of its known limitations (campaign positives
stubbed 0; reached_count an event proxy) are exactly what the new data work erases.

**Goal:** turn the approved design into a callable, tested function that regenerates the client
dashboard from live data — four outputs (weekly + monthly × internal + client) — by extending
the existing `dashboard/client/` pipeline.

## Decisions (locked in brainstorming)

1. **Approach: extend the existing `dashboard/client/` pipeline in place** — keep the working,
   tested model / snapshots / agents / audience-gating; change only what the new design needs.
   Not a rebuild (throws away solved problems), not a thin bolt-on (produces a non-matching
   hybrid).
2. **Source model (three-legged):**
   - *Campaign-level metrics* → **Aimfox** (LinkedIn funnel + variant message text) and
     **Instantly** (email funnel) REST APIs — authoritative live numbers.
   - *Prospect/spine* (reach, both-channel overlap, country, ICP, warm leads) → **XLSX**.
   - *Reply sentiment + event timing* → **Webhook XLSX** tabs (the only source for sentiment;
     also the only source of hourly timestamps for the heatmap, since the APIs are daily-only).
3. **Output matrix:** weekly + monthly × internal + client = **4 outputs**, one compute. Weekly
   mirrors the monthly-full structure with WoW deltas instead of MoM.
4. **Hardcode the UPSTA + Aimfox + Instantly setup for now.** No multi-client config machinery,
   no client selector/loader. Benchmarks + grade bands stay in config (already there); UPSTA
   source identifiers (sheet Drive ID, tab names, campaign filter `upsta`, timezone) are
   constants. Generalize only when a second client appears (YAGNI).
5. **Leads = any positive response.** Flows into the lead ladder and the Positive KPI. Meetings
   stay degraded until CRM is wired.
6. **Orchestration:** render stays a Python CLI. The session hands it the **XLSX path** (Drive
   download is an MCP/session step); **API keys live in env** (Aimfox connector already works
   this way; Instantly gets the same REST-connector treatment). Compute is MCP-free and
   testable.

## Architecture

```
session: download workbook XLSX (Drive MCP) -> path
                         |
        +----------------+-----------------------------------+
        |                       render CLI (Python)          |
        |  sources.load(xlsx_path, window) -> ClientData     |
        |    sheet_source  (XLSX: spine, webhook sentiment,  |
        |                   event timestamps, warm leads)    |
        |    aimfox_source (REST: LI campaign analytics +    |
        |                   variant message text)            |
        |    instantly_source (REST: email campaign          |
        |                   analytics) [NEW]                 |
        |                         |                          |
        |  compute.compute_all(data, rubric, window)         |
        |                         |                          |
        |  snapshots/deltas (MoM monthly / WoW weekly)       |
        |  agents: narrative + actions (Sonnet, fallbacks)   |
        |                         |                          |
        |  templates (Jinja, autoescape) x {audience,cadence}|
        +----------------+-----------------------------------+
                         |
            reports/client/upsta-<date>-<cadence>-<audience>.html  (x4)
```

## Components

### Source layer (`dashboard/client/sources/`)
- **`sheet_source`** — switch input from text dump to **XLSX** (`openpyxl` read_only/data_only),
  header-aware, handles repeated/paginated headers (logic exists; input changes). Extracts:
  spine tabs (cadence IDs → reach/overlap, country, ICP); `Webhook - LinkedIn` / `Webhook -
  Email` (reply rows + **Reply Sentiment** + event timestamps); `Response Tracker` (warm leads).
- **`aimfox_source`** — extend `connectors/aimfox`: per campaign `/campaigns/{id}` →
  `flows[].template.message` (variant text) and `/analytics/interactions` → sent_connections /
  accepted / replies (windowed). Campaign filter `upsta`.
- **`instantly_source`** *(new REST connector)* — per campaign `get_campaign_analytics`
  (authoritative sent/opens/clicks/bounce/replies; NOT the daily endpoint that double-counts).
- **Assembler** `sources.load(...) -> ClientData` merges into one normalized object: email
  campaigns, LinkedIn campaigns (+variant text), reply-sentiment records, spine prospects,
  warm leads, window meta.
- **Seam:** campaign reply *counts/rates* are API-authoritative; reply *sentiment split* is
  webhook-authoritative. Totals may differ slightly; the internal view notes the gap.

### Compute layer (`dashboard/client/compute.py`)
`compute_all(data, rubric, window) -> metrics` producing one dict per block:

| Block | Source | Logic |
|---|---|---|
| 6 KPI tiles | Instantly, Aimfox, webhook | headline + funnel; each + MoM/WoW delta + benchmark verdict |
| Benchmark scorecard | computed | `grade()` per-metric threshold bands (rubric) → A–F |
| Unified campaign table | Instantly + Aimfox | email ranked reply→click→open, LI ranked reply→connect, grouped, graded |
| Which LinkedIn message worked | Aimfox flows+analytics | variant ranking, reply-first, opening-hook text |
| Which email content performed | Instantly steps | per-step open/click |
| Sender-wise *(internal)* | Instantly accounts | inbox bounce/health |
| Deliverability *(internal)* | computed | flags from rubric thresholds |
| Timing heatmap | webhook timestamps | weekday × hour open intensity → blue matrix |
| Channel reach | spine | LinkedIn / email / both from cadence IDs |
| Lead ladder | spine + webhook | reach → engaged → positive(=lead) → meeting |
| Narrative / Actions | agents | Sonnet + fallback; Actions internal-only |
| Targets | config + computed | next-period goals |

- **Deltas:** snapshots store each period's KPIs; `deltas()` computes MoM (monthly) / WoW
  (weekly) off the prior snapshot; degrades to "first period" when none exists.
- **Grades:** existing `grade()` with **per-metric absolute threshold bands** in the rubric,
  tuned to UPSTA's benchmarks (e.g. `open_rate: [[0.20,"A"],[0.12,"B"]...]`; bounce inverts via
  `ascending_metrics`). New metrics (open, reply, positive) get bands added. No ratio function —
  consistent with the existing rubric and the hardcode decision.

### Config
- `config/client_report_rubric.yaml` *(exists)* — per-metric grade bands (absolute thresholds
  tuned to UPSTA), shared display defaults (`bounce_flag_threshold`, dayparts), and UPSTA
  benchmarks (open 0.20, click 0.02, positive 4/mo, replies 12/mo, bounce_max 0.04).
- `config/client_report_layout.yaml` *(exists)* — block list + `visibility` (internal/client/both);
  add the new blocks (variants, unified campaign table).
- UPSTA source identifiers (sheet Drive ID, spine/webhook tab names, campaign filter `upsta`,
  timezone `America/New_York`) hardcoded as constants (no multi-client loader).

### Templates (`dashboard/templates/`, Jinja, autoescape on)
- `base.html.j2` — approved design system CSS (Inter card, grade badges A–F, CSS-only hover
  tooltips `.pop/.tip/.rowtip`, GitHub-blue heatmap palette).
- `report.html.j2` — iterates layout blocks, gated by audience.
- Block partials per block above.
- Weekly = same templates, WoW data + weekly label. No separate weekly template.
- Audience gating: client excludes sender-health / deliverability / actions + internal
  Signal-to-Motion vocabulary; audience-gated footer (exists, tested).

## Error handling & degradation
- XLSX missing/unreadable → hard fail, clear message (no spine, no report).
- Aimfox/Instantly failure → `{available: False, reason}`; affected block degrades, rest proceeds.
- No campaign match → existing "No data matched client" guard, exit 2.
- Agent failure → deterministic fallback (rubric-sourced).
- Data gaps (meetings/CRM, empty sentiment, first-month email) → "—" / "needs X" / "first
  period", as the approved HTML handles them.
- API-vs-webhook reconciliation gap → small note, internal view only.

## Testing
- **Source:** `sheet_source` against a small real-shaped `.xlsx` fixture (spine + both webhook
  tabs incl. a paginated/repeated-header case); `aimfox_source` / `instantly_source` against
  mocked HTTP (no live calls).
- **Compute:** per block from a `ClientData` fixture — KPI math, ratio→grade, campaign ranking
  order, sentiment split, heatmap matrix, lead ladder, MoM/WoW deltas.
- **Template:** render fixture context; assert audience gating (no `augustine` / `sender health`
  / `pause & warm` in client output), autoescape, headline numbers present.
- **Golden:** render the UPSTA fixture and diff structure/key values against the approved
  `upsta-monthly-full.html` — the design is the regression target.
- Existing 115 tests carry forward; update those touched by compute/source rewrites.

## Out of scope (this effort)
- Multi-client generalization (config selector, per-client files) — deferred to YAGNI trigger.
- CRM/meetings ingestion (Meetings KPI stays degraded).
- Calling/warm-call data.
- Scheduling/automation of the render (remains on-demand, session-assisted).

## Success criteria
- One command produces all four outputs (weekly+monthly × internal+client) for UPSTA from live
  Aimfox/Instantly + the XLSX.
- Client outputs match the approved `upsta-monthly-full.html` design and contain no internal
  leakage.
- The two plan limitations (positives stubbed 0; reached_count proxy) are resolved with real
  data.
- Full test suite green, including new source/compute/template/golden tests.

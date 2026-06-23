# Client Dashboard — Ranking, Filtering & Week-over-Week (Sub-project A)

**Date:** 2026-06-23
**Status:** Approved design, pending implementation plan
**Scope:** The client campaign report (`dashboard/client/`) only. Deterministic display
+ ranking + week-over-week. **No AI / no narrative changes** — that is Sub-projects B
("what's not working" summary) and C (remove external API), sequenced after this.

## Problem

The client report's "content" section renders raw Instantly step rows with no campaign
name, no ranking, and no filtering — producing garbage like `Step None 0%`, `Step 0 45%`,
`Step 4 best 87%`. Separately, the week-over-week delta engine exists (`snapshots.deltas`)
but nothing surfaces it: every metric shows a static label, no comparison to last week.

## Goals

1. Replace the broken flat per-step block with **four ranked, filtered boxes** (email
   campaigns, email steps, LinkedIn campaigns, LinkedIn variants).
2. Show **week-over-week** movement: arrows on headline KPIs, previous-week numbers in
   every numeric tooltip.
3. Stay deterministic (pure Python + templates + one new Instantly fetch). The impact
   rule says ranking/filtering is a *script* problem — no AI here.

## Design

### 1. Four campaign boxes (replaces `content.html.j2`'s flat list)

Per channel, two boxes — a **campaigns** box and a **steps/variants** box:

| Box | Source | Rank (desc) | Exclude (non-performer) | Content line |
|---|---|---|---|---|
| Email — campaigns | `EmailCampaign` | reply_rate → click_rate → open_rate | open_rate == 0 | — |
| Email — steps | Instantly steps + **new copy fetch** | open_rate | open_rate == 0 | step subject/body |
| LinkedIn — campaigns | `LinkedInCampaign` | reply_rate → accept_rate (connections) | accepted == 0 | — |
| LinkedIn — variants | `variants()` | reply_rate → accept_rate | accepted == 0 | message `hook` |

- **Top 5** per box (after filtering, take first 5).
- Row label: `Campaign — Step N`; metric data right-aligned; content line below the label
  where present.
- **Filtering removes non-performers** (0 opens for email, 0 connections for LinkedIn).
  The ranking module returns BOTH the kept top-5 AND the excluded list (the excluded list
  is the documented seam Sub-project B will render as "what's not working" — A computes it,
  A does not render it).

### 2. Email step copy fetch (new)

Instantly's `/campaigns/analytics/steps` returns only `step, sent, opened, clicked` — no
copy. Add a fetch that pulls each step's **subject + body** from the campaign sequence
definition (Instantly campaign object's `sequences[].steps[].variants[]` carry
`subject`/`body`), joined to the analytics steps **by step index**. Implementation must:
- Add `campaign` (name) to each analytics step row in `connectors/instantly/fetch.py`
  `_campaign_steps` (the loop already knows the campaign; it currently drops the name).
- Add the copy lookup; attach `subject`/`body_preview` (first ~120 chars) to the step row.
- Degrade gracefully: if the copy fetch fails or a step has no match, the step still
  renders with metrics and an empty content line (never crash).

### 3. Week-over-week

`snapshots.deltas(current, prior)` already returns `{value, delta, baseline}` per key.
Today only `metrics["kpis"]` is snapshotted. Extend so all displayed numerics have a prior:

- **Snapshot scope widens:** `store.save` persists KPIs **plus** the per-campaign and
  per-step metrics (campaign name + the numeric fields), so next week's render can diff
  them. Schema bump in `snapshots.py` / `_snapshots.json` (additive — old snapshots remain
  readable; missing keys → baseline).
- **Display:**
  - Headline KPIs: `↑`/`↓` glyph + green(up)/red(down) class shown on the card.
  - Every numeric metric: `title=` tooltip → `prev <n> (↑/↓ <delta>)`, colored.
  - No prior (first render / new key) → no arrow; tooltip reads `no prior week`.
- **Direction semantics:** higher-is-better for rates/counts (more replies/opens/leads =
  green up). Bounce rate is inverted (lower is better → a decrease is green). The delta
  helper takes a per-metric `higher_is_better` flag.

### 4. Remove the old block

Delete `content.html.j2`'s flat per-step rendering; the email-steps box replaces it. The
`content_steps`/`variants` compute functions are reused/extended, not removed.

## Components touched

- `connectors/instantly/fetch.py` — add campaign name to step rows; add step-copy fetch.
- `dashboard/client/compute.py` — ranking + top-5 + filter for the 4 boxes; expose
  excluded list; per-metric direction flags.
- `dashboard/client/snapshots.py` — widen snapshot scope; delta direction support.
- `dashboard/client/templates/blocks/` — new `campaigns.html.j2` (4-box layout),
  delete flat `content.html.j2` rendering; tooltip + arrow macros.
- `dashboard/client/render.py` — pass the widened deltas to the template.
- `config/client_report_layout.yaml` — register the 4 boxes if layout-driven.

## Testing

- Unit: ranking order (reply→click→open / reply→connections), top-5 truncation,
  non-performer exclusion, excluded-list contents.
- Unit: step copy join by index; graceful degrade when copy missing.
- Unit: delta direction (bounce inverted), baseline (no prior) path.
- Golden render: a fixture with ≥6 campaigns (so top-5 truncation and exclusion both bite)
  and a synthetic prior snapshot (so arrows/tooltips render).
- **No live API calls in any test** — Instantly/Aimfox/Sheets all faked (existing
  invariant).

## Out of scope (later sub-projects)

- **B:** the "what's not working" narrative summary (A only computes the excluded list).
- **C:** removing the external Anthropic API / Claude-Code narration. A leaves the existing
  narrative/actions agents untouched; they keep working as today.
- No write-back to any source system (read-only invariant holds).

## Done when

- The 4 boxes render, ranked + filtered + top-5, with campaign names and content lines
  (email via the new copy fetch, LinkedIn via hook).
- Headline KPIs show WoW arrows; every numeric carries a prev-week tooltip; baseline path
  is clean.
- Full client test suite green, zero live external calls.
- A weekly UPSTA render visibly shows the new boxes + WoW indicators.

## Risks

- **Instantly step-copy join:** analytics `step` index vs sequence step index may not align
  1:1 (A/B variants, paused steps). Mitigation: join defensively; unmatched → empty content
  line, never crash. The plan must verify the real index alignment against live data.
- **Snapshot schema bump:** widening what's stored must stay backward-compatible (old
  KPI-only snapshots still load; absent campaign/step keys → baseline).

# Leadle OS — Dashboard Fasttrack Design

**Status:** approved (2026-05-09)
**Author:** Bhuvanesh + Claude
**Relation to master spec:** child of `2026-05-05-leadle-os-design.md`. The master spec stays the long-term north star; this fasttrack is the lean subset shipped first.

---

## §0 — Why

Bhuvanesh needs a working dashboard reflecting Leadle's GTM funnel, system health, and delivery health *now*, ahead of the master spec's full storage + agent fleet build. The dashboard mirrors the structure of `/home/bhuvanesh/Downloads/leadle-dashboard-2026-05-04 (1).html` (5-tab mock; v1 implements 4 of 5 tabs) and is fed by live data pulled directly from the source MCPs at render time.

Constraints driving this fasttrack:

- Fastest possible time to a working artifact.
- All five sources accessed via their hosted MCP servers (HubSpot, Lemlist, Aimfox, Instantly, Fathom) — no REST scripts, no custom MCP wrappers.
- No database. No raw JSONB landing zones. No identity-resolution audit trail.
- Local file output only — `./reports/dashboard_<date>.html` — no Supabase Storage upload, no shareable URL.
- Manual trigger only via `/render-dashboard` slash command. No CronCreate scheduling in v1.
- Single user (Bhuvanesh) operating it.

This design covers everything needed to build the v1 dashboard. Anything not in this document is either inherited from the master spec or explicitly out of scope per §1.2.

---

## §1 — Scope

### §1.1 — In scope (v1)

- Slash command `/render-dashboard` that interactively asks for a time window, then orchestrates a full data-fetch → analyze → narrate → render → write-local pipeline.
- Live data fetch from 5 hosted MCP servers (HubSpot, Lemlist, Aimfox, Instantly, Fathom).
- 4 tabs of the mock dashboard:
  - **Page 1 — Revenue Engine** (9 sections)
  - **Page 2 — Activity & Rot** (rotting deals, stalled leads)
  - **Page 3 — Sales Actions** (Sales Pipeline SOP, Fathom Gap)
  - **Page 4 — Outreach** (Lemlist / Aimfox / Instantly campaigns + follow-up gap)
- 4 LLM-backed agents:
  - Forward Motion (Page 1 §09) — Sonnet
  - Funnel Leak (Page 1 §06) — Sonnet
  - Hygiene & Divergence (Page 1 §08) — Sonnet
  - Fathom Gap Actions (Page 3) — Haiku, batched
- Window selector with always-interactive prompt (no default), supporting weekly / monthly / quarterly / rolling-N-day / specific-FY-month windows.
- Indian fiscal year convention (FY starts April; Q1 = Apr–Jun, Q2 = Jul–Sep, Q3 = Oct–Dec, Q4 = Jan–Mar).
- Static HTML output rendered to `./reports/dashboard_<YYYY-MM-DD>.html`, single-file, CSS inlined.
- Per-render structured log to `./reports/dashboard_<YYYY-MM-DD>_<window>.log`.
- Degradation reporting to chat after every render.

### §1.2 — Out of scope (v1)

These are deferred deliberately. Each has a re-evaluation trigger in §12.2.

- **Storage layer.** No Supabase Postgres. No raw JSONB landing tables. No `docs/data-shape/<source>.md` observation docs. (Master spec P0–P5.)
- **Page 5 — Marketing.** Inbound traffic / lifecycle stage view. Deferred per Bhuvanesh's scope decision (page 5 dropped).
- **Other master-spec agents:** Phantom Detector, Signal Detector, Outreach Health Monitor, Identity Resolver edge-case, Sai Daily Brief Composer, Sales Insight Digest. (Master spec P3–P8.)
- **Slack delivery.** No posting to channels or DMs. (Master spec P6, P8.)
- **Supabase Storage URL surface.** Local files only.
- **CronCreate scheduling.** Manual `/render-dashboard` only.
- **Ops Heartbeat.** No "did the daily render succeed?" check.
- **Cross-render diffing.** "What changed since yesterday" requires storage.
- **Multi-day anomaly baselines.** Anomaly checks compare current period to immediate prior period only.
- **Predictive forecasting / cohort analysis / per-vertical segmentation.** Mock is descriptive, not predictive.
- **HubSpot connector hybrid component** (master spec §4.4) — replaced by direct MCP fetch in slash command.
- **Custom `leadle-os` analytics MCP server** (master spec §4) — not built.
- **Cost / token-spend telemetry.** No tracking until cost surprises appear.

### §1.3 — Inherited from master spec

These principles and conventions apply to this build without restating in detail; see master spec for full text.

- Read-only against all source systems.
- Impact-based agent vs. script (master spec §2 principle 1).
- Config-driven, not hard-coded (master spec §2 principle 5).
- Cost discipline: Sonnet for narrative reasoning, Haiku for high-volume light classification (master spec §10).
- Voice and tone constraints (master spec §11; CLAUDE.md). Loaded into every agent's system prompt via `dashboard/agents/_voice.md`.
- Identity resolution via Clay-injected HubSpot IDs (master spec §7). Used inline at fetch/compute time; no caching layer.

---

## §2 — Architectural principles

These apply specifically to this fasttrack on top of the master spec's principles.

1. **MCP-only data access.** Every data fetch goes through the source's hosted MCP server. No REST API calls in Python; no local stdio MCP servers. HubSpot uses `claude.ai`-managed MCP; the other four are configured via `claude mcp add`.

2. **Live fetch, no persistence.** Each render is a self-contained execution. Data flows from MCP → memory → analytics → HTML → disk and is never persisted to a database.

3. **Render = one Claude Code session + one Python process.** Claude (the LLM) is the MCP client and the orchestrator; Python is the deterministic-analytics + Jinja-render + agent-call layer. The two are stitched via Bash invocation from inside the slash command.

4. **Always-interactive trigger, no defaults.** `/render-dashboard` always prompts for a window via `AskUserQuestion`. Confirms the resolved range before fetching.

5. **Fail open for data degradation; fail closed for misleading-output risks.** Missing one MCP, one agent, one section → degrade with a banner. Malformed window, malformed config, template syntax error → abort.

6. **Hallucination validation on agent output.** Every numeric claim in agent output is cross-checked against the analytics input. Mismatches reject + retry once + fall back to deterministic.

7. **Window-aware compute, with explicit window-fixed exceptions.** Each compute module receives a `WindowSpec` and uses it. Sections that are inherently point-in-time (Hygiene, Activity & Rot, Follow-up Gap) ignore the window arg.

---

## §3 — Architecture

```
┌────────────────────────────────────────────────────────────────────┐
│  /render-dashboard   (slash command, Claude Code session)          │
├────────────────────────────────────────────────────────────────────┤
│                                                                    │
│  PHASE 0  AskUserQuestion ─► window arg ─► resolve_window()        │
│           confirm resolved range with user                         │
│                                                                    │
│  PHASE 1  Claude ─► HubSpot MCP   ─┐                               │
│                  ─► Lemlist MCP   ─┤                               │
│                  ─► Aimfox MCP    ─┼─► .cache/dashboard_raw.json   │
│                  ─► Instantly MCP ─┤                               │
│                  ─► Fathom MCP    ─┘                               │
│                                                                    │
│  PHASE 2  Bash ─► python -m dashboard.render --input <json>        │
│                                                                    │
│             ┌─────────── compute deterministic analytics ──────┐   │
│             │   compute/page1_revenue.py                       │   │
│             │   compute/page2_activity.py                      │   │
│             │   compute/page3_actions.py                       │   │
│             │   compute/page4_outreach.py                      │   │
│             │   compute/shared.py    (date / pacing / anomaly) │   │
│             │   compute/windows.py   (resolve_window)          │   │
│             └────────────────────┬─────────────────────────────┘   │
│                                  ▼                                 │
│  PHASE 3   ┌─── narrate (Anthropic SDK, asyncio.gather) ─────┐     │
│            │   agents/forward_motion.py     [Sonnet]         │     │
│            │   agents/funnel_leak.py        [Sonnet]         │     │
│            │   agents/hygiene.py            [Sonnet]         │     │
│            │   agents/fathom_gap.py         [Haiku, batched] │     │
│            │   agents/_client.py     (retries, validator)    │     │
│            │   agents/_voice.md      (Leadle voice prompt)   │     │
│            └────────────────────┬────────────────────────────┘     │
│                                 ▼                                  │
│  PHASE 4   Jinja ─► merge analytics + narratives ─► HTML string    │
│                     templates/base.html.j2 + per-tab partials      │
│                                                                    │
│  PHASE 5   Path("./reports/dashboard_<date>.html").write_text(...) │
│                                                                    │
│  PHASE 6   Claude prints local path + degradation report to chat   │
│                                                                    │
└────────────────────────────────────────────────────────────────────┘
```

**Why this shape.** MCP tool calls require an LLM as the client; that's why Phase 1 lives inside a Claude Code session rather than a pure Python script. Analytics and rendering are deterministic, so they live in Python. Agents make Anthropic API calls via the SDK directly — they don't go through the Claude Code session or MCP. The two LLM paths (Claude-as-MCP-client in Phase 1, agents-via-SDK in Phase 3) are independent.

---

## §4 — Component inventory

```
.claude/commands/
  render-dashboard.md            ← slash command markdown — orchestrates the render

dashboard/
  __init__.py                    ← (already exists)
  render.py                      ← CLI entry: python -m dashboard.render --input <json>
                                   loads raw → calls compute.* → calls agents.* → renders Jinja → writes file
  compute/
    __init__.py
    shared.py                    ← date helpers, pacing math, anomaly diff
    windows.py                   ← WindowSpec dataclass + resolve_window()
    page1_revenue.py             ← compute for Page 1's 9 sections
    page2_activity.py            ← rotting deals, stalled leads, KPI strip
    page3_actions.py             ← Fathom Gap detection (SOP is static template)
    page4_outreach.py            ← campaign tables (Lemlist/Aimfox/Instantly), follow-up gap
  agents/
    __init__.py
    _client.py                   ← shared Anthropic SDK wrapper: retries, structured output, hallucination validator, fallback
    _voice.md                    ← Leadle voice constraints (loaded into every prompt)
    forward_motion.py            ← Sonnet · synthesizes Page 1 §09 commitments
    funnel_leak.py               ← Sonnet · interprets Page 1 §06 conversion rates
    hygiene.py                   ← Sonnet · categorizes Page 1 §08 + cross-tool divergences
    fathom_gap.py                ← Haiku · per-row "Action Needed" for Page 3 (batched)
  templates/
    base.html.j2                 ← shared layout, inlined CSS, tab nav scaffolding
    page1_revenue.html.j2
    page2_activity.html.j2
    page3_actions.html.j2
    page4_outreach.html.j2
    _sop_inbound.html.j2         ← static partial for Page 3 SOP inbound flow
    _sop_outbound.html.j2        ← static partial for Page 3 SOP outbound flow

config/
  dashboard_rules.yaml           ← thresholds: rotting-deal age, stalled-lead window, etc.
  dashboard_targets.yaml         ← revenue targets (₹3 Cr Oct 2026, monthly run-rate)
  dashboard_layout.yaml          ← section toggles, ordering
  dashboard_windows.yaml         ← FY convention, supported window enum
  dashboard_window_prompt.yaml   ← which 4 windows surface in primary AskUserQuestion

tests/
  __init__.py
  conftest.py                    ← shared fixtures (frozen "today", canned MCP output)
  test_windows.py                ← every window arg × multiple "today" dates (HIGHEST LEVERAGE)
  test_compute_shared.py
  test_compute_page1.py
  test_compute_page2.py
  test_compute_page3.py
  test_compute_page4.py
  test_agents_client.py          ← validator, fallback, parse error handling
  test_agents_forward_motion.py
  test_agents_funnel_leak.py
  test_agents_hygiene.py
  test_agents_fathom_gap.py
  test_render.py                 ← end-to-end Python pipeline (no MCP, mocked agents)
  test_templates.py              ← Jinja render with full + degraded contexts
  fixtures/
    sample_raw.json              ← frozen MCP output (PII-scrubbed)
    sample_analytics.json        ← expected compute output for sample window
    sample_narratives.json       ← canned agent responses for L3/L5 mocking
    sample_dashboard.html        ← golden render output for snapshot diff

smoke/
  __init__.py                    ← (already exists)
  MANUAL.md                      ← manual checklist for live MCP smoke test
```

**Files unchanged from master-spec scaffolding** (kept for the master spec's eventual P0–P8 build): `agents/` (top-level master-spec agents directory, distinct from `dashboard/agents/`), `analytics/`, `connectors/`, `identity/`, `leadle_os_mcp/`, `schemas/`, `docs/data-shape/`. These remain empty placeholders; this build does not fill them.

---

## §5 — Data flow

The render proceeds through six phases. Phase boundaries are observable: each phase's output is captured in a file or printed to chat, so failures are localizable.

### Phase 0 — Window selection (~10s)

User runs `/render-dashboard` (no args). Claude:

1. Loads `config/dashboard_windows.yaml` (FY convention, supported windows enum).
2. Loads `config/dashboard_window_prompt.yaml` (which 4 options surface in primary prompt).
3. Computes "today" and FY context for display.
4. Calls `AskUserQuestion`:
   ```
   "What time window for this dashboard?
    Today: 2026-05-09 · Current FY quarter: Q1 FY2026 (Apr–Jun 2026)"
   ◯ Last 7 days
   ◯ Current month (May 2026)
   ◯ Current quarter (Q1 FY2026 · Apr–Jun)
   ◯ Last quarter (Q4 FY2025 · Jan–Mar)
   ◯ Other (specify)
   ```
5. If "Other" → second `AskUserQuestion` with the full enum.
6. Calls `resolve_window(<arg>, today)` (see §7).
7. Confirms the resolved range with the user, listing both window and prior-period dates.
8. On "yes" → proceed to Phase 1. On "no" → exit cleanly.

### Phase 1 — Fetch (~2–5 min)

Claude executes per-source MCP calls per the plan in `.claude/commands/render-dashboard.md` (see §6 for per-source details). All results write to `.cache/dashboard_raw_<YYYY-MM-DD>_<window>.json` with a stable per-source shape:

```json
{
  "render_id": "uuid",
  "window": { "name": "...", "label": "...", "start": "...", "end": "...",
              "prior_start": "...", "prior_end": "..." },
  "rendered_at": "ISO-8601",
  "sources": {
    "hubspot":   { "available": true,  "fetched_at": "...", "data": {...} },
    "lemlist":   { "available": true,  "fetched_at": "...", "data": {...} },
    "aimfox":    { "available": false, "error": "...", "fetched_at": "..." },
    "instantly": { "available": true,  "fetched_at": "...", "data": {...} },
    "fathom":    { "available": true,  "fetched_at": "...", "data": {...} }
  }
}
```

Each source pulls *both* the window range and the prior-period range in one fetch (spec'd by `[prior_start, end]` as the outer date filter).

### Phase 2 — Compute (~5–15s)

Claude invokes via Bash:

```
python -m dashboard.render --input .cache/dashboard_raw_<date>_<window>.json
```

Inside Python:

1. Load raw JSON.
2. Load `dashboard_rules.yaml`, `dashboard_targets.yaml`, `dashboard_layout.yaml`.
3. Reconstruct `WindowSpec` from the JSON's `window` block.
4. Call each compute module:
   - `page1_revenue.compute(raw, rules, targets, window) → analytics["page1"]`
   - `page2_activity.compute(raw, rules, window) → analytics["page2"]`
   - `page3_actions.compute(raw, rules, window) → analytics["page3"]`
   - `page4_outreach.compute(raw, rules, window) → analytics["page4"]`
5. `analytics` is a single dict, key per page, with deterministic numbers, threshold-flags, anomaly diffs, and target-pacing math.

### Phase 3 — Narrate (~30–60s)

Run four agents concurrently via `asyncio.gather`:

```python
forward_motion_out, funnel_leak_out, hygiene_out, fathom_gap_out = await asyncio.gather(
    agents.forward_motion(analytics),
    agents.funnel_leak(analytics),
    agents.hygiene(analytics),
    agents.fathom_gap(analytics),
)
```

Each agent flow (in `agents/_client.py`):

1. Load `_voice.md`.
2. Build system prompt = voice + role + JSON schema for structured output.
3. Build user message = analytics input slice scoped to that agent.
4. Call Anthropic SDK with `tenacity` retries (3 attempts, exponential backoff 1s/2s/4s).
5. Parse structured response.
6. Run hallucination validator: every digit-string in agent output must appear in the analytics input slice (with normalization: `"$19,500" ≡ "$19.5K"`, `"around 5" ≡ "5"`).
7. On parse fail → retry once with explicit "JSON only" instruction.
8. On retry fail or validator fail → return deterministic fallback + set `degraded=True`.

Output: `narratives` dict with one key per agent.

### Phase 4 — Render (~1–2s)

```python
context = {
    **analytics,
    **narratives,
    "render_id": render_id,
    "rendered_at": rendered_at,
    "window": window_spec,
    "version": __version__,
}
html = jinja_env.get_template("base.html.j2").render(**context)
```

`base.html.j2` includes the four per-tab partials. CSS inlined (single-file output, ~150–250 KB).

### Phase 5 — Write local (instant)

```python
out = Path(f"./reports/dashboard_{rendered_at:%Y-%m-%d}_{window.name}.html")
out.write_text(html, encoding="utf-8")
return out.absolute()
```

If the `./reports/` directory is missing or read-only → fail closed with the path in the error message.

### Phase 6 — Surface (~instant)

Claude prints to chat:

```
✅ Dashboard rendered: <absolute path>
   Window: <window label>

   ⚠️  Degraded sections:        ← omitted if nothing degraded
       - <section>: <reason>
       …

   Log: <log path>
```

---

## §6 — Per-tab data plan

For each tab: which MCP calls, which compute module, which agent (if any), and source-specific gotchas.

### §6.1 — Page 1 — Revenue Engine (9 sections)

**MCP calls:**

| Source | Tool | Purpose | Date filter |
|---|---|---|---|
| HubSpot | `search_crm_objects(deals)` | §01–06 revenue, pipeline, funnel, channel | `last_modified ≥ prior_start` |
| HubSpot | `search_crm_objects(contacts)` | §03 lead counts, §04 channel attribution, §07 owners | `createdate ≥ today − 365d` |
| HubSpot | `search_crm_objects(companies)` | company name lookup for deal references | (none — fetched as referenced) |
| HubSpot | `search_owners()` | §07 owner scorecards | (none — full list) |
| HubSpot | `get_properties(deals)` | property metadata for null detection | (one-time per render) |
| Fathom | meetings list | §03 "Meetings Booked" KPI | `[prior_start, end]` |

**Compute module:** `dashboard/compute/page1_revenue.py`

| Section | Logic | Window-aware? |
|---|---|---|
| §01 Goal Snapshot | Sum closed-won YTD; % of ₹3 Cr; run-rate status from `dashboard_targets.yaml` | No — always YTD |
| §02 Monthly Control | Sum closed-won MTD; pacing vs. monthly target; pipeline coverage = open_pipeline / monthly_target | **No** — always shows *current calendar month* regardless of selected window. The "Monthly Control Panel" is monthly by definition; the window selector does not change which month it shows. |
| §03 Execution Panel | Counts by stage transition over window | Yes |
| §04 Channel Performance | Group deals by `hs_analytics_source` over window | Yes |
| §05 Channel Economics | Revenue/pipeline/ACV by channel over window | Yes |
| §06 Funnel | Stage→stage conversion % for window cohort | Yes (compute); narrated by Funnel Leak agent |
| §07 Accountability | Group by `hubspot_owner_id` over window | Yes |
| §08 Hygiene | Detect missing source/owner/lifecycle, orphan deals, cross-tool divergences | No — point-in-time |
| §09 Forward Motion | Aggregate rule outputs from all other sections; pass to Forward Motion agent | Yes |

**Agents:**
- §06 → `agents/funnel_leak.py` (Sonnet)
- §08 → `agents/hygiene.py` (Sonnet)
- §09 → `agents/forward_motion.py` (Sonnet)

**Gotchas:**
- `hs_analytics_source` is a standard property (not Marketing Hub Starter restricted) — channel attribution works via MCP.
- HubSpot search caps at 100 records/page — paginate explicitly in slash command instructions.
- Owner names live on the `owners` endpoint, not on deal records — join client-side after both fetches complete.
- Fathom may return Sai's *and* delivery review calls; filter by host or call type in compute.

### §6.2 — Page 2 — Activity & Rot

**MCP calls:**

| Source | Tool | Purpose | Date filter |
|---|---|---|---|
| HubSpot | `search_crm_objects(deals)` | rotting deals: open + last_activity_date | `stage NOT IN [Closed Won, Closed Lost]`, `last_activity ≥ today − 90d` |
| HubSpot | `search_crm_objects(contacts)` | stalled leads: lifecycle + last_activity | `lifecycle = lead`, `last_activity ≥ today − 90d` |
| Lemlist | (lead/reply tools — names discovered at runtime) | identify replied leads | (current period scope sufficient) |
| Aimfox | (conversation/reply tools) | identify replied leads | same |
| Instantly | (lead/email tools) | identify replied leads | same |

**Compute module:** `dashboard/compute/page2_activity.py`

- **Rotting Deals**: open deals where `today − last_activity_date > rules.rotting_deal_days` (default 14)
- **Stalled Leads**: contacts where (replied in any outreach tool) AND (HubSpot lifecycle ≠ Meeting Booked) AND (`days_since_reply > rules.stalled_lead_days`, default 5)
- **KPI strip**: rotting_count, pipeline_at_risk = sum(amount of rotting), stalled_count, 30d+-stalled count, most-critical-deal = oldest by last_activity

**Agents:** None directly; Hygiene agent (Page 1 §08) catches divergences as a side effect (e.g., reply logged in Lemlist but not in HubSpot).

**Gotchas:**
- Cross-tool join via Clay-injected `hubspot_contact_id` custom field on each Lemlist/Aimfox/Instantly lead. 95% deterministic per master spec §7.
- "Replied" semantics differ per tool: Lemlist has reply sentiment; Aimfox has conversation status; Instantly has reply categories. Normalize to a binary `has_replied` in compute; preserve raw shape in `.cache/dashboard_raw.json` for debugging.
- `last_activity_date` in HubSpot covers calls/emails/meetings/notes, but not Lemlist/Aimfox/Instantly *unless* those tools push activity to HubSpot. Don't assume; verify when first sample raw lands.

**Window-aware?** No — Page 2 is point-in-time current state.

### §6.3 — Page 3 — Sales Actions

**MCP calls:**

| Source | Tool | Purpose | Date filter |
|---|---|---|---|
| Fathom | meetings list | gap detection — meetings in window | `[start, end]` |
| HubSpot | (deals + contacts already fetched for Page 1) | check existence of CRM record per Fathom call | (reuse Page 1 fetch) |

**Compute module:** `dashboard/compute/page3_actions.py`

- **Sales Pipeline SOP**: static. Rendered from `templates/_sop_inbound.html.j2` and `templates/_sop_outbound.html.j2`. No data-driven content.
- **Fathom Gap detection**: for each Fathom meeting in window, resolve attendee → company. If no HubSpot deal exists for that company with `created_date` near the meeting date → flag as gap. Output per gap: `{company, contact, last_call_date, call_type, crm_state, suggested_action_default}`.

**Agents:**
- Fathom Gap "Action Needed" column → `agents/fathom_gap.py` (Haiku, batched in one call for all gap rows).

**Gotchas:**
- Fathom attendee → company resolution: prefer email-domain match if attendee email is present; fall back to company-name fuzzy match (mark as low-confidence — agent prompt notes this).
- Default action when agent fails: `"Create deal in HubSpot · stage: Discovery"` (deterministic fallback).
- The SOP section is documentation, not data — hard-code in the Jinja partials. Don't overengineer.

**Window-aware?** Yes (Fathom Gap section); No (SOP).

### §6.4 — Page 4 — Outreach

**MCP calls:**

| Source | Tool | Purpose | Date filter |
|---|---|---|---|
| Lemlist | campaign + per-campaign stats tools | campaign performance table | window |
| Aimfox | campaign + conversation tools | LinkedIn campaign performance | window |
| Instantly | campaign + 3 analytics tools | email campaign performance | window |
| HubSpot | `search_crm_objects(contacts)` filtered `lifecycle=lead` | follow-up gap detection | `last_activity_date < today − rules.followup_gap_days` |

**Compute module:** `dashboard/compute/page4_outreach.py`

- **Lemlist Campaigns**: per-campaign — sends, replies, reply rate, meetings booked (joined via `hubspot_contact_id`)
- **Aimfox Campaigns**: same shape
- **Instantly Campaigns**: same shape
- **Follow-up Gap**: HubSpot contacts where `lifecycle = lead` and `today − last_activity_date > rules.followup_gap_days` (default 5)

**Agents:** None on Page 4 directly; Forward Motion (Page 1 §09) picks up egregious follow-up gaps in synthesis.

**Gotchas:**
- Each outreach tool's MCP exposes campaigns differently. Aimfox docs are thin — discover tool names at runtime via MCP introspection (`list_tools`).
- Reply *count* and reply *rate* may have different denominators per tool (active sends vs. total sends). Normalize in compute; document the chosen denominator inline.
- Suppress campaigns with `< rules.outreach_min_sends` (default 10) — too noisy.

**Window-aware?** Yes (campaign tables); No (Follow-up Gap is point-in-time).

---

## §7 — Window selector

The slash command takes no args and is always interactive (per §2 principle 4).

### §7.1 — Supported window enum

| Window arg | Resolves to | Prior period |
|---|---|---|
| `current-week` | ISO week containing today (Mon–Sun) | previous ISO week |
| `last-week` | previous ISO week | week before that |
| `last-7d` | today − 7d → today (rolling) | 7d before that |
| `current-month` | calendar month containing today | previous month |
| `last-month` | previous calendar month | month before that |
| `month-april` | April of current FY | April of prior FY |
| `month-may` | May of current FY | May of prior FY |
| `month-june` | June of current FY | June of prior FY |
| `month-july` … `month-march` | named month, current FY | named month, prior FY |

**Named-month FY resolution:** `month-X` always resolves to month X *within the current FY*. FY2026 spans Apr 1 2026 → Mar 31 2027, so when today = 2026-05-09 and FY = 2026:

- `month-april` = April 2026 (start of current FY)
- `month-march` = March 2027 (end of current FY — note the calendar year roll)
- `month-january` = January 2027 (within current FY)

If today = 2026-02-09 (still in FY2025), `month-april` = April 2025 (start of FY2025).
| `last-30d` | today − 30 → today | 30d before that |
| `last-60d` | today − 60 → today | 60d before that |
| `last-90d` | today − 90 → today | 90d before that |
| `current-quarter` | current FY quarter | previous FY quarter |
| `last-quarter` | previous FY quarter | quarter before that |
| `q1` / `q2` / `q3` / `q4` | specific quarter, current FY | same quarter, prior FY |

### §7.2 — Fiscal year convention

Indian FY: April–March. FY label = year of the *ending* month. Today = 2026-05-09 falls in FY 2026–2027; we label as **FY2026** (year of fiscal start).

```yaml
# config/dashboard_windows.yaml
fiscal_year:
  start_month: 4          # April
quarters:
  q1: [4, 5, 6]            # Apr Jun
  q2: [7, 8, 9]            # Jul Sep
  q3: [10, 11, 12]         # Oct Dec
  q4: [1, 2, 3]            # Jan Mar (rolls into next calendar year)
supported_windows:
  - current-week
  - last-week
  - last-7d
  - current-month
  - last-month
  - month-april
  - month-may
  - month-june
  - month-july
  - month-august
  - month-september
  - month-october
  - month-november
  - month-december
  - month-january
  - month-february
  - month-march
  - last-30d
  - last-60d
  - last-90d
  - current-quarter
  - last-quarter
  - q1
  - q2
  - q3
  - q4
```

### §7.3 — `WindowSpec` data class

```python
# dashboard/compute/windows.py
@dataclass(frozen=True)
class WindowSpec:
    name: str           # canonical, e.g. "q1-fy2026"
    label: str          # human-readable, e.g. "Q1 FY2026 (Apr–Jun 2026)"
    start: date         # inclusive
    end: date           # inclusive
    prior_start: date   # inclusive
    prior_end: date     # inclusive

def resolve_window(arg: str, today: date) -> WindowSpec:
    """Map a window arg to a concrete WindowSpec.

    Reads fiscal config from config/dashboard_windows.yaml.
    Raises ValueError on unknown arg.
    """
```

### §7.4 — Primary AskUserQuestion options

The 4 options surfaced first (plus "Other") are configurable, not hard-coded:

```yaml
# config/dashboard_window_prompt.yaml
primary_options:
  - last-7d
  - current-month
  - current-quarter
  - last-quarter
prompt_template: |
  What time window for this dashboard?
  Today: {today} · Current FY quarter: {current_quarter_label}
```

If the user picks "Other," a second `AskUserQuestion` lists the full enum.

---

## §8 — Configuration model

Three categories of config, separated to allow different change cadences.

### §8.1 — `config/dashboard_rules.yaml`

Threshold rules. Change rarely.

```yaml
rotting_deal_days: 14
stalled_lead_days: 5
followup_gap_days: 5
outreach_min_sends: 10
anomaly_pct_threshold: 30      # WoW drop/spike % flagged
hygiene:
  require_owner: true
  require_source: true
  require_lifecycle: true
fathom_gap:
  attendee_match_strategy: email_domain_first  # or: company_name_first
  fuzzy_match_threshold: 85                     # for company-name fallback
```

### §8.2 — `config/dashboard_targets.yaml`

Revenue and pacing targets. Change quarterly.

```yaml
# Numbers below match the mock's display (USD); Bhuvanesh sets canonical
# values during implementation. The mock shows mixed framing — ₹3 Cr
# referenced in narrative, $319K shown as the goal — resolve at config time.
annual:
  goal_amount: 319000          # USD per mock; ~₹2.65 Cr at $1=₹83
  goal_currency: USD
  target_date: 2026-10-31
monthly:
  target_amount: 61800         # USD per mock
  target_currency: USD
pipeline_coverage:
  ratio_target: 3.0            # 3× coverage required
  ratio_warning_below: 2.0     # warn below 2×
  ratio_critical_below: 1.0    # critical below 1×
```

### §8.3 — `config/dashboard_layout.yaml`

Section visibility toggles. Change per-render or per-iteration.

```yaml
pages:
  page1_revenue:
    enabled: true
    sections:
      goal_snapshot: true
      monthly_control: true
      execution: true
      channel_performance: true
      channel_economics: true
      funnel: true
      accountability: true
      hygiene: true
      forward_motion: true
  page2_activity:
    enabled: true
  page3_actions:
    enabled: true
  page4_outreach:
    enabled: true
```

### §8.4 — `config/dashboard_windows.yaml`

FY convention and supported window enum (see §7.2).

### §8.5 — `config/dashboard_window_prompt.yaml`

Which window options surface in the primary `AskUserQuestion` (see §7.4).

---

## §9 — Error handling & reliability

### §9.1 — Principles

1. Fail open for data degradation; fail closed for misleading-output risks.
2. Retry transient errors only (3 attempts, exponential backoff).
3. Hallucination-validate every numeric claim in agent output.
4. Always emit a degradation report after every render.

### §9.2 — Failure-mode policy table

| Phase | Failure | Policy | User-facing |
|---|---|---|---|
| 0 | User declines confirm | Exit 0 | "Render cancelled." |
| 0 | Window resolver bug | Fail closed | Stack trace + log path |
| 1 | Single MCP unreachable | Mark `source.unavailable=true`, continue | Tab(s) using that source show degraded banner |
| 1 | Single MCP tool rate-limited | Retry 3× backoff (1s, 2s, 4s) | Transparent on success |
| 1 | OAuth expired | Fail closed with reauth instruction | `"Lemlist OAuth expired. Run: claude mcp reauth lemlist"` |
| 1 | Expected MCP tool not exposed | Try documented fallbacks → mark unavailable | Section degraded |
| 1 | Empty data in window | Not an error | Section shows "No data in selected window" |
| 2 | Raw JSON missing field | Use `.get()` with defaults; log WARNING | Continue |
| 2 | Division by zero | Return `None` → template renders `—` | Mock pattern |
| 2 | Malformed YAML | Fail closed at startup | "config/X.yaml line N: invalid syntax" |
| 3 | Anthropic API down/rate-limited | Retry 3× backoff | Transparent on success |
| 3 | Agent malformed JSON | Retry once with stricter instruction → fall back | Section degraded badge |
| 3 | Agent hallucinated number | Validator rejects → retry once → fall back | Section degraded; log captures hallucination |
| 3 | Single agent fails | Independent failure | One degraded section; others unaffected |
| 4 | Template syntax error | Fail closed | Stack trace |
| 4 | Missing context key | Linted at template load time; defensive `\| default("—")` required | Cannot occur if linter passes |
| 5 | Disk full / permission | Fail closed with clear message | "Cannot write ./reports/. Check disk/perms." |
| 5 | File already exists | Overwrite (same intent) | No prompt |

### §9.3 — Retry strategy

Tenacity decorators on the two retry-eligible call sites:

```python
@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=4),
    retry=retry_if_exception_type((httpx.HTTPStatusError, RateLimitError, TimeoutError)),
)
def _mcp_call(...): ...

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=4),
    retry=retry_if_exception_type((anthropic.APIError, anthropic.RateLimitError)),
)
def _agent_call(...): ...
```

Worst-case retry latency per call: 7s. Across all calls, render still finishes within the 7-min envelope.

### §9.4 — Hallucination validator

Lives in `agents/_client.py`. For each agent response:

1. Extract every digit-string from the response (regex `\b[\d,.\-+]+[KMB]?\b`).
2. Normalize: `"$19,500" ≡ "$19.5K" ≡ "19500"`. Strip currency, expand K/M/B suffixes.
3. Extract every digit-string from the analytics-input slice the agent received.
4. Each output digit-string must match an input digit-string exactly *or* be a substring/prefix.
5. Mismatch → reject + retry once → fall back.

Slice-scoped: each agent's validator only checks against the slice that agent received, not the whole analytics dict. Prevents an agent from sneaking in numbers from a slice it shouldn't have seen.

### §9.5 — Logging

- Library: `structlog` (already in `pyproject.toml`)
- Format: JSON-Lines (greppable)
- File: `./reports/dashboard_<YYYY-MM-DD>_<window>.log` (one per render)
- Required fields: `render_id` (uuid), `phase`, `window`, `source` (when applicable), `slice` (when applicable), `latency_ms`
- Levels:
  - `INFO` — phase start/end, MCP call counts, file write
  - `WARNING` — retried calls, missing fields, degraded sections
  - `ERROR` — fail-closed errors, agent hallucinations

### §9.6 — Degradation report

After every render, Claude prints to chat:

```
✅ Dashboard rendered: <absolute path>
   Window: <window label>

   ⚠️  Degraded sections:
       - <section>: <reason>
       …

   Log: <log path>
```

If nothing degraded, replace the warning block with `All sections at full fidelity.`

---

## §10 — Testing strategy

### §10.1 — Layers

| Layer | Tests | Framework | Required? |
|---|---|---|---|
| L1 — Window resolver | every window arg × multiple "today" dates | pytest, parametrized | TDD-required |
| L2 — Compute modules | each `compute.pageN()` on `sample_raw.json` + rules + WindowSpec → expected analytics | pytest | TDD-required |
| L3 — Agents (mocked SDK) | prompt building, JSON parsing, fallback path, hallucination validator | pytest + `unittest.mock` | TDD-required for `_client.py` |
| L4 — Templates | render with full + degraded contexts; HTML well-formed | pytest + `bs4` | Snapshot-based, not strict TDD |
| L5 — Python pipeline (e2e) | `render.py` end-to-end on fixture, agents mocked, compare to golden HTML | pytest | Integration smoke |
| Manual — Live MCP smoke | Real `/render-dashboard` against real MCPs | checklist in `smoke/MANUAL.md` | Required before declaring "v1 done" |

### §10.2 — Fixture strategy

```
tests/fixtures/
  sample_raw.json           ← frozen MCP output (PII-scrubbed)
  sample_analytics.json     ← expected compute output for sample window
  sample_narratives.json    ← canned agent responses for L3/L5 mocking
  sample_dashboard.html     ← golden render output for L5 snapshot diff
```

Fixture upgrade path:
1. Day 1: hand-craft `sample_raw.json` with ~5 deals, ~10 contacts, ~3 campaigns/source — minimal to exercise compute logic.
2. First real render: capture `dashboard_raw_<date>.json`, scrub emails/names, replace as fixture.
3. As real-data quirks emerge: add minimal repro rows; comment each new row's edge case.

### §10.3 — Coverage targets

```
compute/windows.py            95%+   (pure logic)
compute/page*.py              80%+
agents/_client.py             80%+   (validator + parser)
agents/page-specific          50%+   (mostly wiring + fallback path)
render.py                     60%+
templates                     n/a    (snapshot-tested)
```

### §10.4 — TDD-required modules

Per superpowers `test-driven-development` skill — required for these:

- `compute/windows.py` (write `test_windows.py` first)
- `compute/page*.py` (fixture-driven expected-shape tests first)
- `agents/_client.py` (validator + parser tests before implementation)

Optional / iterative:
- Agent prompts (iterate against real Anthropic responses)
- Jinja templates (snapshot-and-tune)
- Render orchestrator glue

### §10.5 — What's not tested in v1

- **MCP fetch correctness.** Lives in markdown; verified by manual smoke.
- **Agent reasoning quality.** Tested for *valid output of right shape*, not for whether the picks are good.
- **Real Anthropic API behavior.** Mocking is enough for CI.

---

## §11 — Cost envelope (rough)

Per render:

| Item | Approx. tokens / calls | Approx. cost |
|---|---|---|
| HubSpot MCP fetch (paginated) | ~50–150 tool calls; ~30–100K result tokens | $0.30–$1.50 |
| Lemlist + Aimfox + Instantly + Fathom MCP fetches | ~20–60 tool calls; ~10–30K result tokens | $0.10–$0.50 |
| Forward Motion agent (Sonnet) | ~5–10K input + ~1–2K output | $0.05–$0.10 |
| Funnel Leak agent (Sonnet) | ~3–5K input + ~0.5–1K output | $0.02–$0.05 |
| Hygiene agent (Sonnet) | ~5–8K input + ~1–2K output | $0.04–$0.08 |
| Fathom Gap agent (Haiku, batched) | ~3–5K input + ~0.5–1K output | $0.005 |
| **Per render total** | | **~$0.50–$2.20** |

Manual trigger (~5–15 renders/month while iterating): **~$2.50–$33/month**.

Cost driver is HubSpot MCP fetch, not the agents. The slash command session uses whichever Claude model is active — currently Opus 4.7. Switching the slash command session to Sonnet (or Haiku for the orchestration step) would drop the per-render cost by ~3–5×; the agent calls in Phase 3 are independent of this choice. If costs surprise, switching session model is the first lever, then reducing fetch scope or paginating less aggressively.

---

## §12 — Open questions & re-evaluation triggers

### §12.1 — Open questions to settle in implementation

1. **Aimfox & Fathom MCP tool surfaces** — docs are thin. We'll discover the actual tool names at runtime via MCP introspection. Risk: a metric the mock needs is not exposed by the MCP. Action: connect Aimfox + Fathom MCPs first thing in implementation; document tool surface inline in the slash command markdown.
2. **HubSpot Marketing-Hub-scoped properties.** Page 1 §04–05 (channel attribution) uses `hs_analytics_source`, which is standard. If the build needs a Marketing-Hub-scoped property later (e.g., for `hs_marketing_email_*` fields), we'll hit the scope wall the mock already documents. Action: surface the limitation in `dashboard_layout.yaml` as a section toggle, default-off any section dependent on restricted scope.
3. **Fathom call type filtering.** Sai's sales calls vs. delivery review calls share the same Fathom workspace. We need a filter (host? call type? title pattern?) — TBD until we see the Fathom MCP's actual tool surface and field names.
4. **`dashboard_window_prompt.yaml` primary 4 options.** Suggested: `last-7d`, `current-month`, `current-quarter`, `last-quarter`. Bhuvanesh to confirm or override after first few renders.

### §12.2 — Re-evaluation triggers

These are the lights that, when on, mean v1's tradeoffs have stopped paying:

| Trigger | Architectural response |
|---|---|
| Render time > 10 min consistently | Caching layer (probably JSONB) becomes worth it |
| Same agent correction recurring (e.g., "Forward Motion always misses X") | Prompt iteration; if persistent → storage for memory |
| Akil/Sai start asking for the URL | Re-enable Supabase Storage surface |
| Manual trigger fatigue | CronCreate scheduling |
| "What changed since last week?" comes up | Cross-render diffing — requires storage |
| Sai brief becomes priority | Fold into master spec P6 (separate workstream) |
| Cost surprises (agents) | Switch one Sonnet agent to Haiku |
| Cost surprises (MCP fetch) | Reduce fetch scope; paginate less aggressively |

---

## §13 — References

- Master spec: `docs/superpowers/specs/2026-05-05-leadle-os-design.md`
- Project memory: `CLAUDE.md`
- Dashboard mock: `/home/bhuvanesh/Downloads/leadle-dashboard-2026-05-04 (1).html`
- Leadle context: `/home/bhuvanesh/Downloads/LEADLE_CONTEXT.md`
- MCP setup docs:
  - HubSpot: `claude.ai`-managed (already configured)
  - Lemlist: <https://developer.lemlist.com/mcp/setup#claude-code>
  - Aimfox: <https://help.aimfox.com/en/articles/13230384-aimfox-mcp-x-claude>
  - Fathom: <https://developers.fathom.ai/mcp-docs/claude>
  - Instantly: <https://help.instantly.ai/en/articles/12980002-instantly-mcp-model-context-protocol>

### MCP install commands (one-time setup)

```bash
claude mcp add --transport http lemlist  https://app.lemlist.com/mcp
claude mcp add --transport http aimfox   https://mcp.aimfox.com
claude mcp add --transport http instantly "https://mcp.instantly.ai/mcp/$INSTANTLY_API_KEY"
claude mcp add fathom -- npx mcp-remote@latest https://api.fathom.ai/mcp
```

(HubSpot MCP is `claude.ai`-managed and already configured.)

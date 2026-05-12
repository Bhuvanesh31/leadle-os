---
description: Render the Leadle 4-tab dashboard from live MCP data
allowed-tools: AskUserQuestion, Bash, mcp__claude_ai_HubSpot__*, mcp__lemlist__*, mcp__instantly__*, mcp__fathom__*
---

# /render-dashboard

You are rendering the Leadle dashboard. Follow this protocol exactly.

## Phase 0 — Window selection

1. Read `config/dashboard_windows.yaml` and `config/dashboard_window_prompt.yaml`.
2. Compute today's date (use `date "+%Y-%m-%d"` via Bash) and FY quarter context.
3. Use `AskUserQuestion` to ask:

   > "What time window for this dashboard?
   >  Today: {today} · Current FY quarter: {q_label}"

   Options: the 4 in `primary_options` from the prompt YAML, plus "Other (specify)".

4. If "Other" → second `AskUserQuestion` listing every window in `supported_windows` from `dashboard_windows.yaml`.

5. Resolve the window by running:

   ```bash
   source .venv/bin/activate && python -c "
   from datetime import date
   from dashboard.compute.windows import resolve_window
   import json
   spec = resolve_window('<arg>', date.today())
   print(json.dumps({'name': spec.name, 'label': spec.label,
                     'start': spec.start.isoformat(), 'end': spec.end.isoformat(),
                     'prior_start': spec.prior_start.isoformat(),
                     'prior_end': spec.prior_end.isoformat()}))
   "
   ```

6. Show the resolved range and ask the user to confirm before proceeding.

## Phase 1 — Fetch from MCPs

Call each MCP for the data slices documented in spec §6. For each source, log "Fetching <source>..." before the call. On failure, mark `available: false, error: <msg>` and continue.

**HubSpot:**
- `mcp__claude_ai_HubSpot__search_crm_objects` for **deals** — use TWO filterGroups (OR'd by HubSpot):
  - Group 1 (active pipeline regardless of age): `pipeline EQ "1906293444"` AND `dealstage IN [open stages: 3022488285..3022488291]`
  - Group 2 (closed in window): `pipeline EQ "1906293444"` AND `dealstage IN ["3022478048", "3022478049"]` AND `closedate GTE <window.start>` AND `closedate LTE <window.end>`
  - Then **drop closed-lost deals whose createdate is before `<window.start>`** (these are admin/historical cleanup; user-confirmed pattern).
  - Paginate via `offset` until response has fewer than `limit` results. Default limit 200.
- `mcp__claude_ai_HubSpot__search_crm_objects` for **contacts** (used as proxy for HubSpot Leads object, which the MCP doesn't expose):
  - `lifecyclestage EQ "lead"` AND `createdate GTE <window.start>`
  - After fetch, **drop leads whose `hubspot_owner_id` is not in the active-owner allowlist** (Sai 80765353, Akil 77758216, Suraj 82016648, Revops 77502812 — drops Joshna's leads + unassigned).
  - Paginate via `offset` until empty.
- `mcp__claude_ai_HubSpot__search_owners`.
- `mcp__claude_ai_HubSpot__get_properties` for deals (one call, used for stage-ID → label mapping).
- Stage-ID mapping must include **Sales Pipeline stages only** (3022478048..3022488291). Stages from other pipelines map to `"other"` and are dropped from compute.

**Lemlist:**
- `mcp__lemlist__get_campaigns` (list all campaigns, all status).
- `mcp__lemlist__get_campaigns_stats` (pass all campaignIds; startDate=window.start, endDate=window.end, timezone="Asia/Kolkata").
- `mcp__lemlist__get_inbox_conversations` (listId=myConversations, limit=50) — this is the replied-lead feed. Each entry has contactEmail, lastRepliedAt, lastRepliedChannel, lastRepliedMessagePreview. Save into `raw["sources"]["lemlist"]["data"]["leads"]` with `{email, name, replied_at, channel, is_positive}` (set is_positive=false when message preview contains "remove", "no thanks", "not interested", etc.).

**Instantly:**
- `mcp__instantly__list_campaigns` (paginate via starting_after). **Filter to campaigns whose name contains "leadle" (case-insensitive)** — drops client campaigns (Intellikon, PiSystems, Anovate, Ei_*, etc.).
- `mcp__instantly__get_campaign_analytics` twice: once with `start_date=window.start, end_date=window.end` for windowed stats, once with `start_date=2026-01-01, end_date=2026-12-31` for 2026 YTD ("overall" = Leadle's revamped-efforts era, not true lifetime). Save windowed as `stats`, 2026 as `overall_stats` per campaign.
- `mcp__instantly__list_emails` (email_type="received", preview_only=true, limit=100, sort_order="desc"; paginate). Dedupe by `lead` email field, keep most recent timestamp per lead. Flag is_auto_reply when subject matches `/^(Automatic reply|Out of office|Auto-reply)/i`. Save into `raw["sources"]["instantly"]["data"]["leads"]` with `{email, replied_at, channel: "email", is_auto_reply, is_positive: !is_auto_reply}`.

**Fathom:** fetch meetings in window via `mcp__fathom__list_meetings`, then apply this filter before saving to cache (drop everything that doesn't match):
- **Keep** if title (case-insensitive) contains `"discovery meeting"` OR `"proposal discussion"`.
- **Keep** if title matches exactly `Impromptu Google Meet Meeting` or `Impromptu Zoom Meeting` AND the attendee-email set is a subset of `{sai@leadle.in, revops@leadle.in}` (no third-party attendees).
- Drop everything else (Catchup, Sync-up, Review Call, all-hands, etc.).

**Aimfox** (REST fallback while vendor MCP OAuth is broken):

```bash
source .venv/bin/activate && python -m connectors.aimfox.cli \
  --start <window.start> --end <window.end> \
  --name-contains Leadle
```

Requires `AIMFOX_API_KEY` in env (workspace setting → API access). The `--name-contains Leadle` flag drops other-client campaigns we don't care about (case-insensitive substring match). Stdout is the JSON to drop verbatim into `raw["sources"]["aimfox"]`. If `AIMFOX_API_KEY` is missing or the API errors, the CLI prints `{"available": false, "reason": "..."}` — that's the expected degraded path, not a failure.

Aimfox replied-lead fetch (for sections 6/7): GET `https://api.aimfox.com/api/v2/conversations?limit=100`, filter to those where `last_activity_at` is in window (epoch-ms). Save into `raw["sources"]["aimfox"]["data"]["leads"]` with `{name, linkedin_public_id, replied_at, channel: "linkedin", is_positive: true}`. Aimfox is LinkedIn-only — no email available, so cross-joins use name matching.

**Aimfox 2026 per-campaign metrics** (for the overall reply count tile): run the CLI with `--start 2026-01-01 --end 2026-12-31 --name-contains Leadle`. This windows the analytics endpoint to Leadle's revamped-efforts era. Save as `overall_stats` per campaign and `overall_totals` at source level. (Aimfox lifetime = 2026 in current data since campaigns were all created in 2026 — but the date filter keeps it correct as time passes.)

**Lemlist 2026 per-campaign stats** (for overall reply count tile): `mcp__lemlist__get_campaigns_stats` with `startDate=2026-01-01`, `endDate=2026-12-31`, all 36 campaign IDs in one call. Save as `overall_stats` per campaign + `overall_totals` at source level.

Save all results to `.cache/dashboard_raw_<end_date>_<window_name>.json` matching the schema in spec §5 Phase 1.

## Phase 2–5 — Compute, narrate, render, write

Run:

```bash
source .venv/bin/activate && python -m dashboard.render --input .cache/dashboard_raw_<end_date>_<window_name>.json
```

Print the path to the produced HTML file.

## Phase 6 — Surface

Print to chat:

```
Dashboard rendered: <absolute path>
   Window: <window label>
   <degradation report if any>
```

If any source was unavailable, list it. If any agent degraded (check the rendered HTML for `narrative unavailable` strings or read the structlog file), list those.

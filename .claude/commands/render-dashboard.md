---
description: Render the Leadle 4-tab dashboard from live MCP data
allowed-tools: AskUserQuestion, Bash, mcp__claude_ai_HubSpot__*, mcp__lemlist__*, mcp__aimfox__*, mcp__instantly__*, mcp__fathom__*
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
- `mcp__claude_ai_HubSpot__search_crm_objects` for deals (filter `last_modified >= prior_start`), paginate until empty.
- `mcp__claude_ai_HubSpot__search_crm_objects` for contacts (filter `createdate >= today - 365d`), paginate.
- `mcp__claude_ai_HubSpot__search_crm_objects` for companies referenced.
- `mcp__claude_ai_HubSpot__search_owners`.
- `mcp__claude_ai_HubSpot__get_properties` for deals (one call).

**Lemlist, Aimfox, Instantly, Fathom:** introspect the MCP's tool list first via the MCP. Fetch campaigns + leads/conversations + per-campaign stats + (Fathom) meetings. Document tool names you used in a comment at the top of the cache file.

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

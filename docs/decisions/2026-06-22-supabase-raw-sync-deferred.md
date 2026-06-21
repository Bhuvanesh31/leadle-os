# ADR: Supabase raw data sync deferred indefinitely

**Date:** 2026-06-22
**Status:** Decided
**Deciders:** Bhuvanesh (RevOps Architect)

---

## Context

The original Phase 0 spec called for raw JSONB landing zones in Supabase (`raw_hubspot`,
`raw_lemlist`, etc.) with a nightly sync pipeline pulling from source APIs into Supabase,
so analytics scripts query stored data rather than live APIs.

After building 17 working analytics processes that pull directly from source APIs, the
tradeoffs were re-evaluated.

## Decision

**Supabase raw data sync is deferred. Analytics scripts pull live from source APIs.**

Supabase is retained for dashboard hosting (Storage signed URLs) only.

## Rationale

**Arguments against raw sync:**

1. **CRM data changes continuously.** Leads move stages, deals close, calls happen
   throughout the day. A nightly sync means the dashboard always shows data that is
   hours old. On-demand API pulls are more accurate.

2. **Scripts are fast enough.** The 17 analytics processes complete in under 30 seconds
   on a live pull. There is no UX problem requiring a cache.

3. **Single-user, on-demand context.** Phase 1 is one user running analyses interactively.
   The token efficiency argument only matters at scale or for high-frequency automated runs.

4. **Sync overhead is not zero.** A nightly sync requires: API pull, JSONB write to
   Supabase, index maintenance, then a read-back at query time. Net token cost is similar
   to or higher than a direct API pull for infrequent runs.

5. **History via aggregates, not raw records.** The one genuine need for persistence is
   trend data (week-over-week pipeline delta). This is better served by a lightweight
   daily snapshot of ~12 aggregated metrics — not full raw record sync.

**What Supabase raw sync would have enabled:**
- Cross-source joins at query time (Fathom meetings + HubSpot leads in one query)
- True historical reconstruction ("what did the pipeline look like last Tuesday?")
- Automation without live API access at run time

**Why these don't outweigh the costs yet:**
- Cross-source joins are handled in Python at analysis time (slower but simpler)
- Historical reconstruction is not a current requirement
- Automation (P8) will use on-demand API pulls via CronCreate — not sync-dependent

## Consequences

- All 17 analytics scripts pull live from source APIs on every run
- Supabase Storage used for dashboard HTML hosting (unchanged)
- If trend analysis becomes a requirement, add a narrow snapshot script targeting
  aggregated metrics only (not raw records)
- Revisit this decision if: (a) rate limits become a problem, (b) multi-user access
  requires shared data, or (c) historical queries are needed for reporting

## Status of original P0 spec items

| Item | Status |
|---|---|
| `raw_hubspot` landing zone | Deferred |
| `sync_state` table | Deferred |
| `unmatched_review` table | Deferred |
| Supabase Storage for dashboard | In use |
| leadle-os MCP analytics surface | In progress (P1) |

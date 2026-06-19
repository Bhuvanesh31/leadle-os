# Data shape — Client "Prospect list" Google Sheet (UPSTA sample)

Observed 2026-06-17 from sheet `1GgFeDdXpy1ZlDjH8bTWNL_c7m0ihSSO_-iYNyzadCQg`.
This is the per-client onboarding + outreach tracking workbook. Multiple tabs, each a
distinct table. Flattened observations below — **schema not yet typed** (explore-first).

## Tabs / tables observed

1. **ICP definition** — `Offering | Target HQ Location | Channels | Target Market Segment |
   Company Size | Industry Verticals | Roles/Titles | Seniority`. One row per ICP.
   Channels for UPSTA: "LinkedIn, Email, Warm Calling".

2. **Onboarding checklist** — `Item | Status | Responsibility | Target/Actual Completion Date |
   Comments`. Status in {Completed, Pending, Not Applicable}. Useful for an onboarding/health
   strip but secondary to outreach reporting.

3. **Responses tracker (HUMAN-CURATED, qualitative)** — `Channel | Account | Response Date |
   Status | Response | LinkedIn | Name | Job Title | Company | Company Url | Company Web | Loc`.
   - Channel in {LinkedIn, Email, Warm Calling}.
   - Status = human disposition (free text), e.g. "Long follow up". THIS is the warm-lead /
     warm-call layer; it exists ONLY here, not in any API.
   - Volume currently tiny (~1 row) — campaign is young.

4. **Prospect spine** (the "target company list" tabs, several segmented tables, e.g.
   US_Set 1, Singapore_Set 1) — **one row per prospect (person), not per company**. Wide
   (~23 cols) and width VARIES (some tables carry an extra `Start Date` column, shifting
   later columns). Leading cols: `Company Name | Company Country | Company Location | Company
   Linked In URL | Primary Industry | Size (Text) | Account Process(=segment) | First Name |
   Last Name | Full Name | Location | Company Domain | LinkedIn Profile | Title | ...` then
   (added 2026-06-19) the cadence-ID columns `Aimfox ID | Aimfox URN | Instantly ID` (see
   "Update 2026-06-19"). Because the grain is per-prospect and the width varies, parse columns
   by header NAME, not fixed position.

5. **Enriched company list** — `Company name | domain | Revenue USD | Employee count | City |
   Country | ...`.

6. **LinkedIn event export (Aimfox), manual dump** — `Event Type | Company Name | Profile Url |
   Company Url | Prospect Name | Title`. Event Type in {connect, accepted, reply}.
   UPSTA tallies: connect 239, accepted 42, reply 3.

7. **Email event export (Instantly), manual dump** — `Company Name | To Name | Event Type |
   Campaign Name | Event Timestamp | From Email`. Event Type in {email_sent, email_opened,
   link_clicked, email_bounced, auto_reply_received, lead_out_of_office}.
   Campaign Name carries the client key (e.g. `Upsta_SFDI_V1`).
   UPSTA tallies: sent 224, opened 129, clicked 41, bounced 16, auto_reply 1, OOO 1.

8. **Industry reference table** — lookup dump, ignore for dashboard.

## Architectural implications

- Quant funnel (tabs 6/7) duplicates what the Instantly + Aimfox APIs serve live. Prefer LIVE
  API pull for freshness; the manual export is a cost to eliminate.
- Qualitative layer (tab 3) and the onboarding/ICP/target tabs are sheet-only → must be read
  from the sheet.
- Client scoping key: campaign/sequence name prefix (`Upsta_*` in Instantly; "UPSTA" tag in
  Aimfox). Confirmed reliable for Instantly (5 campaigns matched).
- The sheet is large (~640k chars across all tabs); read per-tab/range, never whole.
- **Pagination**: the Drive flatten splits each large table into MULTIPLE consecutive blocks,
  each re-emitting the SAME header row. A parser that reads only the first block under a
  header undercounts badly (observed: email/LinkedIn KPIs came out 0). Read ALL blocks under
  each header signature and concatenate.

## Update 2026-06-19 — per-prospect cadence IDs (identity backbone)

The prospect spine (tab 4) now carries three per-prospect identifier columns, injected
upstream (same idea as Clay's HubSpot-ID injection described in CLAUDE.md, but for the
outreach tools):

| Column | Example | What it is |
|---|---|---|
| `Aimfox ID`  | `229856678` | Aimfox's native numeric lead id |
| `Aimfox URN` | `ACoAAA2zVaYBQXGrEKQf8TU4u1pSCTjzT45lh2Y` | LinkedIn member URN |
| `Instantly ID` | `019e89de-c4f3-7c29-9e9b-752159d50611` | Instantly lead id (UUIDv7) |

Population is **partial and meaningful** — a blank means the prospect has not entered that
channel's cadence yet. Observed patterns on real rows: all-three (in both cadences),
Instantly-only (email only), Aimfox-only (LinkedIn only), all-blank (not yet started). This
matches the operator's statement: "missing id ⇒ not in cadence; some prospects are
Instantly-only, some Aimfox-only."

**Uses:**
- **v1 (now), deterministic, no event join:** count unique prospects reached per channel
  (distinct non-empty `Aimfox ID` = LinkedIn reached; distinct `Instantly ID` = email
  reached) and the overlap (rows holding both = touched on both channels). Drives the new
  "Channel reach" block. Dedupe on the ID value itself (it is the unique key).
- **v2 (live pull), deterministic join key:** `Instantly ID` → Instantly lead → that lead's
  email events; `Aimfox ID`/`URN` → Aimfox lead → invite/accept/reply events. This replaces
  the fragile company-name + `Upsta_*` campaign-prefix matching with an exact per-prospect
  join. It is the proper backbone for `live_source.py`.

**Caveat (verify before building the v2 join):** confirmed these IDs exist and are populated
on the spine and that their formats are the platforms' native ids; have NOT yet round-tripped
a fetch through the Instantly/Aimfox APIs (Instantly MCP was disconnected, Aimfox needs
re-auth). The event-dump tabs (6/7) do NOT carry these IDs — they are keyed by Profile URL /
email — so in v1 the IDs add the reach layer but do not retro-join to the manual dumps.

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

4. **Target company lists** (several segmented tables, e.g. US_Set 1, Singapore) —
   `Company Name | Country | Location | LinkedIn URL | Primary Industry | Size | Account Process |
   Domain`. The addressable universe (denominator for coverage).

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
- The sheet is large (~600k chars across all tabs); read per-tab/range, never whole.

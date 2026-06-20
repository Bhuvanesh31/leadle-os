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
- **CRITICAL — do NOT ingest via the Drive text flatten** (`read_file_content` / the
  natural-language rendering). For a workbook this size it is **silently truncated**: the
  rendering returned only ~261 of 1,229 prospects (US cut at ~150/942, SG at ~111/287) with
  NO error, just fewer rows. Every reach number came out ~5x low and internally consistent —
  the worst kind of wrong. **Ingest the raw XLSX instead**: Drive `download_file_content` with
  `exportMimeType = application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`, then
  parse cell-by-cell with `openpyxl` (read_only, data_only). This reads every row of every tab.
  The legacy `--workbook <text dump>` path in `dashboard/client/render.py` inherits the
  truncation and must move to XLSX ingestion before the numbers can be trusted.

## Prospect spine tabs — real structure (verified 2026-06-19 via XLSX)

The per-prospect spine lives in two tabs (exact names, mind the spacing):

| Tab | People (excl. header) | Aimfox ID | Instantly ID | Both | Neither |
|---|---|---|---|---|---|
| `Prospect Data-US` (no space)      | 942   | 642 | 664 distinct | 529 | 162 |
| `Prospect Data- Singapore` (space) | 287   | 165 | 198 distinct | 137 | 60  |
| **Combined**                       | 1,229 | 807 | 862 distinct | 666 | 222 |

Header is 23 cols; the three ID columns are the last three (`Aimfox ID | Aimfox URN |
Instantly ID`), but resolve by NAME not position (the US tab has no `Start Date` col; some
segments do). A few Instantly IDs repeat (866 present → 862 distinct = ~4 dupes, same person
on two rows) — dedupe on the ID value, not the row. The 21 full tab list also includes
`Accounts Data-*`, event-export tabs (`Invite Sent`, `Connection Accepted`, `First Email
Sent`, `Email Opened`, ...), `Response Tracker`, `DNC List`, and `Webhook -*` mirrors.

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

**Round-trip VERIFIED 2026-06-19 (both join keys live):**
- **Aimfox:** sheet `Aimfox ID` (numeric) → `GET https://api.aimfox.com/api/v2/leads/{id}`
  returns HTTP 200 with the full profile and `lead.origins` = the campaign(s) it belongs to
  (e.g. `Upsta_US_SFDIP_CFO_V1`). The numeric ID is the key. The **`Aimfox URN` is NOT a
  lookup key** — `/leads/{urn}` returns 422. The collection route `/leads` (no id) 404s; only
  the item route works. 7/7 sampled IDs (US + SG) resolved.
- **Instantly:** sheet `Instantly ID` → `get_lead(id)` (MCP) returns `campaign` (one of the 5
  `Upsta_*` ids), per-lead `email_open_count` / `email_reply_count` / `email_click_count`,
  `status`, and full payload (Title, Process, Country, LinkedIn URL). 3/3 sampled resolved.
- **Cross-channel proof:** a prospect with both IDs (Christopher Garisek, aid `229856678` /
  iid `019e89de-c4f3…`) resolves on both; Aimfox `public_identifier` and the Instantly
  payload LinkedIn URL share the same slug → same human, both channels, confirmed by one row.

**Reach reconciliation (sheet distinct IDs vs live API reach):** Aimfox 807 sheet IDs vs 780
live reached (~3%); Instantly 862 sheet IDs vs 870 live reached (~1%). The sheet runs slightly
ahead because an ID is stamped on *add*, while "reached" needs a send to have fired (the gap is
the in-flight queue). **"Reached on both" (666) is computable ONLY from the sheet** — it is the
sole place one row holds both an Aimfox ID and an Instantly ID; neither API can join to the
other. This is why the spine stays in the pipeline as the identity bridge.

The event-dump tabs do NOT carry these IDs — they are keyed by Profile URL / email — so they
do not retro-join to the ID backbone.

## Update 2026-06-19 — webhook reply tabs (`Webhook - LinkedIn` / `Webhook - Email`)

These two tabs are the **reply + segmentation source** (verified via XLSX, repeated-header
pagination handled). They carry richer, timestamped event streams than the manual event-dump
tabs (6/7) and, crucially, a `Reply Sentiment` column.

**`Webhook - LinkedIn`** (897 rows, 2026-05-14 → 2026-06-19). Cols:
`Event Type | Company Name | Profile Url | Company Url | Prospect Name | Title | Sender
Profile | Campaign Name | Timestamp | Date Extraction | Connection request sent date |
Connection Accepted Date | Reply Date | Reply Messages | Industry | Size | Company Country |
Process | Variant | Reply Sentiment`.
- `Event Type` ∈ {`connect`=invite sent, `accepted`, `message`=sequence step, `reply` /
  `campaign_reply`=inbound human reply, `campaign_ended`}.
- Association key (per operator): **Aimfox ID** — resolve `Profile Url` → spine row → `Aimfox
  ID`. (The tab itself stores `Profile Url`, not the numeric ID.)
- **`Variant` is 100% empty** (897/897) in the sheet — but "which message/variant worked" IS
  answerable from the **Aimfox API**: `GET /campaigns/{id}` returns `flows[]`, each
  `PRIMARY_CONNECT` flow carries the connection-note `template.message` (the actual variant
  text). Per-variant performance comes from `GET /analytics/interactions?campaign_id=…`
  (`sent_connections`, `accepted_connections`, `replies`) — and `&flow_id=…` filters to a
  single A/B flow (verified: campaign total 8 vs flow-filtered 1). The campaign *name* is the
  variant key (`V1/V2/V3_A-C`, `SFDIP_CFO_V1/V2`). Ranked May+June: `Upsta_US_PMP_V1` is the
  only variant that drew replies (3 / 2.2%); `Reconciliation_V3_*` are dead (0% accept).
  Extractor `/tmp/afx_variants.py` → `/tmp/afx_variants.json`.
- Replies are rare: May 2 (1 neutral, 1 negative), June 2 (1 neutral, 1 untagged). **0 positive.**

**`Webhook - Email`** (2389 rows, **2026-06-03 → 2026-06-19 only** — email is a *single month*,
no May baseline). Cols: `Company Name | To Name | Event Type | Campaign Name | Event Timestamp
| From Email | To Email | Reply Message | Sent Date | Email Open date | Reply Date | Email
click date | Sequence Number | Title | Website | Company Size | Company Country | Industry |
Prospect Linkedin Profile | Reply Sentiment`.
- `Event Type` ∈ {`email_sent`, `email_opened`, `link_clicked`, `email_bounced`,
  `auto_reply_received`, `lead_out_of_office`, `campaign_completed_for_lead_without_reply`}.
  **There is NO human-reply event type** and `Reply Sentiment` is 100% empty → human email
  replies = 0. `auto_reply_received`/`lead_out_of_office` are automated, not human replies.
- Association key (per operator): **`Prospect Linkedin Profile`** column → spine row.
- **Rates are unique-prospect, not event count** (events double-count opens). June: 870
  prospects sent, 766 delivered, 224 unique opened (29.2% of delivered), 21 clicked (2.7%).
  **Bounce is event-based** (operator's call): 105 `email_bounced` / 1661 `email_sent` events
  = **6.3%** (above the <4% benchmark).

**Leads rule (operator):** any *positive* response = a lead. Current count = **0** (0 positive
replies on either channel). **Upsta benchmarks:** open 20%, click 2%, positive replies 4/mo,
total replies 12/mo, bounce <4%. Extractor: `/tmp/reply_metrics.py` → `/tmp/reply_metrics.json`.

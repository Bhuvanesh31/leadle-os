# /fathom-crm-gap

Finds Fathom meetings (discovery calls, proposal discussions) that have no
matching HubSpot contact, lead, or active deal. These are calls that happened
but were never logged in the CRM — a signal that a deal was dropped or never
created.

Requires: FATHOM_API_KEY in .env (currently not set — script degrades to 0 results).
Add the key to unlock this analysis.

Match strategy (email_domain_first from config/dashboard_rules.yaml):
1. Exact email match → HubSpot contact
2. Email domain match → HubSpot company
3. For matched contact/company, check for active lead or open deal

Gap states:
- no_contact          — no HubSpot record at all for the attendee domain
- contact_no_lead     — contact exists but no active lead
- contact_no_deal     — company exists but no active deal in the pipeline

Meeting filter (from fathom_filter config):
- Title contains "discovery meeting" or "proposal discussion"
- OR: Impromptu Google Meet/Zoom where all attendees are internal

Internal Leadle attendees (@leadle.in) are excluded from matching.
Only the primary external attendee email is used for matching.

## Setup

Add FATHOM_API_KEY to .env:
  FATHOM_API_KEY=your_key_here

The Fathom API key can be found in Settings → Integrations → API in the Fathom app.

## Usage

```
/fathom-crm-gap
/fathom-crm-gap --period last-month
/fathom-crm-gap --start 2026-05-01 --end 2026-05-31
```

## Steps

### Step 1 — Run the script

```bash
cd /home/bhuvanesh/AI_Native_Workspace/30-leadle-systems/leadle_gtm_intelligence
set -a && source .env && set +a
python -m analytics.fathom_crm_gap $ARGUMENTS --json /tmp/fathom_gap.json
```

### Step 2 — Check for gaps

If FATHOM_API_KEY is not set, the output will show `Fathom available: False`
and 0 results. Prompt the user to add the key.

If available, read `/tmp/fathom_gap.json`. Key sections:
- `summary`: meetings_fetched, meetings_relevant, gaps, covered
- `gaps`: list of meetings with no CRM record — each has title, scheduled_date,
  contact_email, company (guessed from domain), and gap_state
- `covered`: meetings that did match a CRM record (excluded from action required)

### Step 3 — Write the narrative

In Leadle voice:
1. How many relevant meetings in the window? What fraction had no CRM record?
2. For each gap: name the company (derived from email domain if no contact),
   what stage the CRM gap leaves them at, and what action to take
   (create contact + lead, or link existing contact to a deal)
3. Flag recurring domains in gaps — same company showing up repeatedly with
   no CRM entry is a workflow problem, not a one-off miss
4. Recommended action: for each gap with gap_state = no_contact, create a
   HubSpot contact manually; for contact_no_lead, start a lead in Meeting Booked

### Step 4 — Show results

Output the narrative, then HTML report path.

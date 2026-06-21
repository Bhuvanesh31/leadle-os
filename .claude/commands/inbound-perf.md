# /inbound-perf

Inbound lead funnel performance over a time window. Funnel/conversion view
to complement /inbound-lead-analysis (which covers current-state health).

Three views:
- **New leads** in the window — volume and source breakdown
- **Decisions** in the window — leads advanced to deal OR archived (regardless of when created)
- **Active from window** — leads created this window that haven't been decided yet

Conversion rate = advances / (advances + archives) for leads with a decision.

Sources: inbound (Web Form, LinkedIn Inbound, Reference, etc.) from config/inbound_scoring.yaml.
Outbound-sourced leads appear as "Other / Outbound" — useful to see the cross-contamination rate.
Leads with no source set appear as "Unknown" — these are a data quality issue.

## Usage

```
/inbound-perf
/inbound-perf --period last-month
/inbound-perf --start 2026-05-01 --end 2026-05-31
```

## Steps

### Step 1 — Run the script

```bash
cd /home/bhuvanesh/AI_Native_Workspace/30-leadle-systems/leadle_gtm_intelligence
set -a && source .env && set +a
python -m analytics.inbound_perf $ARGUMENTS --json /tmp/inbound_perf.json
```

### Step 2 — Read the JSON

Read `/tmp/inbound_perf.json`. Key sections:
- `summary`: new_leads, advanced_to_deal, archived, overall_conversion_rate_pct, still_active_from_window
- `source_conversion`: per-source conversion rate (source, advanced, archived, rate)
- `advanced_leads`: list of leads promoted to deal in window (name, source, date)
- `active_from_window`: leads created in window still in active stages

### Step 3 — Write the narrative

4–5 paragraphs in Leadle voice (conversational, short sentences, no AI phrases, no em dashes):
1. Volume summary: how many new leads, what's the conversion rate on decided leads, how many still pending
2. Source breakdown: which sources drove new leads, which converted best
3. Web Form specifically: it's Leadle's primary inbound channel — call out its rate vs. overall
4. Unknown source problem: any advances with no source set = data quality gap, flag it
5. Still-active cohort: who's in-flight from this window and in which stages — is the pipeline healthy?

### Step 4 — Show results

Output the narrative, then HTML report path.

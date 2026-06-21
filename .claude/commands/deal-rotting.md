# /deal-rotting

Identifies rotting active deals in the Leadle sales pipeline.

Two independent rot signals (same model as /lead-rotting):
- **Activity-stalled**: no logged activity for >= stalled_deal_days (config/dashboard_rules.yaml)
- **Stage-stuck**: in same pipeline stage for >= rotting_deal_days

Severity:
- CRITICAL = both signals firing
- STALLED = only no-activity signal
- STUCK = only stage-progression signal
- OK = fresh on both dimensions

Activity signal uses `notes_last_activity_date` (logged calls/emails/meetings on deal).
Falls back to `hs_lastmodifieddate` when absent — marked with `~` in output.

Covers all 13 active deals in pipeline 1906293444.

## Usage

```
/deal-rotting
/deal-rotting --out /tmp/rotting.html
```

## Steps

### Step 1 — Run the script

```bash
cd /home/bhuvanesh/AI_Native_Workspace/30-leadle-systems/leadle_gtm_intelligence
set -a && source .env && set +a
python -m analytics.deal_rotting $ARGUMENTS --json /tmp/deal_rotting.json
```

### Step 2 — Read the JSON

Read `/tmp/deal_rotting.json`. Key sections:
- `severity_counts`: Critical/Stalled/Stuck/OK totals
- `thresholds`: stalled_deal_days, deal_stage_stuck_days (from config)
- `deals`: each deal with severity, days_since_activity, days_in_stage, amount, close_date

### Step 3 — Write the narrative

3–5 paragraphs in Leadle voice (conversational, short sentences, no AI phrases, no em dashes):
1. How many rotting deals, split by severity
2. The pattern: which stages are stuck, which deals are most at risk (especially ones with close dates in the past)
3. For STUCK deals: specific note on whether activity is logged or proxy-only (all `~` means no logged CRM activity at all)
4. For CRITICAL deals (if any): specific calls to action
5. Flag any deals with close dates already past — Rodeme (close 2026-06-20) is one example

### Step 4 — Show results

Output the narrative, then HTML report path.

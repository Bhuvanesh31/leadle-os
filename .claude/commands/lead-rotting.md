# /lead-rotting

Identifies rotting active leads across both inbound and outbound pipelines.

Two independent rot signals:
- **Activity-stalled**: no logged activity for >= stalled_lead_days (config/dashboard_rules.yaml)
- **Stage-stuck**: in same pipeline stage for >= lead_stage_stuck_days

Severity:
- CRITICAL = both signals firing
- STALLED = only no-activity signal
- STUCK = only stage-progression signal
- OK = fresh on both dimensions

Includes all active leads (18 currently — 9 inbound + 9 outbound).

## Usage

```
/lead-rotting
/lead-rotting --out /tmp/rotting.html
```

## Steps

### Step 1 — Run the script

```bash
cd /home/bhuvanesh/AI_Native_Workspace/30-leadle-systems/leadle_gtm_intelligence
set -a && source .env && set +a
python -m analytics.lead_rotting $ARGUMENTS --json /tmp/lead_rotting.json
```

### Step 2 — Read the JSON

Read `/tmp/lead_rotting.json`. Key sections:
- `severity_counts`: Critical/Stalled/Stuck/OK totals
- `thresholds`: stalled_lead_days, lead_stage_stuck_days (from config)
- `leads`: each lead with severity, days_since_activity, days_in_stage

### Step 3 — Write the narrative

3–5 paragraphs in Leadle voice (conversational, short sentences, no AI phrases, no em dashes):
1. How many rotting leads, split by severity (Critical vs Stalled)
2. The pattern: which stages are the rot concentrated in?
3. For Critical leads: specific calls to action (who to reach, how long they've been stuck)
4. For Stalled leads: lighter follow-up note
5. What the thresholds mean — are they calibrated right? (e.g., if 15/18 leads are Critical, the threshold might be too aggressive)

### Step 4 — Show results

Output the narrative, then HTML report path.

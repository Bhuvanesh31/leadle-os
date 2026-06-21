# /icp-corrector

Scores all active leads using the ICP config (inbound_scoring.yaml + outbound_scoring.yaml)
and flags three categories of mismatches:

- **HOT_UNDERSTAGED**: score >= hot threshold (65) but in an early stage (order <= 2).
  These leads need immediate attention.
- **COLD_OVERSTAGED**: score < warm threshold (35) AND in an actively-worked stage (rotting=true,
  order >= 5 = Meeting Proposed) AND has enough data to trust the score.
  These leads may be consuming meeting slots they shouldn't.
- **ENRICHMENT_GAP**: missing job title, revenue, or funding — score may be deflated.
  Needs Clay re-enrichment before the score is trustworthy.

Score breakdown: decision_maker (40) + revenue (25) + funding (20) + spend_capacity (15) = 100.

Last run (2026-06-21): 72 active leads — 0 HOT understaged, 2 COLD overstaged,
67 enrichment gap, 3 OK.

## Usage

```
/icp-corrector
/icp-corrector --out /tmp/icp.html
```

Note: makes one company association lookup per active lead. Expect 60–90 seconds for ~70 leads.

## Steps

### Step 1 — Run the script

```bash
cd /home/bhuvanesh/AI_Native_Workspace/30-leadle-systems/leadle_gtm_intelligence
set -a && source .env && set +a
python -m analytics.icp_corrector --json /tmp/icp_corrector.json
```

### Step 2 — Read the JSON

Read `/tmp/icp_corrector.json`. Key sections:
- `summary`: counts per flag category
- `hot_understaged`: high ICP leads stuck in early stages — action required
- `cold_overstaged`: low ICP leads at Meeting Proposed — worth a second look
- `enrichment_gap`: leads whose scores can't be trusted due to missing data
- `all_leads`: full scored list sorted by severity

### Step 3 — Write the narrative

3–5 paragraphs in Leadle voice (conversational, short sentences, no AI phrases, no em dashes):
1. Overall picture: are leads placed correctly or is the pipeline misaligned?
2. HOT understaged (if any): specific leads Sai should move on immediately
3. COLD overstaged: Mohammed (Product Project Manager, score 22) and Mavia (Stylist, score 0)
   at Meeting Proposed — are these the right people to be having meetings with?
4. Enrichment gap: 67 leads where missing titles/financials mean scores are 0 or deflated.
   The pattern (inbound form leads with no job title) — enrichment priority list
5. Recommended action: trigger Clay re-enrichment on the enrichment-gap cohort

### Step 4 — Show results

Output the narrative, then HTML report path.

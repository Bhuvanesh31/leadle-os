# /outbound-lead-analysis

Diagnostic snapshot of Leadle's outbound pipeline — stage distribution, ICP fit,
data quality gaps, and staleness — followed by a short narrative for Sai or Bhuvanesh.

This is process #8. It reuses the same HubSpot data as /outbound-lead-scoring but
focuses on aggregate patterns rather than individual lead rank.

## Usage

```
/outbound-lead-analysis                        # outbound leads only
/outbound-lead-analysis --enrich-from FILE     # pass web-enriched company data
```

## Steps

### Step 1 — Run the analysis

```bash
cd /home/bhuvanesh/AI_Native_Workspace/30-leadle-systems/leadle_gtm_intelligence
set -a && source .env && set +a
python -m analytics.outbound_lead_analysis $ARGUMENTS --json /tmp/outbound_analysis.json
```

### Step 2 — Read the JSON

Read `/tmp/outbound_analysis.json`. It contains sections:
summary, stage_distribution, campaign_breakdown, icp_summary, data_quality,
staleness, priority_flags, top_leads.

### Step 3 — Write the narrative

Write a short analysis (3–5 paragraphs) based on the JSON data. Tone rules from LEADLE_CONTEXT.md:
- Conversational, thinking-out-loud, dry humor, short sentences
- Forbidden: "leverage", "unlock", "ecosystem", "delve", preachy endings, em dashes
- No listy structure where prose works better
- Captions/headers that add POV, not summaries

Cover:
1. The headline picture (how many outbound, Hot/Warm/Cold split, avg score vs inbound)
2. Staleness — the key operational question: are leads being worked after the meeting is proposed?
3. Who Sai should call next and why (Hot leads, ranked by staleness × ICP score)
4. What's missing from the data and how it's capping scores
5. One observation on the stage distribution (7 stuck at Meeting Proposed is a pattern)

Do NOT list the JSON fields back. Synthesise. If 3/3 Hot leads are stale after 10+ days,
that's a follow-up execution problem, not a targeting problem.

### Step 4 — Show results

Output the narrative to the user, then show the HTML report path.

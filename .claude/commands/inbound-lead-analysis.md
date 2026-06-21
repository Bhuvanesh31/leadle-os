# /inbound-lead-analysis

Diagnostic snapshot of Leadle's inbound pipeline — stage distribution, ICP fit,
data quality gaps, and staleness — followed by a short narrative for Sai or Bhuvanesh.

This is process #6. It reuses the same HubSpot data as /inbound-lead-scoring but
focuses on aggregate patterns rather than individual lead rank.

## Usage

```
/inbound-lead-analysis                        # inbound leads only (default)
/inbound-lead-analysis --all-sources          # include outbound leads too
/inbound-lead-analysis --enrich-from FILE     # pass web-enriched company data
```

## Steps

### Step 1 — Run the analysis

```bash
cd /home/bhuvanesh/AI_Native_Workspace/30-leadle-systems/leadle_gtm_intelligence
set -a && source .env && set +a
python -m analytics.inbound_lead_analysis $ARGUMENTS --json /tmp/inbound_analysis.json
```

### Step 2 — Read the JSON

Read `/tmp/inbound_analysis.json`. It contains the full data structure with sections:
summary, stage_distribution, source_breakdown, icp_summary, data_quality,
staleness, priority_flags, top_leads.

### Step 3 — Write the narrative

Write a short analysis (3–5 paragraphs) based on the JSON data. Tone rules from LEADLE_CONTEXT.md:
- Conversational, thinking-out-loud, dry humor, short sentences
- Forbidden: "leverage", "unlock", "ecosystem", "delve", preachy endings, em dashes
- No listy structure where prose works better
- Captions/headers that add POV, not summaries

Cover:
1. The headline number (how many inbound leads, how many Warm/Hot, overall score average)
2. What's holding scores down (top data quality gap, source mix)
3. Staleness picture (are leads being worked or sitting?)
4. Priority flags — who Sai should contact next and why
5. One concrete action (e.g., "add job title capture to the web form" if that's the top gap)

Do NOT just list the JSON fields back. Synthesise. If 9/9 leads have no job title,
that's a web form design problem, not an individual lead problem.

### Step 4 — Show results

Output the narrative to the user, then show the HTML report path.

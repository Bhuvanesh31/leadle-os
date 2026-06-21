# /lost-deals

Lost deals analysis over a time window. Surfaces volume, pipeline value lost,
loss reason clusters, stage of loss (where deals drop off), and avg time in pipeline.

Default window: last-quarter. Use --period last-month for recent, data-rich deals
(historical bulk data pre-dating the pipeline has no stage/reason data).

Loss reason clusters (keyword-matched from free-text closed_lost_reason):
- Unresponsive / No-show
- Not ICP fit
- Budget / Pricing
- Not ready / Too early
- Lost to competition
- No authority / Wrong stakeholder
- Payment / Terms
- No reason recorded (field was empty)

May 2026: 27 lost deals, $1M pipeline, avg 16d in pipe.
Top reasons: No reason recorded (44%), Budget/Pricing (26%), Unresponsive (11%).
Top stage of loss: Discovery Call (13), Proposal Made (8).

## Usage

```
/lost-deals
/lost-deals --period last-month
/lost-deals --start 2026-05-01 --end 2026-05-31
```

## Steps

### Step 1 — Run the script

```bash
cd /home/bhuvanesh/AI_Native_Workspace/30-leadle-systems/leadle_gtm_intelligence
set -a && source .env && set +a
python -m analytics.lost_deals $ARGUMENTS --json /tmp/lost_deals.json
```

Use --period last-month for recent data. Default (last-quarter) includes
historical bulk data with no reasons or stage info.

### Step 2 — Read the JSON

Read `/tmp/lost_deals.json`. Key sections:
- `summary`: total_lost, total_amount_lost, avg_days_in_pipe
- `reason_clusters`: sorted by count, with percentage
- `stage_of_loss`: which funnel stage the deal was last active in before Lost
- `deals`: per-deal detail (name, lost_date, stage, amount, reason_raw, reason_cluster)

### Step 3 — Write the narrative

3–4 paragraphs in Leadle voice:
1. Volume and pipeline value: how severe is the loss picture?
2. Where deals die: stage_of_loss breakdown — if Discovery Call is the top, that's a
   qualifying problem; if Proposal Made is top, that's a pricing/value problem
3. Why deals die: reason clusters — call out the "No reason recorded" rate as a
   data quality issue (44% in May means nearly half of losses have no diagnosis)
4. Time in pipe: 16d average means short sales cycles — are we qualifying fast enough
   or just failing fast?
5. Recommended action: for Budget/Pricing losses, check if ICP fit is low (cross with /icp-corrector)

### Step 4 — Show results

Output the narrative, then HTML report path.

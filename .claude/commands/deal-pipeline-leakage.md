# /deal-pipeline-leakage

Run the deal pipeline leakage report for Leadle's Sales Pipeline.

Shows how many deals ever entered each stage, the reach percentage (% of all deals
that touched each stage), the absolute drop between stages, and the biggest leak.

## Usage

```
/deal-pipeline-leakage                          # all-time
/deal-pipeline-leakage --period month           # this month
/deal-pipeline-leakage --period quarter         # current quarter
/deal-pipeline-leakage --period last-quarter
/deal-pipeline-leakage --period ytd
/deal-pipeline-leakage --period fy              # Indian FY (Apr–Mar)
/deal-pipeline-leakage --start 2026-01-01 --end 2026-06-30   # custom range
```

Periods: `week`, `last-week`, `month`, `last-month`, `quarter`, `last-quarter`, `ytd`, `fy`, `last-fy`.

## Steps

1. Run the script:
   ```bash
   cd /home/bhuvanesh/AI_Native_Workspace/30-leadle-systems/leadle_gtm_intelligence
   python -m analytics.deal_pipeline_leakage $ARGUMENTS
   ```
2. Show the user the text summary and the HTML report path.
3. If the pipeline or stage IDs change in HubSpot, update `config/hubspot_pipeline.yaml`
   under the `deals:` section — no code change needed.

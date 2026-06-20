# /lead-pipeline-leakage

Run the lead pipeline leakage report for Leadle's own HubSpot lead funnel.

Shows how many leads ever entered each stage, the conversion rate between stages,
the single biggest drop-off, and where leads currently sit.

## Usage

```
/lead-pipeline-leakage                          # all-time
/lead-pipeline-leakage --period month           # this month
/lead-pipeline-leakage --period quarter         # current quarter
/lead-pipeline-leakage --period last-quarter
/lead-pipeline-leakage --period ytd
/lead-pipeline-leakage --period fy              # Indian FY (Apr–Mar)
/lead-pipeline-leakage --start 2026-01-01 --end 2026-06-30   # custom range
```

Periods: `week`, `last-week`, `month`, `last-month`, `quarter`, `last-quarter`, `ytd`, `fy`, `last-fy`.

## Steps

1. Run the script:
   ```bash
   cd /home/bhuvanesh/AI_Native_Workspace/30-leadle-systems/leadle_gtm_intelligence
   python -m analytics.lead_pipeline_leakage $ARGUMENTS
   ```
2. The script prints a text summary to stdout and writes an HTML report to `reports/`.
3. Show the user the text summary and the path to the HTML file.
4. If the script errors, check:
   - `HUBSPOT_PRIVATE_TOKEN` is set in `.env`
   - `config/hubspot_pipeline.yaml` stage IDs match the live HubSpot pipeline
     (verify with HubSpot MCP `get_properties` on the leads object if stage counts come back zero)

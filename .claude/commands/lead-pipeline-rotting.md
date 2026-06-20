# /lead-pipeline-rotting

Run the lead pipeline rotting report. Flags active (non-archived) leads that have:
- No future task scheduled, OR
- No activity in the past N days (default: 1, from config/hubspot_pipeline.yaml)

## Usage

```
/lead-pipeline-rotting
/lead-pipeline-rotting --threshold 3   # override the inactivity threshold
```

## Steps

1. Run the script:
   ```bash
   cd /home/bhuvanesh/AI_Native_Workspace/30-leadle-systems/leadle_gtm_intelligence
   python -m analytics.lead_pipeline_rotting $ARGUMENTS
   ```
2. Show the user the text summary and the HTML report path.
3. If rotting count is high, surface the worst lead (most days since activity) as the most urgent action.
4. Threshold can be changed permanently in `config/hubspot_pipeline.yaml` → `rotting.lead_no_activity_days`.

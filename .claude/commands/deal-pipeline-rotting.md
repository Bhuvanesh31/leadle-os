# /deal-pipeline-rotting

Flag active deals in Leadle's Sales Pipeline that have gone cold.

A deal is rotting if there has been no human activity (no call logged, no email sent) for
more than 4 days. The threshold is set in `config/hubspot_pipeline.yaml` under
`rotting.deal_no_activity_days`. Won and Lost deals are excluded.

The report also flags deals where the expected close date has already passed.

## Usage

```
/deal-pipeline-rotting                     # use config threshold (4 days)
/deal-pipeline-rotting --threshold 7       # override to 7 days
/deal-pipeline-rotting --out /tmp/r.html   # custom output path
```

## Steps

1. Run the script:
   ```bash
   cd /home/bhuvanesh/AI_Native_Workspace/30-leadle-systems/leadle_gtm_intelligence
   python -m analytics.deal_pipeline_rotting $ARGUMENTS
   ```
2. Show the user the text summary and the HTML report path.
3. If the threshold needs changing, edit `config/hubspot_pipeline.yaml`
   under `rotting.deal_no_activity_days` — no code change needed.

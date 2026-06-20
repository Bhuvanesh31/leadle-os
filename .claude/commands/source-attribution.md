# /source-attribution

Find leads in HubSpot where lead_source_v2 is missing, empty, or an unrecognized
custom value. Source gaps silently exclude leads from both inbound and outbound scoring.

Checks ALL leads (active + archived). Recommends which source values to add to
config/inbound_scoring.yaml or config/outbound_scoring.yaml.

Read-only: no HubSpot writes. Fixing empty-source leads requires manual update in HubSpot.

## Usage

```
/source-attribution
/source-attribution --out /tmp/source_gaps.html
```

## Steps

### Step 1 — Run the script

```bash
cd /home/bhuvanesh/AI_Native_Workspace/30-leadle-systems/leadle_gtm_intelligence
set -a && source .env && set +a
python -m analytics.source_attribution $ARGUMENTS --json /tmp/source_gaps.json
```

### Step 2 — Read the JSON

Read `/tmp/source_gaps.json`. Key sections:
- `by_classification`: counts of known_inbound, known_outbound, unattributed, unrecognized
- `unrecognized_sources`: list of unknown source values with counts
- `gap_leads`: each gap lead with is_active flag (active gaps affect current scoring)
- `config_recommendation`: which values to add to which config

### Step 3 — Report findings

Summarize:
1. How many leads are affected (active vs archived/converted)
2. What the unrecognized source values are and what they likely mean
3. Config changes needed (if any) — edit inbound_scoring.yaml or outbound_scoring.yaml
4. Which leads need manual source tagging in HubSpot (must be done by a human)

If there are no active gaps, note that and confirm the config is current.

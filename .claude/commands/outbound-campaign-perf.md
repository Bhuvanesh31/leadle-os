# /outbound-campaign-perf

Pulls live campaign performance metrics from Aimfox (LinkedIn) and Instantly (email).

Covers:
- **LinkedIn campaigns** (Aimfox): sends, replies, reply rate per campaign
- **Email campaigns** (Instantly): sends, opens, open rate, clicks, replies, reply rate

Degrades cleanly if a source is unavailable — shows "unavailable" badge in HTML
rather than crashing. Missing keys or API errors are reported in the JSON source block.

Required env vars (set in .env):
- `AIMFOX_API_KEY` — LinkedIn campaigns via Aimfox REST
- `INSTANTLY_API_KEY` — email campaigns via Instantly REST

## Usage

```
/outbound-campaign-perf
/outbound-campaign-perf --period last-month
/outbound-campaign-perf --start 2026-06-01 --end 2026-06-21
```

## Steps

### Step 1 — Run the script

```bash
cd /home/bhuvanesh/AI_Native_Workspace/30-leadle-systems/leadle_gtm_intelligence
set -a && source .env && set +a
python -m analytics.outbound_campaign_perf $ARGUMENTS --json /tmp/outbound_perf.json
```

### Step 2 — Read the JSON

Read `/tmp/outbound_perf.json`. Key sections:
- `sources.aimfox.available` / `sources.instantly.available`: true if data loaded
- `totals.linkedin`: aggregate sends + replies for the window
- `totals.email`: aggregate sends + opened + bounced + replies
- `linkedin_campaigns`: per-campaign sorted by reply rate desc
- `email_campaigns`: per-campaign sorted by reply rate desc

### Step 3 — Write the narrative

3–5 paragraphs in Leadle voice (conversational, short sentences, no AI phrases, no em dashes):
1. Window and what's available (note any degraded sources upfront)
2. LinkedIn performance: top campaigns, reply rate vs. typical B2B benchmark (2–5% good, under 2% concerning)
3. Email performance: open rate (20%+ good, 15–20% okay, under 15% inbox placement issue) and reply rate
4. Cross-channel comparison: which channel is performing better this window
5. What to investigate next (e.g., if reply rates are low: check sequence step performance, message variants, audience fit)

### Step 4 — Show results

Output the narrative, then HTML report path.

# /outbound-lead-scoring

Score and rank Leadle's active outbound leads by ICP fit (0–100).

"Outbound" = leads sourced via LinkedIn Outbound or Email Outbound campaigns.
Inbound leads are scored separately via /inbound-lead-scoring.

Scoring dimensions (same model as inbound):
- Decision Maker fit (40) — contact title × company size
- Revenue (25) — company annual revenue vs $2M threshold
- Funding (20) — total funding raised vs $2M threshold
- Spend capacity (15) — derived composite

Tiers: Hot (≥65), Warm (35–64), Cold (<35).

All weights in `config/outbound_scoring.yaml` — no code change needed to tune.

## Usage

```
/outbound-lead-scoring                      # outbound leads only (default)
/outbound-lead-scoring --no-enrich          # skip web lookup, HubSpot data only
/outbound-lead-scoring --out /tmp/r.html
```

## Steps

### Step 1 — Dump companies needing enrichment

```bash
cd /home/bhuvanesh/AI_Native_Workspace/30-leadle-systems/leadle_gtm_intelligence
set -a && source .env && set +a
python -m analytics.outbound_lead_scoring $ARGUMENTS --dump-needs-enrichment /tmp/outbound_needs_enrichment.json
```

Read `/tmp/outbound_needs_enrichment.json`. If empty (`[]`) or `--no-enrich` was passed, skip to Step 3.

### Step 2 — Web lookup via Exa

For each company in the needs file, search using `mcp__claude_ai_Exa__web_search_exa`:
- `"{company_name}" annual revenue`
- `"{company_name}" total funding raised`

Extract:
- `annual_revenue_usd` — number in USD (null if not found)
- `total_funding_usd` — number in USD (null if not found)
- `funding_stage` — Pre-Seed, Seed, Series A, Series B, Series C, IPO, Public, Bootstrapped (null if not found)

Write to `/tmp/outbound_enrichment_data.json` keyed by company name.

### Step 3 — Score

```bash
cd /home/bhuvanesh/AI_Native_Workspace/30-leadle-systems/leadle_gtm_intelligence
set -a && source .env && set +a
python -m analytics.outbound_lead_scoring $ARGUMENTS --enrich-from /tmp/outbound_enrichment_data.json
```

(If `--no-enrich` was passed, run without `--enrich-from`.)

### Step 4 — Show results

Show the text summary (total, Hot/Warm/Cold, top lead with breakdown) and HTML report path.
If data gaps are still present, suggest enriching via Clay or HubSpot Breeze.

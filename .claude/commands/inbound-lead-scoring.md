# /inbound-lead-scoring

Score and rank Leadle's active inbound leads by ICP fit (0–100).

"Inbound" = lead came via Web Form, organic, referral, or direct (not LinkedIn Outbound).
Scoring dimensions: Decision Maker fit (40) + Revenue (25) + Funding (20) + Spend capacity (15).
Tiers: Hot (≥65), Warm (35–64), Cold (<35).

All weights are in `config/inbound_scoring.yaml` — no code change needed to tune.

## Usage

```
/inbound-lead-scoring                       # inbound leads only (default)
/inbound-lead-scoring --all-sources         # all leads regardless of source
/inbound-lead-scoring --no-enrich           # skip web lookup, use HubSpot data only
/inbound-lead-scoring --out /tmp/scored.html
```

## Steps

### Step 1 — Dump companies needing enrichment

```bash
cd /home/bhuvanesh/AI_Native_Workspace/30-leadle-systems/leadle_gtm_intelligence
python -m analytics.inbound_lead_scoring $ARGUMENTS --dump-needs-enrichment /tmp/inbound_needs_enrichment.json
```

Read `/tmp/inbound_needs_enrichment.json`. It contains a list of `{lead_id, company_name}` objects
for inbound leads that have no revenue or funding data in HubSpot.

If the file is empty (`[]`) or `--no-enrich` was passed, skip to Step 3.

### Step 2 — Web lookup via Exa (for each company in the needs file)

For each company in the list, search the web using the `mcp__claude_ai_Exa__web_search_exa` tool.

Run two searches per company:
- `"{company_name}" annual revenue`
- `"{company_name}" total funding raised`

Extract:
- `annual_revenue_usd` — convert text amounts to numbers ($5M → 5000000, $1.2B → 1200000000). null if not found.
- `total_funding_usd` — same conversion. null if not found.
- `funding_stage` — one of: Pre-Seed, Seed, Series A, Series B, Series C, Series D, IPO, Public, Bootstrapped. null if not found.

Build a JSON object keyed by company name:
```json
{
  "Navaan": {"annual_revenue_usd": null, "total_funding_usd": 5000000, "funding_stage": "Series A"},
  "Fincent": {"annual_revenue_usd": 8000000, "total_funding_usd": 25000000, "funding_stage": "Series B"}
}
```

Write that to `/tmp/inbound_enrichment_data.json`.

### Step 3 — Score with enriched data

```bash
cd /home/bhuvanesh/AI_Native_Workspace/30-leadle-systems/leadle_gtm_intelligence
python -m analytics.inbound_lead_scoring $ARGUMENTS --enrich-from /tmp/inbound_enrichment_data.json
```

(If `--no-enrich` was passed, run without `--enrich-from`.)

### Step 4 — Show results

Show the user:
- Text summary (total, Hot/Warm/Cold counts, top lead with score breakdown)
- HTML report path
- If data gaps are still present, suggest enriching via Clay or HubSpot Breeze

If source filter or thresholds need tuning, edit `config/inbound_scoring.yaml`.

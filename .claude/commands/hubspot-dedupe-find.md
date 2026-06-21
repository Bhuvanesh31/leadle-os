# /hubspot-dedupe-find

Scans all HubSpot contacts and companies for duplicate records.
Read-only — finds only. Use /hubspot-dedupe-fix (process #15) to merge.

Four duplicate signals (deterministic, no fuzzy matching):
- **Contact email dupes**: same email on multiple contact records
- **Contact name dupes**: same first+last name with different emails
- **Company domain dupes**: same website domain on multiple company records
- **Company name dupes**: identical company name on multiple records

Last run (2026-06-21): 0 email dup groups, 331 contact name groups,
115 company domain groups (249 records), 120 company name groups.

## Usage

```
/hubspot-dedupe-find
/hubspot-dedupe-find --out /tmp/dedupe.html
```

## Steps

### Step 1 — Run the script

```bash
cd /home/bhuvanesh/AI_Native_Workspace/30-leadle-systems/leadle_gtm_intelligence
set -a && source .env && set +a
python -m analytics.hubspot_dedupe_find --json /tmp/dedupe.json
```

Note: scans ~9K contacts + ~6K companies. Expect 60–120 seconds.

### Step 2 — Read the JSON

Read `/tmp/dedupe.json`. Key sections:
- `summary`: group counts and records-affected for each signal type
- `contact_email_dupes`: groups sorted by record count (most severe first)
- `contact_name_dupes`: same-name groups across different email addresses
- `company_domain_dupes`: domain-based company duplicates (most actionable)
- `company_name_dupes`: identical company name duplicates

### Step 3 — Write the narrative

3–4 paragraphs in Leadle voice:
1. Overall health: is the CRM clean or noisy? Frame contacts vs. companies separately
2. Company domain dupes: these are the most actionable — same domain = almost certainly the same company. Top offenders by record count
3. Contact name dupes: more nuanced — could be two people with the same name. Flag groups where company also matches
4. What's genuinely low priority (e.g., 2-record groups at small companies vs. 4-record groups at Leadle's own prospects)
5. Recommended next step: /hubspot-dedupe-fix with the top N domain groups

### Step 4 — Show results

Output the narrative, then HTML report path.

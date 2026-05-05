# Data shape observations

Per the *explore-first schema* principle, every new data source we ingest must produce a markdown observation document **before** typed staging or unified schemas are designed for it.

## Convention

One file per source: `<source>.md` (e.g., `hubspot.md`, `lemlist.md`).

Each file should answer:

1. **What objects does the source expose?** Top-level entities, their identifiers, their cardinality.
2. **What fields are populated in our actual data?** Don't trust the API docs — pull a sample, see what's there. Note `null` patterns.
3. **What's the relationship structure?** What joins what, how, with what foreign-key shape.
4. **What's noisy vs. valuable?** Which fields are meaningful for our use cases (Phantom Detection, Outreach Health, etc.) and which are decoration.
5. **What's missing or surprising?** Things you expected to be there but aren't, or vice versa.
6. **Identity-relevant fields:** especially the Clay-injected `hubspot_company_id` and `hubspot_contact_id` custom fields when applicable.
7. **Estimated volume:** rows/day, rows/month at Leadle's current scale.
8. **Schema commitment recommendations:** what to model in `stg_<source>_*` and `unified_*` based on what you actually saw.

## Why this matters

Designing typed schemas before observation produces tables you have to throw away. The observation step takes hours; redoing schemas takes weeks.

## Status

| Source | Status |
|---|---|
| HubSpot | not yet observed (P1) |
| Lemlist | not yet observed (P3) |
| Instantly | not yet observed (P4) |
| Aimfox | not yet observed (P5) |
| Fathom | not yet observed (P6) |

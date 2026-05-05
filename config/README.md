# Operational configuration (YAML)

Operational rules — what shows up in the brief, which signals to detect, where the ICP boundaries are, what counts as a phantom deal — live here as YAML, not in code.

## Files (planned, added per phase)

| File | Phase added | Controls |
|---|---|---|
| `brief_sections.yaml` | P1 | Sections in Sai's daily brief, their order, their producer functions |
| `signals.yaml` | P5 | Signal Detector triggers — keywords, ICP filters per offer, time windows |
| `phantom_rules.yaml` | P1 | Phantom Detector thresholds — revenue band per offer, days-stuck cutoffs, evaluator-keyword list |
| `icp_per_offer.yaml` | P1 | ICP definitions per offer (Founder on Call / Outbound OS / RevOps as a Service); mirrors Pipeline Action Plan §04 |
| `dashboard_layout.yaml` | P7 | Dashboard sections per tab, ordering, freshness banner thresholds |
| `voice.yaml` | P1 | Voice and tone references for the brief composer |

## Editing rules

- These files **are** the operational behavior. Editing one and rerunning the relevant agent should produce different output without code changes.
- The corresponding `config_*` Supabase tables mirror these files; they are loaded at run start. YAML is the source of truth.
- Changes are reviewable in git diffs. Don't tune values in the database directly.

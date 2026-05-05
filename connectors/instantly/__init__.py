"""Instantly ingestion (REST API; script).

Lands raw payloads into raw_instantly. Surfaces inbox-placement signal —
the unique value-add this source provides over other email tools. That
metric is load-bearing for the Outreach Health Monitor's TOFU lens.

Schema design happens in P4 after observation in docs/data-shape/instantly.md.
"""

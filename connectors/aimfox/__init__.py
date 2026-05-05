"""Aimfox ingestion (REST API + webhooks; script).

Lands raw payloads into raw_aimfox. Builds on the existing Clay→HubSpot sync
pipeline that already uses Aimfox webhooks (waterfall match: company ID →
LinkedIn slug → email domain → CREATE).

Schema design happens in P5 after observation in docs/data-shape/aimfox.md.
"""

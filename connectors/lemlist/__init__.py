"""Lemlist ingestion (REST API; script).

Lands raw payloads into raw_lemlist. Includes Clay-injected hubspot_company_id
and hubspot_contact_id custom fields — preserved as-is into JSONB; the
identity resolver reads them downstream.

Schema design happens in P3 after observation in docs/data-shape/lemlist.md.
"""

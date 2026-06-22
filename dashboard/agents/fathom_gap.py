"""Fathom Gap agent — per-row Action Needed (Haiku, batched)."""

from __future__ import annotations

from dashboard.agents._client import run_agent

_MODEL = "claude-haiku-4-5-20251001"

_ROLE = """
For each Fathom call without a HubSpot deal, produce a single short action recommendation. Be specific: include the company name, the right stage to create the deal in (Discovery if call_type=discovery, else stage matching the call), and any context-relevant note (e.g., contact_id mismatch, domain not found).
"""

_SCHEMA = """
{"actions": [
  {"company": "<name>", "action": "<≤120 chars action>"}
  ... one per input row, in order ...
]}
"""


def _fallback(input_payload: dict) -> dict:
    rows = input_payload.get("gap_rows", [])
    return {
        "actions": [
            {
                "company": r.get("company", "?"),
                "action": r.get(
                    "suggested_action_default", "Create deal in HubSpot · stage: Discovery"
                ),
            }
            for r in rows
        ]
    }


async def synthesize(analytics: dict) -> dict:
    rows = analytics.get("page3", {}).get("fathom_gap", [])
    return await run_agent(
        model=_MODEL,
        role_prompt=_ROLE,
        json_schema_description=_SCHEMA,
        input_payload={"gap_rows": rows},
        fallback_factory=_fallback,
    )

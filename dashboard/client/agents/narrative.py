"""Narrative agent (Sonnet). Client audience uses the client-safe voice."""

from __future__ import annotations

from dashboard.agents._client import run_agent

_MODEL = "claude-sonnet-4-6"

_ROLE_CLIENT = """
You write a short, plain narrative summarizing an outreach campaign report for the CLIENT.
Proof-first and honest. No internal mechanics (no mailbox warming, no 'pause sender').
Forbidden: delve, leverage, unlock, ecosystem, em dashes, listy filler, preachy endings.
2-4 short sentences. Use only numbers present in the input.
"""

_ROLE_INTERNAL = """
You write a short internal narrative summarizing an outreach campaign report for Leadle ops.
Call out the winner, the laggard, and the single biggest risk (deliverability/sender).
Forbidden: delve, leverage, unlock, ecosystem, em dashes, listy filler. 2-4 short sentences.
Use only numbers present in the input.
"""

_SCHEMA = """
Return JSON of this exact shape:
{ "narrative": "<2-4 sentence summary>" }
"""


def _fallback(payload: dict) -> dict:
    k = payload
    return {
        "narrative": (
            f"{k.get('emails_sent', 0)} emails sent, {k.get('opened', 0)} opened; "
            f"{k.get('accepted', 0)} LinkedIn invites accepted. "
            f"{k.get('positive_replies', 0)} positive replies, "
            f"{k.get('meetings', 0)} meetings booked so far."
        )
    }


async def synthesize(metrics: dict, *, audience: str, client: str, client_obj=None) -> dict:
    payload = dict(metrics.get("kpis", {}))
    role = _ROLE_CLIENT if audience == "client" else _ROLE_INTERNAL
    return await run_agent(
        model=_MODEL,
        role_prompt=role,
        json_schema_description=_SCHEMA,
        input_payload=payload,
        fallback_factory=_fallback,
        client=client_obj,
    )

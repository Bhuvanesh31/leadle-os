"""Actions agent (Sonnet). Internal audience only — never rendered for clients."""

from __future__ import annotations

from dashboard.agents._client import run_agent

_MODEL = "claude-sonnet-4-6"

_ROLE = """
You propose up to 4 concrete operator actions for this outreach campaign for the next period
(scale a winner, swap a weak subject, pause/warm a bouncing inbox, follow up positives).
Each under 90 characters. Use only numbers present in the input.
"""

_SCHEMA = """
Return JSON of this exact shape:
{ "actions": ["<action>", "... up to 4 ..."] }
"""


def _make_fallback(bounce_threshold: float):
    """Build the degraded-path fallback; bounce threshold is sourced from the rubric."""

    def _fallback(payload: dict) -> dict:
        acts = []
        if payload.get("bounce_rate", 0) >= bounce_threshold:
            acts.append("Pause & warm the bouncing inbox before next send.")
        acts.append("Follow up every positive reply within 24h.")
        return {"actions": acts}

    return _fallback


async def synthesize(metrics: dict, *, client: str, rubric: dict, client_obj=None) -> dict:
    payload = dict(metrics.get("kpis", {}))
    return await run_agent(
        model=_MODEL,
        role_prompt=_ROLE,
        json_schema_description=_SCHEMA,
        input_payload=payload,
        fallback_factory=_make_fallback(rubric["bounce_flag_threshold"]),
        client=client_obj,
    )

"""Funnel Leak agent — interprets Page 1 §06 conversions (Sonnet)."""
from __future__ import annotations

from dashboard.agents._client import run_agent

_MODEL = "claude-sonnet-4-6"

_ROLE = """
You identify the largest leak in the sales funnel and explain its likely cause in one short paragraph.

Pick the single stage transition with the lowest conversion rate (or smallest absolute count drop, whichever is more meaningful). Headline names the leak. Explanation is one short sentence (<200 chars) about why this stage might be the bottleneck. Don't speculate beyond what the numbers support.
"""

_SCHEMA = """
{"headline": "<one line, e.g. 'Discovery → Proposal at 12%'>",
 "explanation": "<≤200 chars>",
 "leaking_stage": "<from_stage>",
 "conversion_pct": <float>}
"""


def _fallback(input_payload: dict) -> dict:
    convs = input_payload.get("conversions", [])
    if not convs:
        return {
            "headline": "—",
            "explanation": "Insufficient data.",
            "leaking_stage": "",
            "conversion_pct": 0.0,
        }
    worst = min(
        (c for c in convs if c.get("conversion_pct") is not None),
        key=lambda c: c["conversion_pct"],
        default=None,
    )
    if not worst:
        return {
            "headline": "—",
            "explanation": "No conversions computed.",
            "leaking_stage": "",
            "conversion_pct": 0.0,
        }
    return {
        "headline": f"{worst['from_stage']} → {worst['to_stage']} at {worst['conversion_pct']:.1f}%",
        "explanation": "Lowest conversion rate in the funnel.",
        "leaking_stage": worst["from_stage"],
        "conversion_pct": worst["conversion_pct"],
    }


async def synthesize(analytics: dict) -> dict:
    p = analytics.get("page1", {}).get("funnel", {})
    payload = {
        "stage_counts": p.get("stage_counts", {}),
        "conversions": p.get("conversions", []),
    }
    return await run_agent(
        model=_MODEL,
        role_prompt=_ROLE,
        json_schema_description=_SCHEMA,
        input_payload=payload,
        fallback_factory=_fallback,
    )

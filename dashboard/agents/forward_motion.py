"""Forward Motion agent — synthesizes Page 1 §09 commitments (Sonnet)."""
from __future__ import annotations

from dashboard.agents._client import run_agent

_MODEL = "claude-sonnet-4-6"

_ROLE = """
You synthesize 5 weekly revenue commitments for Leadle's RevOps team based on the dashboard's analytics output.

Pick the 5 highest-impact actions. Assign each to one of: Sai (Sales Head), Bhuvanesh (RevOps), Akil (Head of RevOps), Founders. Phrase each commitment with specific deal names, dollar amounts, day counts where relevant. Keep each under 200 characters.
"""

_SCHEMA = """
Return JSON of this exact shape:
{
  "commitments": [
    {"owner": "Sai|Bhuvanesh|Akil|Founders", "text": "<action with specifics>"},
    ... exactly 5 items ...
  ]
}
"""


def _fallback(input_payload: dict) -> dict:
    deals = input_payload.get("rotting_deals", [])[:5]
    return {
        "commitments": [
            {
                "owner": "Sai",
                "text": f"Review {d.get('name')} (stale {d.get('days_stale')}d, ${d.get('amount')})",
            }
            for d in deals
        ]
        or [{"owner": "Sai", "text": "No rule-flagged actions in window."}]
    }


async def synthesize(analytics: dict) -> dict:
    p1 = analytics.get("page1", {})
    p2 = analytics.get("page2", {})
    p4 = analytics.get("page4", {})
    payload = {
        "rotting_deals": p1.get("forward_motion_input", {}).get("rotting_deals", [])[:10],
        "pipeline_at_risk": p1.get("forward_motion_input", {})
        .get("rotting_pipeline_at_risk", 0),
        "stalled_leads_count": p2.get("kpi", {}).get("stalled_count", 0),
        "monthly_target": p1.get("monthly_control", {}).get("monthly_target", 0),
        "monthly_gap": p1.get("monthly_control", {}).get("monthly_gap", 0),
        "pipeline_coverage_ratio": p1.get("monthly_control", {})
        .get("pipeline_coverage_ratio", 0),
        "hygiene_issues_count": p1.get("hygiene", {}).get("total_issues", 0),
        "followup_gap_count": len(p4.get("followup_gap", [])),
    }
    return await run_agent(
        model=_MODEL,
        role_prompt=_ROLE,
        json_schema_description=_SCHEMA,
        input_payload=payload,
        fallback_factory=_fallback,
    )

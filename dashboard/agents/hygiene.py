"""Hygiene agent — categorizes Page 1 §08 issues by impact (Sonnet)."""

from __future__ import annotations

from dashboard.agents._client import run_agent

_MODEL = "claude-sonnet-4-6"

_ROLE = """
You categorize hygiene issues by business impact. Group similar issues. Mark severity: blocking (blocks monthly close), important (affects reporting), cosmetic (nice-to-fix).

Output 3–6 categories. Each has a title, a one-sentence summary, count, severity, and a one-sentence "fix" hint (specific, not generic).
"""

_SCHEMA = """
{"categories": [
  {"title": "<short>", "summary": "<≤150 chars>", "count": <int>,
   "severity": "blocking|important|cosmetic", "fix": "<≤150 chars>"}
]}
"""


def _fallback(input_payload: dict) -> dict:
    return {
        "categories": [
            {
                "title": "Hygiene issues",
                "summary": f"Total {input_payload.get('total_issues', 0)} issues across deals and contacts.",
                "count": input_payload.get("total_issues", 0),
                "severity": "important",
                "fix": "Review issues list manually.",
            }
        ]
    }


async def synthesize(analytics: dict) -> dict:
    payload = analytics.get("page1", {}).get("hygiene", {})
    return await run_agent(
        model=_MODEL,
        role_prompt=_ROLE,
        json_schema_description=_SCHEMA,
        input_payload=payload,
        fallback_factory=_fallback,
    )

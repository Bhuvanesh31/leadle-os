"""Page 4 — Outreach. Campaign metrics + follow-up gap."""
from __future__ import annotations

from datetime import date
from typing import Any

from dashboard.compute.page1_revenue import _parse_iso_date
from dashboard.compute.windows import WindowSpec


def compute(raw: dict, rules: dict, window: WindowSpec,
            today: date | None = None) -> dict[str, Any]:
    today = today or date.today()
    return {
        "lemlist": _campaigns(raw, "lemlist", rules),
        "aimfox": _campaigns(raw, "aimfox", rules),
        "instantly": _campaigns(raw, "instantly", rules),
        "followup_gap": _followup_gap(raw, rules, today),
    }


def _campaigns(raw: dict, source: str, rules: dict) -> list[dict]:
    src = raw["sources"].get(source, {})
    if not src.get("available"):
        return []
    out = []
    for c in src["data"].get("campaigns", []):
        stats = c.get("stats", {})
        sends = stats.get("sends", 0)
        if sends < rules["outreach_min_sends"]:
            continue
        replies = stats.get("replies", 0)
        meetings = stats.get("meetings", 0)
        out.append({
            "id": c.get("id"),
            "name": c.get("name"),
            "sends": sends,
            "replies": replies,
            "reply_rate_pct": (replies / sends * 100) if sends > 0 else 0,
            "meetings": meetings,
            "meeting_rate_pct": (meetings / sends * 100) if sends > 0 else 0,
        })
    return sorted(out, key=lambda x: x["reply_rate_pct"], reverse=True)


def _followup_gap(raw: dict, rules: dict, today: date) -> list[dict]:
    hubspot = raw["sources"].get("hubspot", {})
    if not hubspot.get("available"):
        return []
    out = []
    for c in hubspot["data"].get("contacts", []):
        if c.get("lifecyclestage") != "lead":
            continue
        la = _parse_iso_date(c.get("last_activity_date"))
        if not la:
            continue
        days = (today - la).days
        if days > rules["followup_gap_days"]:
            out.append({
                "id": c.get("id"),
                "email": c.get("email"),
                "last_activity": c.get("last_activity_date"),
                "days_since_activity": days,
            })
    return sorted(out, key=lambda x: x["days_since_activity"], reverse=True)

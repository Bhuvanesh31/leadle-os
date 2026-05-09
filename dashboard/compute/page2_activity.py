"""Page 2 — Activity & Rot. Point-in-time current state. Not window-aware."""
from __future__ import annotations

from datetime import date
from typing import Any

from dashboard.compute.page1_revenue import _parse_iso_date


def compute(raw: dict, rules: dict, today: date | None = None) -> dict[str, Any]:
    today = today or date.today()
    hubspot = raw["sources"].get("hubspot", {})
    if not hubspot.get("available"):
        return {"unavailable": True}

    deals = hubspot["data"].get("deals", [])
    contacts = hubspot["data"].get("contacts", [])

    rotting = _rotting_deals(deals, rules, today)
    stalled = _stalled_leads(contacts, raw, rules, today)
    return {
        "rotting_deals": rotting,
        "pipeline_at_risk": sum(d["amount"] or 0 for d in rotting),
        "stalled_leads": stalled,
        "kpi": {
            "rotting_count": len(rotting),
            "stalled_count": len(stalled),
            "stalled_30d_plus": sum(1 for s in stalled if (s.get("days_stalled") or 0) >= 30),
            "most_critical_deal": rotting[0] if rotting else None,
        },
    }


def _rotting_deals(deals: list[dict], rules: dict, today: date) -> list[dict]:
    out = []
    for d in deals:
        if d.get("dealstage") in ("closedwon", "closedlost"):
            continue
        la = _parse_iso_date(d.get("last_activity_date"))
        if not la:
            continue
        days_stale = (today - la).days
        if days_stale > rules["rotting_deal_days"]:
            out.append({
                "id": d.get("id"), "name": d.get("dealname"),
                "amount": d.get("amount"), "stage": d.get("dealstage"),
                "last_activity": d.get("last_activity_date"),
                "days_stale": days_stale,
            })
    return sorted(out, key=lambda x: x["days_stale"], reverse=True)


def _stalled_leads(contacts: list[dict], raw: dict, rules: dict, today: date) -> list[dict]:
    """Cross-tool join: outreach replies + HubSpot lifecycle != Meeting Booked."""
    replied_contact_ids = set()
    for source in ("lemlist", "aimfox", "instantly"):
        src = raw["sources"].get(source, {})
        if not src.get("available"):
            continue
        for lead in src["data"].get("leads", []):
            if lead.get("reply_status") in ("positive", "neutral", "replied"):
                if hcid := lead.get("hubspot_contact_id"):
                    replied_contact_ids.add(hcid)
    out = []
    for c in contacts:
        if c["id"] not in replied_contact_ids:
            continue
        if c.get("lifecyclestage") in ("opportunity", "customer", "salesqualifiedlead"):
            continue  # already advanced to meeting/opportunity
        la = _parse_iso_date(c.get("last_activity_date"))
        if not la:
            continue
        days = (today - la).days
        if days > rules["stalled_lead_days"]:
            out.append({"id": c["id"], "email": c.get("email"),
                        "lifecycle": c.get("lifecyclestage"),
                        "last_activity": c.get("last_activity_date"),
                        "days_stalled": days})
    return sorted(out, key=lambda x: x["days_stalled"], reverse=True)

"""Page 3 — Sales Actions. Fathom Gap detection (SOP is static template-only)."""
from __future__ import annotations

from datetime import date
from typing import Any

from dashboard.compute.page1_revenue import _parse_iso_date
from dashboard.compute.windows import WindowSpec


def compute(raw: dict, rules: dict, window: WindowSpec) -> dict[str, Any]:
    fathom = raw["sources"].get("fathom", {})
    hubspot = raw["sources"].get("hubspot", {})
    if not fathom.get("available") or not hubspot.get("available"):
        return {"fathom_gap": [], "unavailable": True}

    meetings = fathom["data"].get("meetings", [])
    deals = hubspot["data"].get("deals", [])
    companies = hubspot["data"].get("companies", [])
    domain_to_company = {c["domain"].lower(): c for c in companies if c.get("domain")}
    company_id_to_deals = {}
    for d in deals:
        cid = d.get("company_id")
        if cid:
            company_id_to_deals.setdefault(cid, []).append(d)

    gap = []
    for m in meetings:
        scheduled = _parse_iso_date(m.get("scheduled_at"))
        if not scheduled or not (window.start <= scheduled <= window.end):
            continue
        attendee_emails = [a.get("email", "") for a in m.get("attendees", [])]
        external = [e for e in attendee_emails
                    if e and not e.endswith("@leadle.in")]
        if not external:
            continue
        domain = external[0].split("@")[-1].lower() if "@" in external[0] else ""
        company = domain_to_company.get(domain)
        if company:
            cid = company["id"]
            if cid in company_id_to_deals:
                continue  # has a deal, not a gap
        gap.append({
            "company": company["name"] if company else _company_from_email(external[0]),
            "contact_email": external[0],
            "last_call_date": scheduled.isoformat(),
            "call_type": m.get("call_type", "unknown"),
            "crm_state": "no deal" if not company else "company exists, no deal",
            "suggested_action_default": "Create deal in HubSpot · stage: Discovery",
        })
    return {"fathom_gap": gap, "gap_count": len(gap)}


def _company_from_email(email: str) -> str:
    if "@" not in email:
        return "Unknown"
    domain = email.split("@")[1]
    root = domain.split(".")[0]
    return root.capitalize()

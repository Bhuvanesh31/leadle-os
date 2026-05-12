"""Page 2 — Activity & Rot. Point-in-time current state. Not window-aware."""
from __future__ import annotations

import re
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
    leads = hubspot["data"].get("leads", [])

    rotting = _rotting_deals(deals, rules, today)
    stalled = _stalled_leads(contacts, raw, rules, today)
    funnel = _lead_funnel(leads, raw, rules, today)
    return {
        "rotting_deals": rotting,
        "pipeline_at_risk": sum(d["amount"] or 0 for d in rotting),
        "stalled_leads": stalled,
        "lead_funnel": funnel,
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


# All of these are sourced from config/dashboard_rules.yaml at compute time —
# the module-level defaults below only kick in when rules doesn't carry the
# key (which happens in tests that pass a minimal rules dict).
_LEADLE_INTERNAL_NAMES_DEFAULT = {
    "sai ganesh subramanian", "sai ganesh", "revops leadle",
    "akil mohan", "suraj seetharaman", "bhuvaneswari",
}
_CLOSED_LEAD_STAGES_DEFAULT = {"qualified-stage-id", "unqualified-stage-id"}
_MEETING_PROPOSED_STAGE_DEFAULT = "3200435923"


def _config_internal_names(rules: dict) -> set[str]:
    names = rules.get("leadle_internal_names") or []
    return {n.lower() for n in names} if names else _LEADLE_INTERNAL_NAMES_DEFAULT


def _config_closed_stages(rules: dict) -> set[str]:
    lp = rules.get("lead_pipeline") or {}
    stages = lp.get("closed_stage_ids") or []
    return set(stages) if stages else _CLOSED_LEAD_STAGES_DEFAULT


def _config_meeting_proposed_stage(rules: dict) -> str:
    lp = rules.get("lead_pipeline") or {}
    return lp.get("meeting_proposed_stage_id") or _MEETING_PROPOSED_STAGE_DEFAULT


def _lead_funnel(leads: list[dict], raw: dict, rules: dict, today: date) -> dict[str, Any]:
    """Classify OPEN Leads into 5 funnel buckets using the user's cascade.

    Pre-filter: Leads in closed stages (Advance to Deal / Lead Archived) are
    out of scope — those have left the Lead pipeline and are tracked elsewhere
    (Advance to Deal records show up in Deal-pipeline reporting; Archived are
    dead). The funnel only describes leads still being actively worked.

    Buckets (top-down precedence):
      1. call_completed         — Fathom meeting recorded for this lead
      2. meeting_booked_no_call — Lead at "Meeting Proposed" stage but no
                                  Fathom meeting yet
      3. responded_no_meeting   — They replied AND we responded back, no
                                  meeting booked yet
      4. replied_awaiting_us    — They replied but we haven't responded
      5. no_reply               — No outreach reply found in any platform

    Plus lead_rotting: subset of no_reply where createdate is >5d ago.
    """
    closed_stages = _config_closed_stages(rules)
    internal_names = _config_internal_names(rules)
    meeting_proposed_stage = _config_meeting_proposed_stage(rules)
    leads = [
        l for l in leads
        if l.get("pipeline_stage_id") not in closed_stages
        and _has_contact_identity(l)
    ]
    # Build reply index keyed by lowercased email AND lowercased name (for
    # Aimfox name-only matching).
    replies_by_email: dict[str, dict] = {}
    replies_by_name: dict[str, dict] = {}

    for src in ("lemlist", "aimfox", "instantly"):
        s = raw["sources"].get(src, {})
        if not s.get("available"):
            continue
        for r in s["data"].get("leads", []):
            we_responded = _did_we_respond(r, src)
            entry = {
                "source": src,
                "replied_at": r.get("replied_at") or r.get("lastRepliedAt"),
                "channel": r.get("channel"),
                "we_responded": we_responded,
                "is_positive": r.get("is_positive", True),
            }
            email = (r.get("email") or r.get("contactEmail") or "").lower().strip()
            name = (r.get("name") or r.get("contactName") or "").lower().strip()
            if email:
                replies_by_email[email] = entry
            if name and name not in internal_names:
                replies_by_name[name] = entry

    # Build Fathom call index — emails of attendees who aren't Leadle internal.
    fathom_emails: set[str] = set()
    fathom_names: set[str] = set()
    fathom = raw["sources"].get("fathom", {})
    if fathom.get("available"):
        for m in fathom["data"].get("meetings", []):
            for a in m.get("attendees", []):
                email = (a.get("email") or "").lower().strip()
                if email and not email.endswith("@leadle.in"):
                    fathom_emails.add(email)
                name = (a.get("name") or "").lower().strip()
                if name and name not in internal_names:
                    fathom_names.add(name)

    # Classify each lead
    buckets: dict[str, list[dict]] = {
        "call_completed": [],
        "meeting_booked_no_call": [],
        "responded_no_meeting": [],
        "replied_awaiting_us": [],
        "no_reply": [],
    }
    rot_threshold = rules.get("stalled_lead_days", 5)
    rotting: list[dict] = []

    for lead in leads:
        email = (lead.get("contact_email") or "").lower().strip()
        name = (lead.get("contact_name") or "").lower().strip()
        row = _shape_funnel_row(lead)

        # State 1: call already happened?
        if (email and email in fathom_emails) or (name and name in fathom_names):
            buckets["call_completed"].append(row)
            continue

        # State 2: meeting booked (lead is at "Meeting Proposed" stage)?
        # We don't use associated_deal_ids here because an open lead with
        # a deal would have been pre-filtered out (Advance to Deal stage).
        if lead.get("pipeline_stage_id") == meeting_proposed_stage:
            buckets["meeting_booked_no_call"].append(row)
            continue

        # State 3-5: reply state
        reply = (replies_by_email.get(email) if email else None) \
                or (replies_by_name.get(name) if name else None)
        if not reply:
            buckets["no_reply"].append(row)
            cd = _parse_iso_date(lead.get("createdate"))
            if cd and (today - cd).days > rot_threshold:
                rotting.append({**row, "days_since_created": (today - cd).days})
            continue

        if not reply["we_responded"]:
            buckets["replied_awaiting_us"].append({**row, "replied_at": reply["replied_at"],
                                                    "channel": reply["channel"]})
            continue

        # We responded back, no meeting yet
        buckets["responded_no_meeting"].append({**row, "replied_at": reply["replied_at"],
                                                 "channel": reply["channel"]})

    return {
        "totals": {k: len(v) for k, v in buckets.items()},
        "total_leads": len(leads),
        "call_completed": buckets["call_completed"],
        "meeting_booked_no_call": buckets["meeting_booked_no_call"],
        "responded_no_meeting": buckets["responded_no_meeting"],
        "replied_awaiting_us": buckets["replied_awaiting_us"],
        "no_reply": buckets["no_reply"],
        "lead_rotting": sorted(rotting, key=lambda x: -x["days_since_created"]),
        "rotting_count": len(rotting),
    }


_INBOUND_FORM_PREFIX = re.compile(r"^Inbound\s*-\s*Form\s*-\s*", re.IGNORECASE)


def _has_contact_identity(lead: dict) -> bool:
    """Drop ghost leads — inbound form submissions where the contact name
    didn't get captured.

    A 'Inbound - Form -' lead_name with no suffix (i.e., empty after stripping
    the prefix) AND no contact_name means the form fired but didn't carry the
    person's name through. The contact_email may exist (from the form's email
    field) but the lead is functionally an unenriched stub that HubSpot users
    typically exclude from active-pipeline views.
    """
    if (lead.get("contact_name") or "").strip():
        return True
    lead_name = (lead.get("lead_name") or "").strip()
    if not lead_name:
        return False
    suffix = _INBOUND_FORM_PREFIX.sub("", lead_name).strip()
    return bool(suffix)


def _did_we_respond(reply_record: dict, source: str) -> bool:
    """Per-platform signal for whether we've responded to this lead's reply.

    Lemlist: is_your_turn=False means we already replied (we don't owe a turn).
    Aimfox:  unread_count=0 means no unread inbound messages (we read & maybe
             replied — best signal available).
    Instantly: auto-replies don't need a response. For real replies, we don't
             have direct visibility into our sent threads, so assume the
             worst (treat as awaiting our response).
    """
    if source == "lemlist":
        return not reply_record.get("is_your_turn", True)
    if source == "aimfox":
        return reply_record.get("unread_count", 0) == 0
    if source == "instantly":
        return bool(reply_record.get("is_auto_reply"))
    return False


def _shape_funnel_row(lead: dict) -> dict:
    return {
        "id": lead.get("id"),
        "lead_name": lead.get("lead_name"),
        "contact_name": lead.get("contact_name"),
        "contact_email": lead.get("contact_email"),
        "company": lead.get("company_name"),
        "createdate": lead.get("createdate"),
        "last_activity_date": lead.get("last_activity_date"),
        "owner_id": lead.get("hubspot_owner_id"),
    }


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

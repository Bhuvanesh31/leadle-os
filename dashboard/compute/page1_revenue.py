"""Page 1 — Revenue Engine compute.

Section-by-section deterministic analytics. Window-aware where applicable,
point-in-time for hygiene. Output is a dict mapping section keys to computed values.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import Any

from dashboard.compute.windows import WindowSpec


def _parse_iso_date(s: str | None) -> date | None:
    if not s:
        return None
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        return None


def compute(
    raw: dict, rules: dict, targets: dict, window: WindowSpec, today: date | None = None
) -> dict[str, Any]:
    today = today or date.today()
    hubspot = raw["sources"]["hubspot"]
    if not hubspot.get("available"):
        return {"unavailable": True, "reason": hubspot.get("error", "HubSpot unavailable")}

    deals = hubspot["data"].get("deals", [])
    contacts = hubspot["data"].get("contacts", [])
    owners = hubspot["data"].get("owners", [])

    return {
        "goal_snapshot": _goal_snapshot(deals, targets, today),
        "monthly_control": _monthly_control(deals, targets, today),
        "execution": _execution_panel(deals, contacts, raw, window),
        "channel_performance": _channel_performance(deals),
        "channel_economics": _channel_economics(deals),
        "funnel": _funnel(deals, window),
        "accountability": _accountability(deals, owners, window),
        "hygiene": _hygiene(deals, contacts, rules["hygiene"]),
        "forward_motion_input": _forward_motion_input(deals, contacts, rules, window, today),
    }


def _goal_snapshot(deals: list[dict], targets: dict, today: date) -> dict:
    goal = targets["annual"]["goal_amount"]
    target_date = date.fromisoformat(targets["annual"]["target_date"])
    fy_start = date(today.year if today.month >= 4 else today.year - 1, 4, 1)
    ytd_revenue = sum(
        d.get("amount", 0)
        for d in deals
        if d.get("dealstage") == "closedwon"
        and (cd := _parse_iso_date(d.get("closedate")))
        and fy_start <= cd <= today
    )
    pct_of_goal = (ytd_revenue / goal * 100) if goal > 0 else 0
    months_remaining = max(
        1, (target_date.year - today.year) * 12 + (target_date.month - today.month)
    )
    monthly_needed = (goal - ytd_revenue) / months_remaining if months_remaining > 0 else 0
    return {
        "ytd_revenue": ytd_revenue,
        "goal_amount": goal,
        "goal_currency": targets["annual"]["goal_currency"],
        "pct_of_goal": pct_of_goal,
        "revenue_remaining": goal - ytd_revenue,
        "monthly_needed": monthly_needed,
        "run_rate_status": "critical"
        if pct_of_goal < 30
        else "warning"
        if pct_of_goal < 60
        else "on-track",
    }


def _monthly_control(deals: list[dict], targets: dict, today: date) -> dict:
    month_start = date(today.year, today.month, 1)
    monthly_target = targets["monthly"]["target_amount"]
    mtd_revenue = sum(
        d.get("amount", 0)
        for d in deals
        if d.get("dealstage") == "closedwon"
        and (cd := _parse_iso_date(d.get("closedate")))
        and month_start <= cd <= today
    )
    open_pipeline = sum(
        d.get("amount", 0) for d in deals if d.get("dealstage") not in ("closedwon", "closedlost")
    )
    coverage = open_pipeline / monthly_target if monthly_target > 0 else 0
    targets["pipeline_coverage"]["ratio_target"]
    cov_warning = targets["pipeline_coverage"]["ratio_warning_below"]
    cov_critical = targets["pipeline_coverage"]["ratio_critical_below"]
    coverage_status = (
        "critical"
        if coverage < cov_critical
        else "warning"
        if coverage < cov_warning
        else "on-track"
    )
    return {
        "mtd_revenue": mtd_revenue,
        "monthly_target": monthly_target,
        "pct_target_achieved": (mtd_revenue / monthly_target * 100) if monthly_target > 0 else 0,
        "monthly_gap": monthly_target - mtd_revenue,
        "open_pipeline": open_pipeline,
        "pipeline_coverage_ratio": coverage,
        "pipeline_coverage_status": coverage_status,
        "closed_won_count": sum(
            1
            for d in deals
            if d.get("dealstage") == "closedwon"
            and (cd := _parse_iso_date(d.get("closedate")))
            and month_start <= cd <= today
        ),
    }


def _execution_panel(
    deals: list[dict], contacts: list[dict], raw: dict, window: WindowSpec
) -> dict:
    s, e = window.start, window.end
    new_leads = sum(
        1 for c in contacts if (cd := _parse_iso_date(c.get("createdate"))) and s <= cd <= e
    )
    qualified = sum(
        1
        for c in contacts
        if c.get("lifecyclestage") in ("salesqualifiedlead", "marketingqualifiedlead")
        and (cd := _parse_iso_date(c.get("createdate")))
        and s <= cd <= e
    )
    fathom = raw["sources"].get("fathom", {})
    meetings = []
    if fathom.get("available"):
        meetings = [
            m
            for m in fathom["data"].get("meetings", [])
            if (md := _parse_iso_date(m.get("scheduled_at"))) and s <= md <= e
        ]
    opportunities = sum(
        1 for d in deals if (cd := _parse_iso_date(d.get("createdate"))) and s <= cd <= e
    )
    proposals = sum(
        1
        for d in deals
        if d.get("dealstage") == "proposal"
        and (cd := _parse_iso_date(d.get("createdate")))
        and s <= cd <= e
    )
    pipeline_added = sum(
        d.get("amount", 0)
        for d in deals
        if (cd := _parse_iso_date(d.get("createdate"))) and s <= cd <= e
    )
    return {
        "window_label": window.label,
        "new_leads": new_leads,
        "qualified_leads": qualified,
        "qualification_rate": (qualified / new_leads * 100) if new_leads > 0 else 0,
        "meetings_booked": len(meetings),
        "opportunities": opportunities,
        "proposals_sent": proposals,
        "pipeline_added": pipeline_added,
    }


def _channel_performance(deals: list[dict]) -> dict:
    by_channel = defaultdict(lambda: {"deal_count": 0, "pipeline": 0, "closed_won_revenue": 0})
    for d in deals:
        ch = d.get("hs_analytics_source", "UNKNOWN")
        by_channel[ch]["deal_count"] += 1
        if d.get("dealstage") not in ("closedwon", "closedlost"):
            by_channel[ch]["pipeline"] += d.get("amount", 0)
        elif d.get("dealstage") == "closedwon":
            by_channel[ch]["closed_won_revenue"] += d.get("amount", 0)
    return {"channels": [{"channel": k, **v} for k, v in by_channel.items()]}


def _channel_economics(deals: list[dict]) -> dict:
    perf = _channel_performance(deals)
    out = []
    for ch in perf["channels"]:
        won_count = sum(
            1
            for d in deals
            if d.get("hs_analytics_source") == ch["channel"] and d.get("dealstage") == "closedwon"
        )
        acv = ch["closed_won_revenue"] / won_count if won_count > 0 else None
        out.append({**ch, "won_count": won_count, "acv": acv})
    return {"channels": out}


def _funnel(deals: list[dict], window: WindowSpec) -> dict:
    stage_order = ["new", "qualified", "discovery", "proposal", "negotiation", "closedwon"]
    counts = defaultdict(int)
    for d in deals:
        stage = d.get("dealstage", "")
        if stage in stage_order:
            counts[stage] += 1
    conversions = []
    for i in range(len(stage_order) - 1):
        a = counts.get(stage_order[i], 0)
        b = counts.get(stage_order[i + 1], 0)
        rate = (b / a * 100) if a > 0 else None
        conversions.append(
            {
                "from_stage": stage_order[i],
                "to_stage": stage_order[i + 1],
                "from_count": a,
                "to_count": b,
                "conversion_pct": rate,
            }
        )
    return {"stage_counts": dict(counts), "conversions": conversions}


def _accountability(deals: list[dict], owners: list[dict], window: WindowSpec) -> dict:
    owner_map = {o["id"]: o for o in owners}
    by_owner = defaultdict(lambda: {"deal_count": 0, "pipeline": 0, "closed_won": 0})
    for d in deals:
        oid = d.get("hubspot_owner_id")
        if oid:
            by_owner[oid]["deal_count"] += 1
            if d.get("dealstage") not in ("closedwon", "closedlost"):
                by_owner[oid]["pipeline"] += d.get("amount", 0)
            elif d.get("dealstage") == "closedwon":
                by_owner[oid]["closed_won"] += d.get("amount", 0)
    rows = []
    for oid, stats in by_owner.items():
        owner = owner_map.get(oid, {"firstName": "?", "lastName": ""})
        rows.append(
            {
                "owner_id": oid,
                "owner_name": f"{owner.get('firstName', '')} {owner.get('lastName', '')}".strip(),
                **stats,
            }
        )
    return {"owners": rows}


def _hygiene(deals: list[dict], contacts: list[dict], rules: dict) -> dict:
    issues = []
    missing_source_count = 0
    missing_owner_count = 0
    missing_lifecycle_count = 0
    for d in deals:
        if rules.get("require_owner") and not d.get("hubspot_owner_id"):
            missing_owner_count += 1
            issues.append(
                {
                    "type": "missing_owner",
                    "entity": "deal",
                    "id": d.get("id"),
                    "name": d.get("dealname"),
                }
            )
        if rules.get("require_source") and not d.get("hs_analytics_source"):
            missing_source_count += 1
            issues.append(
                {
                    "type": "missing_source",
                    "entity": "deal",
                    "id": d.get("id"),
                    "name": d.get("dealname"),
                }
            )
    for c in contacts:
        if rules.get("require_lifecycle") and not c.get("lifecyclestage"):
            missing_lifecycle_count += 1
            issues.append(
                {
                    "type": "missing_lifecycle",
                    "entity": "contact",
                    "id": c.get("id"),
                    "email": c.get("email"),
                }
            )
        if rules.get("require_source") and not c.get("hs_analytics_source"):
            missing_source_count += 1
            issues.append(
                {
                    "type": "missing_source",
                    "entity": "contact",
                    "id": c.get("id"),
                    "email": c.get("email"),
                }
            )
    return {
        "missing_source_count": missing_source_count,
        "missing_owner_count": missing_owner_count,
        "missing_lifecycle_count": missing_lifecycle_count,
        "total_issues": len(issues),
        "issues": issues,
    }


def _forward_motion_input(
    deals: list[dict], contacts: list[dict], rules: dict, window: WindowSpec, today: date
) -> dict:
    """Aggregate rule outputs that the Forward Motion agent consumes."""
    rotting_deals = [
        {
            "id": d.get("id"),
            "name": d.get("dealname"),
            "amount": d.get("amount"),
            "stage": d.get("dealstage"),
            "last_activity": d.get("last_activity_date"),
            "days_stale": (today - la).days
            if (la := _parse_iso_date(d.get("last_activity_date")))
            else None,
        }
        for d in deals
        if d.get("dealstage") not in ("closedwon", "closedlost")
        and (la := _parse_iso_date(d.get("last_activity_date")))
        and (today - la).days > rules["rotting_deal_days"]
    ]
    return {
        "rotting_deals": sorted(
            rotting_deals, key=lambda x: x.get("days_stale") or 0, reverse=True
        ),
        "rotting_pipeline_at_risk": sum(d.get("amount") or 0 for d in rotting_deals),
    }

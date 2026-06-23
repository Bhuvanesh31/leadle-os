"""Deterministic compute over ClientData. Pure functions, no I/O, no agents."""

from __future__ import annotations

import math
from zoneinfo import ZoneInfo

from dashboard.client.model import ClientData


def _rate(n: int, d: int) -> float:
    return (n / d) if d else 0.0


def _status_hits(status: str, keywords: list[str]) -> bool:
    s = (status or "").lower()
    return any(k in s for k in keywords)


def kpis(data: ClientData, rubric: dict) -> dict:
    # Aggregate from campaign-level data (empty list → 0 for each metric).
    sent = sum(c.sent for c in data.email_campaigns)
    opened = sum(c.opened for c in data.email_campaigns)
    clicked = sum(c.clicked for c in data.email_campaigns)
    bounced = sum(c.bounced for c in data.email_campaigns)

    invites = sum(c.invites for c in data.linkedin_campaigns)
    accepted = sum(c.accepted for c in data.linkedin_campaigns)

    delivered = sent - bounced

    # Reply counts from ReplyRecord list.
    li_replies = sum(1 for r in data.replies if r.channel == "linkedin")
    email_replies = sum(1 for r in data.replies if r.channel == "email")
    total_replies = li_replies + email_replies
    positive_replies = sum(1 for r in data.replies if r.sentiment == "positive")
    neutral_replies = sum(1 for r in data.replies if r.sentiment == "neutral")
    negative_replies = sum(1 for r in data.replies if r.sentiment == "negative")

    # Warm-lead outcomes from tracker (meeting_statuses)
    meetings = sum(1 for w in data.warm_leads if _status_hits(w.status, rubric["meeting_statuses"]))

    return {
        "emails_sent": sent,
        "fresh_prospects": sent,
        "opened": opened,
        "clicked": clicked,
        "bounced": bounced,
        "delivered": delivered,
        "open_rate": _rate(opened, delivered),
        "click_rate": _rate(clicked, delivered),
        "bounce_rate": _rate(bounced, sent),  # event-based: bounced/sent
        "invites": invites,
        "accepted": accepted,
        "accept_rate": _rate(accepted, invites),
        "li_replies": li_replies,
        "email_replies": email_replies,
        "total_replies": total_replies,
        "positive_replies": positive_replies,
        "neutral_replies": neutral_replies,
        "negative_replies": negative_replies,
        "leads": positive_replies,  # leads == positive_replies
        "meetings": meetings,
    }


def grade(metric: str, value: float, rubric: dict) -> str:
    bands = rubric["grades"][metric]
    if metric in rubric.get("ascending_metrics", []):
        # lower is better: iterate ascending bands, last satisfied threshold wins
        letter = bands[0][1]
        for threshold, let in bands:
            if value >= threshold:
                letter = let
        return letter
    for threshold, let in bands:  # descending: first satisfied threshold wins
        if value >= threshold:
            return let
    return bands[-1][1]


def scorecard(k: dict, rubric: dict) -> dict:
    # reply_rate: total replies relative to emails sent (combined channel proxy)
    total_sent = k.get("emails_sent", 0) + k.get("invites", 0)
    metrics = {
        "open_rate": k["open_rate"],
        "reply_rate": _rate(k["total_replies"], total_sent),
        "positive": _rate(k["positive_replies"], k["emails_sent"]),
        "bounce_rate": k["bounce_rate"],
        "accept_rate": k["accept_rate"],
    }
    grades = {m: grade(m, v, rubric) for m, v in metrics.items()}
    order = "ABCDF"
    worst = max((grades[m] for m in grades), key=lambda g: order.index(g))
    overall = worst  # roll-up = weakest band (conservative)
    return {"grades": grades, "overall": overall}


def campaign_table(data: ClientData, rubric: dict) -> list[dict]:
    email_rows = []
    for c in data.email_campaigns:
        delivered = c.sent - c.bounced
        reply_rate = _rate(c.replied, c.sent)
        click_rate = _rate(c.clicked, delivered)
        open_rate = _rate(c.opened, delivered)
        bounce_rate = _rate(c.bounced, c.sent)
        email_rows.append(
            {
                "name": c.name,
                "channel": "Email",
                "sent": c.sent,
                "reply_rate": reply_rate,
                "secondary": click_rate,
                "secondary_label": "click",
                "open_rate": open_rate,
                "bounce_rate": bounce_rate,
                "grade": grade("open_rate", open_rate, rubric),
            }
        )
    email_rows.sort(key=lambda r: (-r["reply_rate"], -r["secondary"], -r["open_rate"]))

    li_rows = []
    for c in data.linkedin_campaigns:
        reply_rate = _rate(c.replied, c.invites)
        accept_rate = _rate(c.accepted, c.invites)
        li_rows.append(
            {
                "name": c.name,
                "channel": "LinkedIn",
                "sent": c.invites,
                "reply_rate": reply_rate,
                "secondary": accept_rate,
                "secondary_label": "accept",
                "open_rate": None,
                "bounce_rate": None,
                "grade": grade("accept_rate", accept_rate, rubric),
            }
        )
    li_rows.sort(key=lambda r: (-r["reply_rate"], -r["secondary"]))

    return email_rows + li_rows


def variants(data: ClientData, rubric: dict) -> list[dict]:
    """Per-LinkedIn-campaign variant performance. Sorted by (reply_rate desc, accept_rate desc).
    The first row with replies > 0 is marked winner=True; all others False."""
    rows = []
    for c in data.linkedin_campaigns:
        accept_rate = _rate(c.accepted, c.invites)
        reply_rate = _rate(c.replied, c.invites)
        rows.append(
            {
                "name": c.name,
                "accept_rate": accept_rate,
                "replies": c.replied,
                "reply_rate": reply_rate,
                "hook": (c.variant_message or "")[:80],
                "winner": False,
            }
        )
    rows.sort(key=lambda r: (-r["reply_rate"], -r["accept_rate"]))
    # Flag first row with replies > 0 as winner
    for r in rows:
        if r["replies"] > 0:
            r["winner"] = True
            break
    return rows


def content_steps(data: ClientData) -> list[dict]:
    """Per-step open rates from Instantly step analytics (data.content_steps)."""
    rows = []
    for s in data.content_steps:
        opened = int(s.get("opened", 0) or 0)
        sent = int(s.get("sent", 0) or 0)
        rows.append(
            {
                "step": s.get("step"),
                "open_rate": _rate(opened, sent),
            }
        )
    return rows


def sender_wise(data: ClientData, rubric: dict) -> list[dict]:
    """Per-sender bounce health from data.senders (list of {from_email, sent, bounced})."""
    threshold = rubric["bounce_flag_threshold"]
    rows = []
    for s in data.senders:
        sent = int(s.get("sent", 0) or 0)
        bounced = int(s.get("bounced", 0) or 0)
        bounce_rate = _rate(bounced, sent)
        rows.append(
            {
                "from_email": s.get("from_email"),
                "volume": sent,
                "bounced": bounced,
                "bounce_rate": bounce_rate,
                "flag": bounce_rate >= threshold,
            }
        )
    return rows


def deliverability(data: ClientData, rubric: dict) -> list[dict]:
    flags = []
    for s in sender_wise(data, rubric):
        if s["flag"]:
            flags.append(
                {
                    "sender": s["from_email"],
                    "bounce_rate": s["bounce_rate"],
                    "note": "pause & warm",
                }
            )
    return flags


def _daypart(hour: int, dayparts: list) -> str | None:
    for label, start, end in dayparts:
        if start <= hour < end:
            return label
    return None


def timing_heatmap(data: ClientData, rubric: dict) -> dict:
    tz = ZoneInfo(rubric["timezone"])
    dayparts = rubric["dayparts"]
    weekdays = ["Mon", "Tue", "Wed", "Thu", "Fri"]
    labels = [d[0] for d in dayparts]
    grid = {wd: {lbl: 0 for lbl in labels} for wd in weekdays}
    best = {"weekday": None, "daypart": None, "count": -1}
    for e in data.opens:
        if e.channel != "email":
            continue
        if e.ts is None:
            continue
        local = e.ts.astimezone(tz)
        wd = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"][local.weekday()]
        if wd not in grid:
            continue
        part = _daypart(local.hour, dayparts)
        if part is None:
            continue
        grid[wd][part] += 1
        if grid[wd][part] > best["count"]:
            best = {"weekday": wd, "daypart": part, "count": grid[wd][part]}
    mx = max(grid[wd][lbl] for wd in weekdays for lbl in labels)
    levels = (
        {
            wd: {
                lbl: (0 if grid[wd][lbl] == 0 else math.ceil(4 * grid[wd][lbl] / mx))
                for lbl in labels
            }
            for wd in weekdays
        }
        if mx > 0
        else {wd: {lbl: 0 for lbl in labels} for wd in weekdays}
    )
    return {
        "weekdays": weekdays,
        "dayparts": labels,
        "grid": grid,
        "levels": levels,
        "max": mx,
        "best": best,
        "timezone": rubric["timezone"],
        "note": "Engagement (opens), not replies. LinkedIn timing N/A (Aimfox).",
    }


def lead_ladder(data: ClientData, rubric: dict) -> dict:
    hot: list[dict] = []
    seen: set[str] = set()

    # Source 1: positive replies from the reply stream (replies first).
    for r in data.replies:
        if r.sentiment != "positive":
            continue
        key = (r.name or "").lower()
        if key and key in seen:
            continue
        if key:
            seen.add(key)
        hot.append(
            {
                "name": r.name,
                "title": "",
                "company": "",
                "channel": r.channel,
                "status": "Positive reply",
                "tier": "Hot",
                "response_text": "",
            }
        )

    # Source 2: warm-lead tracker rows matching meeting or positive statuses.
    for w in data.warm_leads:
        is_meeting = _status_hits(w.status, rubric["meeting_statuses"])
        is_positive = _status_hits(w.status, rubric["positive_statuses"])
        if not (is_meeting or is_positive):
            continue
        key = (w.linkedin_url or w.name).lower()
        if key in seen:
            continue
        seen.add(key)
        hot.append(
            {
                "name": w.name,
                "title": w.title,
                "company": w.company,
                "channel": w.channel,
                "status": w.status,
                "tier": "Hot",
                "response_text": w.response_text,
            }
        )

    reach = channel_reach(data)
    reached = max(reach["linkedin_reached"] + reach["email_reached"] - reach["both_reached"], 0)
    positive_leads = sum(1 for r in data.replies if r.sentiment == "positive")
    meetings = sum(1 for w in data.warm_leads if _status_hits(w.status, rubric["meeting_statuses"]))
    warm_count = sum(c.accepted for c in data.linkedin_campaigns)
    engaged = warm_count + len(data.replies)

    return {
        "reached": reached,
        "engaged": engaged,
        "positive_leads": positive_leads,
        "meetings": meetings,
        "hot": hot,
        "warm_count": warm_count,
    }


def channel_reach(data: ClientData) -> dict:
    """Unique prospects reached per channel, from the spine cadence IDs.
    Non-empty Aimfox ID = entered LinkedIn cadence; Instantly ID = entered email cadence.
    Dedupe on the id value (it is the unique key); 'both' = holds both ids."""
    li = {t.aimfox_id for t in data.targets if t.aimfox_id}
    em = {t.instantly_id for t in data.targets if t.instantly_id}
    both = {t.aimfox_id for t in data.targets if t.aimfox_id and t.instantly_id}
    return {
        "linkedin_reached": len(li),
        "email_reached": len(em),
        "both_reached": len(both),
    }


def campaign_boxes(data: ClientData, rubric: dict) -> dict:
    """Four ranked, top-5, performer-only boxes + the excluded non-performers.

    Contract: ``excluded`` is always a dict with both "email" and "linkedin" keys
    (initialised to empty lists below). Template code may safely test
    ``metrics.boxes.excluded.email`` and ``metrics.boxes.excluded.linkedin``
    without an ``is defined`` guard.
    """
    excluded = {"email": [], "linkedin": []}

    # Email campaigns: reply -> click -> open; drop 0-open
    email = []
    for c in data.email_campaigns:
        delivered = c.sent - c.bounced
        open_rate = _rate(c.opened, delivered)
        if open_rate == 0:
            excluded["email"].append(c.name)
            continue
        email.append({
            "name": c.name, "sent": c.sent,
            "reply_rate": _rate(c.replied, c.sent),
            "click_rate": _rate(c.clicked, delivered),
            "open_rate": open_rate,
            "bounce_rate": _rate(c.bounced, c.sent),
            "grade": grade("open_rate", open_rate, rubric),
        })
    email.sort(key=lambda r: (-r["reply_rate"], -r["click_rate"], -r["open_rate"]))

    # Email steps: drop 0-open; rank by open_rate; label "campaign — Step N"
    steps = []
    for s in data.content_steps:
        open_rate = _rate(int(s.get("opened", 0) or 0), int(s.get("sent", 0) or 0))
        if open_rate == 0:
            continue
        steps.append({
            "campaign": s.get("campaign", ""), "step": s.get("step"),
            "label": f'{s.get("campaign", "")} — Step {s.get("step")}',
            "open_rate": open_rate,
            "click_rate": _rate(int(s.get("clicked", 0) or 0), int(s.get("sent", 0) or 0)),
            "subject": s.get("subject", ""), "body_preview": s.get("body_preview", ""),
        })
    steps.sort(key=lambda r: -r["open_rate"])

    # LinkedIn campaigns: reply -> accept; drop 0 connections
    li = []
    for c in data.linkedin_campaigns:
        accept_rate = _rate(c.accepted, c.invites)
        if c.accepted == 0:
            excluded["linkedin"].append(c.name)
            continue
        li.append({
            "name": c.name, "invites": c.invites, "connections": c.accepted,
            "reply_rate": _rate(c.replied, c.invites), "accept_rate": accept_rate,
        })
    li.sort(key=lambda r: (-r["reply_rate"], -r["accept_rate"]))

    # LinkedIn variants: reuse variants(); drop 0 accepts
    var = [v for v in variants(data, rubric) if v["accept_rate"] > 0]
    var.sort(key=lambda r: (-r["reply_rate"], -r["accept_rate"]))

    return {
        "email_campaigns": email[:5],
        "email_steps": steps[:5],
        "linkedin_campaigns": li[:5],
        "linkedin_variants": var[:5],
        "excluded": excluded,
    }


def compute_all(data: ClientData, rubric: dict) -> dict:
    k = kpis(data, rubric)
    return {
        "kpis": k,
        "scorecard": scorecard(k, rubric),
        "campaigns": campaign_table(data, rubric),
        "content": content_steps(data),
        "variants": variants(data, rubric),
        "senders": sender_wise(data, rubric),
        "deliverability": deliverability(data, rubric),
        "timing": timing_heatmap(data, rubric),
        "reach": channel_reach(data),
        "leads": lead_ladder(data, rubric),
        "boxes": campaign_boxes(data, rubric),
    }

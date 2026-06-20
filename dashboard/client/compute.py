"""Deterministic compute over ClientData. Pure functions, no I/O, no agents."""
from __future__ import annotations

from collections import Counter, defaultdict
from zoneinfo import ZoneInfo

from dashboard.client.model import ClientData


def _rate(n: int, d: int) -> float:
    return (n / d) if d else 0.0


def _status_hits(status: str, keywords: list[str]) -> bool:
    s = (status or "").lower()
    return any(k in s for k in keywords)


def kpis(data: ClientData, rubric: dict) -> dict:
    # Aggregate from campaign-level data; fall back to event-based counts when
    # email_campaigns is empty (supports legacy event-only ClientData shapes).
    if data.email_campaigns:
        sent = sum(c.sent for c in data.email_campaigns)
        opened = sum(c.opened for c in data.email_campaigns)
        clicked = sum(c.clicked for c in data.email_campaigns)
        bounced = sum(c.bounced for c in data.email_campaigns)
    else:
        # TODO(Task-11): remove this fallback once compute_all + remaining functions are migrated
        ec = Counter(e.event_type for e in data.emails)
        sent = ec.get("email_sent", 0)
        opened = ec.get("email_opened", 0)
        clicked = ec.get("link_clicked", 0)
        bounced = ec.get("email_bounced", 0)

    if data.linkedin_campaigns:
        invites = sum(c.invites for c in data.linkedin_campaigns)
        accepted = sum(c.accepted for c in data.linkedin_campaigns)
    else:
        # TODO(Task-11): remove this fallback once compute_all + remaining functions are migrated
        lc = Counter(e.event_type for e in data.linkedin)
        invites = lc.get("connect", 0)
        accepted = lc.get("accepted", 0)

    delivered = sent - bounced

    # Reply counts from ReplyRecord list (new path) or LinkedIn events (legacy)
    if data.replies:
        li_replies = sum(1 for r in data.replies if r.channel == "linkedin")
        email_replies = sum(1 for r in data.replies if r.channel == "email")
        total_replies = li_replies + email_replies
        positive_replies = sum(1 for r in data.replies if r.sentiment == "positive")
        neutral_replies = sum(1 for r in data.replies if r.sentiment == "neutral")
        negative_replies = sum(1 for r in data.replies if r.sentiment == "negative")
    else:
        # TODO(Task-11): remove this fallback once compute_all + remaining functions are migrated
        lc = Counter(e.event_type for e in data.linkedin)
        li_replies = lc.get("reply", 0)
        email_replies = 0
        total_replies = li_replies
        positive_replies = sum(1 for w in data.warm_leads
                               if _status_hits(w.status, rubric["positive_statuses"]))
        neutral_replies = 0
        negative_replies = 0

    # Warm-lead outcomes from tracker (meeting_statuses)
    meetings = sum(1 for w in data.warm_leads
                   if _status_hits(w.status, rubric["meeting_statuses"]))

    return {
        "emails_sent": sent,
        "fresh_prospects": sent,
        "opened": opened,
        "clicked": clicked,
        "bounced": bounced,
        "delivered": delivered,
        "open_rate": _rate(opened, delivered),
        "click_rate": _rate(clicked, delivered),
        "bounce_rate": _rate(bounced, sent),        # event-based: bounced/sent
        "invites": invites,
        "accepted": accepted,
        "accept_rate": _rate(accepted, invites),
        "li_replies": li_replies,
        "email_replies": email_replies,
        "total_replies": total_replies,
        "positive_replies": positive_replies,
        "neutral_replies": neutral_replies,
        "negative_replies": negative_replies,
        "leads": positive_replies,                  # leads == positive_replies
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
        email_rows.append({
            "name": c.name,
            "channel": "Email",
            "sent": c.sent,
            "reply_rate": reply_rate,
            "secondary": click_rate,
            "secondary_label": "click",
            "open_rate": open_rate,
            "bounce_rate": bounce_rate,
            "grade": grade("open_rate", open_rate, rubric),
        })
    email_rows.sort(key=lambda r: (-r["reply_rate"], -r["secondary"], -r["open_rate"]))

    li_rows = []
    for c in data.linkedin_campaigns:
        reply_rate = _rate(c.replied, c.invites)
        accept_rate = _rate(c.accepted, c.invites)
        li_rows.append({
            "name": c.name,
            "channel": "LinkedIn",
            "sent": c.invites,
            "reply_rate": reply_rate,
            "secondary": accept_rate,
            "secondary_label": "accept",
            "open_rate": None,
            "bounce_rate": None,
            "grade": grade("accept_rate", accept_rate, rubric),
        })
    li_rows.sort(key=lambda r: (-r["reply_rate"], -r["secondary"]))

    return email_rows + li_rows


def sender_wise(data: ClientData, rubric: dict) -> list[dict]:
    agg: dict[str, Counter] = defaultdict(Counter)
    for e in data.emails:
        agg[e.from_email][e.event_type] += 1
    threshold = rubric["bounce_flag_threshold"]
    rows = []
    for sender, c in sorted(agg.items()):
        sent = c.get("email_sent", 0)
        vol = sum(c.values())
        bounced = c.get("email_bounced", 0)
        denom = sent or vol
        bounce_rate = _rate(bounced, denom)
        rows.append({
            "from_email": sender, "volume": vol,
            "opened": c.get("email_opened", 0),
            "open_rate": _rate(c.get("email_opened", 0), sent),
            "bounced": bounced, "bounce_rate": bounce_rate,
            "flag": bounce_rate >= threshold,
        })
    return rows


def deliverability(data: ClientData, rubric: dict) -> list[dict]:
    flags = []
    for s in sender_wise(data, rubric):
        if s["flag"]:
            flags.append({
                "sender": s["from_email"],
                "bounce_rate": s["bounce_rate"],
                "note": "pause & warm",
            })
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
    for e in data.emails:
        if e.event_type not in ("email_opened", "link_clicked"):
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
    return {
        "weekdays": weekdays, "dayparts": labels, "grid": grid, "best": best,
        "timezone": rubric["timezone"],
        "note": "Engagement (opens/clicks), not replies. LinkedIn timing N/A (Aimfox).",
    }


def lead_ladder(data: ClientData, rubric: dict) -> dict:
    hot: list[dict] = []
    seen: set[str] = set()
    for w in data.warm_leads:
        key = (w.linkedin_url or w.name).lower()
        if key in seen:
            continue
        seen.add(key)
        is_meeting = _status_hits(w.status, rubric["meeting_statuses"])
        is_positive = _status_hits(w.status, rubric["positive_statuses"])
        if is_meeting or is_positive:
            hot.append({
                "name": w.name, "title": w.title, "company": w.company,
                "channel": w.channel, "status": w.status, "tier": "Hot",
                "response_text": w.response_text,
            })
    # Warm tier = engaged on LinkedIn (accepted) not already Hot
    warm: list[dict] = []
    for e in data.linkedin:
        if e.event_type != "accepted":
            continue
        key = (e.profile_url or e.prospect_name).lower()
        if key in seen:
            continue
        seen.add(key)
        warm.append({
            "name": e.prospect_name, "title": e.title, "company": e.company,
            "channel": "LinkedIn", "status": "Accepted invite", "tier": "Warm",
            "response_text": "",
        })
    reached = len(data.emails) + len(data.linkedin) - len(hot) - len(warm)
    return {"hot": hot, "warm": warm, "reached_count": max(reached, 0)}


def coverage(data: ClientData) -> dict:
    by_segment: dict[str, dict] = defaultdict(lambda: {"targets": 0, "contacted": 0})
    contacted_companies = {e.company for e in data.emails} | {
        e.company for e in data.linkedin}
    for t in data.targets:
        seg = by_segment[t.segment]
        seg["targets"] += 1
        if t.name in contacted_companies:
            seg["contacted"] += 1
    return {
        "by_segment": dict(by_segment),
        "target_total": len(data.targets),
        "contacted_total": len(contacted_companies),
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


def compute_all(data: ClientData, rubric: dict) -> dict:
    k = kpis(data, rubric)
    return {
        "kpis": k,
        "scorecard": scorecard(k, rubric),
        "campaigns": campaign_table(data, rubric),
        "senders": sender_wise(data, rubric),
        "deliverability": deliverability(data, rubric),
        "timing": timing_heatmap(data, rubric),
        "leads": lead_ladder(data, rubric),
        "coverage": coverage(data),
        "reach": channel_reach(data),
    }

"""Deterministic compute over ClientData. Pure functions, no I/O, no agents."""
from __future__ import annotations

from collections import Counter, defaultdict

from dashboard.client.model import ClientData


def _rate(n: int, d: int) -> float:
    return (n / d) if d else 0.0


def _status_hits(status: str, keywords: list[str]) -> bool:
    s = (status or "").lower()
    return any(k in s for k in keywords)


def kpis(data: ClientData, rubric: dict) -> dict:
    ec = Counter(e.event_type for e in data.emails)
    sent = ec.get("email_sent", 0)
    opened = ec.get("email_opened", 0)
    clicked = ec.get("link_clicked", 0)
    bounced = ec.get("email_bounced", 0)
    lc = Counter(e.event_type for e in data.linkedin)
    invites = lc.get("connect", 0)
    accepted = lc.get("accepted", 0)
    li_replied = lc.get("reply", 0)
    positive = sum(1 for w in data.warm_leads
                   if _status_hits(w.status, rubric["positive_statuses"]))
    meetings = sum(1 for w in data.warm_leads
                   if _status_hits(w.status, rubric["meeting_statuses"]))
    return {
        "emails_sent": sent, "opened": opened, "clicked": clicked, "bounced": bounced,
        "open_rate": _rate(opened, sent), "click_rate": _rate(clicked, sent),
        "bounce_rate": _rate(bounced, sent),
        "invites": invites, "accepted": accepted, "li_replied": li_replied,
        "accept_rate": _rate(accepted, invites),
        "li_reply_rate": _rate(li_replied, invites),
        "positive_replies": positive, "meetings": meetings,
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
    metrics = {
        "open_rate": k["open_rate"], "reply_rate": k["li_reply_rate"],
        "positive": _rate(k["positive_replies"], max(k["emails_sent"], 1)),
        "bounce_rate": k["bounce_rate"], "accept_rate": k["accept_rate"],
    }
    grades = {m: grade(m, v, rubric) for m, v in metrics.items()}
    order = "ABCD"
    worst = max((grades[m] for m in grades), key=lambda g: order.index(g))
    overall = worst  # roll-up = weakest band (conservative)
    return {"grades": grades, "overall": overall}


def campaign_table(data: ClientData, rubric: dict) -> list[dict]:
    by_campaign: dict[str, Counter] = defaultdict(Counter)
    for e in data.emails:
        by_campaign[e.campaign][e.event_type] += 1
    rows = []
    for name, c in sorted(by_campaign.items()):
        sends = c.get("email_sent", 0)
        opened = c.get("email_opened", 0)
        rows.append({
            "name": name, "channel": "Email", "sends": sends,
            "rate": _rate(opened, sends), "rate_label": "open",
            "positives": 0,
            "grade": grade("open_rate", _rate(opened, sends), rubric),
        })
    return rows

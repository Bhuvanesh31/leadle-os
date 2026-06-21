"""Aimfox REST connector.

Fetches campaigns and windowed interaction analytics, sums daily buckets into
per-campaign stats matching the {sends, replies, meetings} shape page4_outreach
expects. Used as a REST fallback while the Aimfox MCP OAuth flow is broken
on the vendor side.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

import httpx

_BASE_URL = "https://api.aimfox.com/api/v2"
_TIMEOUT = 30.0


def fetch(
    api_key: str,
    window_start: date,
    window_end: date,
    *,
    name_contains: str | None = None,
    client: httpx.Client | None = None,
) -> dict[str, Any]:
    """Return {available, data: {campaigns: [...]}} or {available: False, reason: ...}.

    The returned shape matches what raw["sources"]["aimfox"] must look like for
    dashboard.compute.page4_outreach to consume. On any HTTP error we degrade
    to available=False so the dashboard renders cleanly without aimfox data.

    If name_contains is set, campaigns whose name doesn't contain that substring
    (case-insensitive) are dropped before the per-campaign metrics calls — this
    is both a relevance filter and a cost saver (one HTTP call per kept campaign).
    """
    headers = {"Authorization": f"Bearer {api_key}"}
    owns_client = client is None
    client = client or httpx.Client(headers=headers, timeout=_TIMEOUT)
    try:
        campaigns = _list_campaigns(client)
        if name_contains:
            needle = name_contains.lower()
            campaigns = [c for c in campaigns if needle in (c.get("name") or "").lower()]
        start_ms, end_ms = _window_to_epoch_ms(window_start, window_end)
        out = [
            _shape_campaign(c, _fetch_window_metrics(client, c["id"], start_ms, end_ms))
            for c in campaigns
        ]
        return {
            "available": True,
            "data": {"campaigns": out},
            "meta": {
                "source": "rest",
                "window": [window_start.isoformat(), window_end.isoformat()],
                "name_contains": name_contains,
            },
        }
    except httpx.HTTPError as e:
        return {"available": False, "reason": f"aimfox REST error: {type(e).__name__}: {e}"}
    finally:
        if owns_client:
            client.close()


def _list_campaigns(client: httpx.Client) -> list[dict]:
    r = client.get(f"{_BASE_URL}/campaigns")
    r.raise_for_status()
    return r.json().get("campaigns", [])


def _fetch_window_metrics(
    client: httpx.Client, campaign_id: str, start_ms: int, end_ms: int
) -> dict[str, int]:
    r = client.get(
        f"{_BASE_URL}/analytics/interactions",
        params={
            "campaign_id": campaign_id,
            "from": start_ms,
            "to": end_ms,
            "bucket": "1 day",
        },
    )
    r.raise_for_status()
    return _sum_buckets(r.json().get("buckets", []))


def _sum_buckets(buckets: list[dict]) -> dict[str, int]:
    """Sum windowed daily buckets into total counts for the metrics we use."""
    totals = {k: 0 for k in (
        "sent_connections", "sent_messages", "sent_inmails",
        "message_requests", "replies",
    )}
    for b in buckets:
        for k in totals:
            totals[k] += b.get(k, 0)
    return totals


def _shape_campaign(campaign: dict, metrics: dict[str, int]) -> dict[str, Any]:
    sends = (
        metrics["sent_connections"]
        + metrics["sent_messages"]
        + metrics["sent_inmails"]
        + metrics["message_requests"]
    )
    return {
        "id": campaign.get("id"),
        "name": campaign.get("name"),
        "stats": {
            "sends": sends,
            "replies": metrics["replies"],
            "meetings": 0,
        },
    }


def fetch_campaign_detail(client: httpx.Client, cid: str) -> dict:
    """Return the `campaign` dict from GET /campaigns/{id}."""
    r = client.get(f"{_BASE_URL}/campaigns/{cid}")
    r.raise_for_status()
    return r.json().get("campaign", {})


def _window_to_epoch_ms(start: date, end: date) -> tuple[int, int]:
    start_dt = datetime.combine(start, datetime.min.time(), tzinfo=timezone.utc)
    end_dt = datetime.combine(end, datetime.max.time(), tzinfo=timezone.utc)
    return int(start_dt.timestamp() * 1000), int(end_dt.timestamp() * 1000)

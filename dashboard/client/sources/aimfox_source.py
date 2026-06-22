"""Aimfox source: read LinkedIn campaigns + variant text into LinkedInCampaign models.

Calls:
  GET /campaigns                           → list all campaigns
  GET /campaigns/{id}                      → campaign detail (flows → variant_message)
  GET /analytics/interactions?...          → daily buckets → summed metrics
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import httpx

from connectors.aimfox.fetch import _BASE_URL, _TIMEOUT, fetch_campaign_detail
from dashboard.client.model import LinkedInCampaign


def read(
    api_key: str,
    window: tuple[str, str],
    *,
    name_contains: str,
    client: httpx.Client | None = None,
) -> list[LinkedInCampaign]:
    """Return LinkedInCampaign list filtered by name_contains (case-insensitive).

    window is a (start_iso, end_iso) tuple of ISO date strings (YYYY-MM-DD).
    """
    headers = {"Authorization": f"Bearer {api_key}"}
    owns_client = client is None
    client = client or httpx.Client(headers=headers, timeout=_TIMEOUT)
    try:
        campaigns = _list_campaigns(client)
        needle = name_contains.lower()
        campaigns = [c for c in campaigns if needle in (c.get("name") or "").lower()]

        start_ms, end_ms = _iso_window_to_epoch_ms(window[0], window[1])

        result: list[LinkedInCampaign] = []
        for c in campaigns:
            cid = c["id"]
            metrics = _fetch_interactions(client, cid, start_ms, end_ms)
            detail = fetch_campaign_detail(client, cid)
            variant = _extract_variant(detail)
            result.append(
                LinkedInCampaign(
                    name=c.get("name", ""),
                    invites=metrics["invites"],
                    accepted=metrics["accepted"],
                    replied=metrics["replied"],
                    variant_message=variant,
                )
            )
        return result
    finally:
        if owns_client:
            client.close()


def _list_campaigns(client: httpx.Client) -> list[dict]:
    r = client.get(f"{_BASE_URL}/campaigns")
    r.raise_for_status()
    return r.json().get("campaigns", [])


def _fetch_interactions(
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
    invites = accepted = replied = 0
    for b in buckets:
        invites += b.get("sent_connections", 0)
        accepted += b.get("accepted_connections", 0)
        replied += b.get("replies", 0) + b.get("inmail_replies", 0)
    return {"invites": invites, "accepted": accepted, "replied": replied}


def _extract_variant(campaign_detail: dict) -> str:
    for flow in campaign_detail.get("flows", []):
        if flow.get("type") == "PRIMARY_CONNECT":
            return flow.get("template", {}).get("message", "")
    return ""


def _iso_window_to_epoch_ms(start_iso: str, end_iso: str) -> tuple[int, int]:
    start = date.fromisoformat(start_iso)
    end = date.fromisoformat(end_iso)
    start_dt = datetime.combine(start, datetime.min.time(), tzinfo=UTC)
    end_dt = datetime.combine(end, datetime.max.time(), tzinfo=UTC)
    return int(start_dt.timestamp() * 1000), int(end_dt.timestamp() * 1000)

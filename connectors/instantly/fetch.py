"""Instantly REST connector. Mirrors connectors/aimfox/fetch.py.

Per-campaign authoritative analytics (NOT the daily endpoint, which double-counts).
senders and steps arrays are returned empty here; Task 9 populates them.
"""
from __future__ import annotations

from typing import Any

import httpx

_BASE_URL = "https://api.instantly.ai/api/v2"
_TIMEOUT = 30.0
_UA = "Mozilla/5.0"  # default urllib UA is WAF-blocked (see docs/data-shape)


def fetch(
    api_key: str,
    window_start,
    window_end,
    *,
    name_contains: str | None = None,
    client: httpx.Client | None = None,
) -> dict[str, Any]:
    """Return {available, data: {campaigns, senders, steps}} or {available: False, reason}.

    Per-campaign analytics use the authoritative /campaigns/analytics endpoint,
    not the daily endpoint (daily double-counts sends). senders and steps are
    intentionally empty — Task 9 populates them.

    If name_contains is set, campaigns whose name doesn't contain that substring
    (case-insensitive) are dropped before per-campaign analytics calls.
    """
    headers = {"Authorization": f"Bearer {api_key}", "User-Agent": _UA}
    owns = client is None
    client = client or httpx.Client(headers=headers, timeout=_TIMEOUT)
    try:
        camps = _list_campaigns(client)
        if name_contains:
            needle = name_contains.lower()
            camps = [c for c in camps if needle in (c.get("name") or "").lower()]
        out = [_shape(c, _analytics(client, c["id"], window_start, window_end)) for c in camps]
        return {"available": True, "data": {"campaigns": out, "senders": [], "steps": []}}
    except httpx.HTTPError as e:
        return {"available": False, "reason": f"instantly REST error: {type(e).__name__}: {e}"}
    finally:
        if owns:
            client.close()


def _list_campaigns(client: httpx.Client) -> list[dict]:
    r = client.get(f"{_BASE_URL}/campaigns")
    r.raise_for_status()
    body = r.json()
    return body.get("items", body.get("campaigns", []))


def _analytics(client: httpx.Client, cid: str, start, end) -> dict:
    r = client.get(
        f"{_BASE_URL}/campaigns/analytics",
        params={"id": cid, "start_date": str(start), "end_date": str(end)},
    )
    r.raise_for_status()
    a = r.json()
    if isinstance(a, list):
        a = a[0] if a else {}
    return a


def _shape(c: dict, a: dict) -> dict[str, Any]:
    return {
        "name": c.get("name"),
        "sent": int(a.get("emails_sent_count", 0) or 0),
        "opened": int(a.get("open_count", 0) or 0),
        "clicked": int(a.get("link_click_count", 0) or 0),
        "bounced": int(a.get("bounced_count", 0) or 0),
        "replied": int(a.get("reply_count", 0) or 0),
    }

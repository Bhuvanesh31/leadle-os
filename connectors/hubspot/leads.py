"""HubSpot Leads REST connector.

The claude.ai HubSpot MCP doesn't expose the Leads object — see CLAUDE.md.
This connector closes that gap via HubSpot's private-app API. It mirrors
the Aimfox connector pattern: a sync httpx call, fail-open on errors, returns
the source-agnostic shape page2_activity expects.

Only Leads (HubSpot's separate object since 2024 in Sales Hub Pro+) — NOT
contacts. The two are semantically different: 'lifecyclestage = lead' on
contacts is a marketing attribute applied broadly; the Leads object is the
sales team's actual work queue.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

import httpx

_BASE_URL = "https://api.hubapi.com"
_TIMEOUT = 30.0
_PAGE_LIMIT = 100  # HubSpot search endpoint max page size

# Properties to request from each Lead record. Keeps the response slim and
# documents exactly what downstream compute can rely on.
LEAD_PROPERTIES = [
    "hs_object_id",
    "hs_lead_name",
    "hs_lead_status",
    "hs_pipeline",
    "hs_pipeline_stage",
    "hubspot_owner_id",
    "hs_createdate",
    "hs_lastmodifieddate",
    "hs_contact_last_activity_date",
    "hs_associated_contact_email",
    "hs_associated_contact_firstname",
    "hs_associated_contact_lastname",
    # Company association — used by page3 gap matching to bridge Fathom-
    # call attendees to deals when the email-domain-root doesn't reflect
    # the deal-naming brand (e.g. LevoWorld lead → Deal "Levo Exhibitions
    # & Events").
    "hs_associated_company_name",
    "hs_associated_company_domain",
    # Attribution — used by the source-hygiene check on page3.
    # Leadle uses the custom property `lead_source_v2` rather than HubSpot's
    # legacy `hs_contact_analytics_source` for primary lead attribution.
    "lead_source_v2",
    "hs_contact_analytics_source",
]


def fetch(
    token: str,
    window_start: date,
    window_end: date,
    *,
    owner_allowlist: list[str] | None = None,
    client: httpx.Client | None = None,
) -> dict[str, Any]:
    """Return {available, data: {leads, total}} or {available: False, reason: ...}.

    Filters: hs_createdate in [window_start, window_end].
    If owner_allowlist is provided, only Leads owned by one of those IDs are kept.

    Each shaped lead carries an `associated_deal_ids: list[str]` populated from
    HubSpot's lead-to-deal association table — this is what makes the Page 3
    gap analysis authoritative (no more name-matching heuristics needed when
    a real association exists in HubSpot).
    """
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    owns_client = client is None
    client = client or httpx.Client(headers=headers, timeout=_TIMEOUT)
    try:
        leads = _paginated_search(client, window_start, window_end)
        shaped = [_shape_lead(l) for l in leads]
        if owner_allowlist is not None:
            allow = set(owner_allowlist)
            shaped = [l for l in shaped if l.get("hubspot_owner_id") in allow]
        # Augment with lead → deal associations
        lead_ids = [l["id"] for l in shaped if l.get("id")]
        associations = _fetch_lead_deal_associations(client, lead_ids)
        for l in shaped:
            l["associated_deal_ids"] = associations.get(l["id"], [])
        return {
            "available": True,
            "data": {"leads": shaped, "total": len(shaped)},
            "meta": {
                "source": "rest",
                "window": [window_start.isoformat(), window_end.isoformat()],
                "owner_filter": owner_allowlist,
            },
        }
    except httpx.HTTPError as e:
        return {"available": False, "reason": f"hubspot Leads REST error: {type(e).__name__}: {e}"}
    finally:
        if owns_client:
            client.close()


def _fetch_lead_deal_associations(client: httpx.Client, lead_ids: list[str]) -> dict[str, list[str]]:
    """Return {lead_id: [deal_id, ...]} from HubSpot's association API.

    Uses /crm/v3/associations/leads/deals/batch/read. Returns 207 (partial)
    when some leads have associations and others don't — this is normal.
    Leads with no associations appear in the response's errors[] array as
    NO_ASSOCIATIONS_FOUND, not in results[].
    """
    out: dict[str, list[str]] = {}
    if not lead_ids:
        return out
    BATCH_SIZE = 100
    for i in range(0, len(lead_ids), BATCH_SIZE):
        batch = lead_ids[i : i + BATCH_SIZE]
        r = client.post(
            f"{_BASE_URL}/crm/v3/associations/leads/deals/batch/read",
            json={"inputs": [{"id": str(lid)} for lid in batch]},
        )
        # 207 = multi-status (some succeeded, some had no associations)
        if r.status_code not in (200, 207):
            r.raise_for_status()
        for result in r.json().get("results", []):
            from_id = result.get("from", {}).get("id")
            if not from_id:
                continue
            out[from_id] = [t.get("id") for t in result.get("to", []) if t.get("id")]
    return out


def _paginated_search(client: httpx.Client, window_start: date, window_end: date) -> list[dict]:
    out: list[dict] = []
    after: str | None = None
    while True:
        body = {
            "filterGroups": [{
                "filters": [
                    {
                        "propertyName": "hs_createdate",
                        "operator": "GTE",
                        "value": _to_epoch_ms(window_start, start_of_day=True),
                    },
                    {
                        "propertyName": "hs_createdate",
                        "operator": "LTE",
                        "value": _to_epoch_ms(window_end, start_of_day=False),
                    },
                ],
            }],
            "properties": LEAD_PROPERTIES,
            "sorts": [{"propertyName": "hs_createdate", "direction": "ASCENDING"}],
            "limit": _PAGE_LIMIT,
        }
        if after is not None:
            body["after"] = after
        r = client.post(f"{_BASE_URL}/crm/v3/objects/leads/search", json=body)
        r.raise_for_status()
        data = r.json()
        out.extend(data.get("results", []))
        after = (data.get("paging") or {}).get("next", {}).get("after")
        if not after:
            break
    return out


def _shape_lead(lead: dict) -> dict[str, Any]:
    """Reshape a raw Leads-API record into the dashboard's expected shape."""
    p = lead.get("properties", {})
    first = p.get("hs_associated_contact_firstname") or ""
    last = p.get("hs_associated_contact_lastname") or ""
    contact_name = f"{first} {last}".strip() or None
    return {
        "id": lead.get("id"),
        "lead_name": p.get("hs_lead_name"),
        "status": p.get("hs_lead_status"),
        "pipeline_id": p.get("hs_pipeline"),
        "pipeline_stage_id": p.get("hs_pipeline_stage"),
        "hubspot_owner_id": p.get("hubspot_owner_id"),
        "createdate": _iso_date(p.get("hs_createdate")),
        "last_activity_date": _iso_date(p.get("hs_contact_last_activity_date") or p.get("hs_lastmodifieddate")),
        "contact_email": p.get("hs_associated_contact_email"),
        "contact_name": contact_name,
        "company_name": p.get("hs_associated_company_name"),
        "company_domain": p.get("hs_associated_company_domain"),
        # Prefer the custom lead_source_v2 attribution; fall back to legacy
        # analytics source. The Page-3 hygiene check uses this directly.
        "source": p.get("lead_source_v2") or p.get("hs_contact_analytics_source"),
        "lead_source_v2": p.get("lead_source_v2"),
    }


def _to_epoch_ms(d: date, *, start_of_day: bool) -> str:
    """HubSpot search filters on datetime properties want epoch-ms strings."""
    if start_of_day:
        dt = datetime.combine(d, datetime.min.time(), tzinfo=timezone.utc)
    else:
        dt = datetime.combine(d, datetime.max.time(), tzinfo=timezone.utc)
    return str(int(dt.timestamp() * 1000))


def _iso_date(s: str | None) -> str | None:
    if not s:
        return None
    return s.split("T")[0]

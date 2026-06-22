"""Tests for the HubSpot Leads REST connector.

httpx.MockTransport for hermetic tests — same pattern as test_aimfox.py.
"""

from __future__ import annotations

from datetime import UTC, date

import httpx

from connectors.hubspot.leads import _shape_lead, _to_epoch_ms, fetch


def _make_client(handler):
    return httpx.Client(
        transport=httpx.MockTransport(handler),
        headers={"Authorization": "Bearer test", "Content-Type": "application/json"},
    )


def _sample_lead(idx: int, owner: str = "80765353", name: str = "Test Lead") -> dict:
    return {
        "id": str(100 + idx),
        "properties": {
            "hs_object_id": str(100 + idx),
            "hs_lead_name": name,
            "hs_lead_status": "NEW",
            "hs_pipeline": "lead-pipeline",
            "hs_pipeline_stage": "new-stage",
            "hubspot_owner_id": owner,
            "hs_createdate": f"2026-04-{(idx % 28) + 1:02d}T10:00:00Z",
            "hs_lastmodifieddate": f"2026-05-{(idx % 12) + 1:02d}T10:00:00Z",
            "hs_contact_last_activity_date": f"2026-05-{(idx % 12) + 1:02d}T10:00:00Z",
            "hs_associated_contact_email": f"lead{idx}@example.com",
            "hs_associated_contact_firstname": "First",
            "hs_associated_contact_lastname": f"Last{idx}",
        },
    }


def test_fetch_returns_shaped_leads():
    """Single-page response — leads shaped into the dashboard's expected fields."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/crm/v3/objects/leads/search"):
            return httpx.Response(
                200,
                json={
                    "total": 2,
                    "results": [_sample_lead(1), _sample_lead(2)],
                },
            )
        if request.url.path.endswith("/crm/v3/associations/leads/deals/batch/read"):
            return httpx.Response(200, json={"results": []})
        return httpx.Response(404)

    with _make_client(handler) as client:
        result = fetch("test", date(2026, 4, 1), date(2026, 6, 30), client=client)

    assert result["available"] is True
    assert result["data"]["total"] == 2
    leads = result["data"]["leads"]
    assert {ld["id"] for ld in leads} == {"101", "102"}
    assert leads[0]["contact_email"] == "lead1@example.com"
    assert leads[0]["contact_name"] == "First Last1"
    assert leads[0]["status"] == "NEW"
    # ISO date — no time component
    assert "T" not in leads[0]["createdate"]


def test_fetch_paginates_via_after_cursor():
    """Two-page response — connector follows paging.next.after until exhausted."""
    pages_seen: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/crm/v3/associations/leads/deals/batch/read"):
            return httpx.Response(200, json={"results": []})
        body = request.read().decode()
        import json as _json

        after = _json.loads(body).get("after")
        pages_seen.append(after)
        if after is None:
            return httpx.Response(
                200,
                json={
                    "total": 3,
                    "results": [_sample_lead(i) for i in range(1, 3)],
                    "paging": {"next": {"after": "cursor-page-2"}},
                },
            )
        return httpx.Response(
            200,
            json={
                "total": 3,
                "results": [_sample_lead(3)],
            },
        )

    with _make_client(handler) as client:
        result = fetch("test", date(2026, 4, 1), date(2026, 6, 30), client=client)

    assert pages_seen == [None, "cursor-page-2"]
    assert result["data"]["total"] == 3


def test_fetch_filters_by_owner_allowlist():
    """owner_allowlist drops leads whose hubspot_owner_id isn't in the set."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/crm/v3/associations/leads/deals/batch/read"):
            return httpx.Response(200, json={"results": []})
        return httpx.Response(
            200,
            json={
                "total": 3,
                "results": [
                    _sample_lead(1, owner="80765353"),  # Sai — keep
                    _sample_lead(2, owner="999999999"),  # unknown — drop
                    _sample_lead(3, owner="77758216"),  # Akil — keep
                ],
            },
        )

    with _make_client(handler) as client:
        result = fetch(
            "test",
            date(2026, 4, 1),
            date(2026, 6, 30),
            owner_allowlist=["80765353", "77758216"],
            client=client,
        )

    assert result["data"]["total"] == 2
    assert {ld["hubspot_owner_id"] for ld in result["data"]["leads"]} == {"80765353", "77758216"}
    assert result["meta"]["owner_filter"] == ["80765353", "77758216"]


def test_fetch_degrades_on_401():
    """401 response → degraded result, dashboard renders cleanly."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"message": "Unauthorized"})

    with _make_client(handler) as client:
        result = fetch("bad-token", date(2026, 4, 1), date(2026, 6, 30), client=client)

    assert result["available"] is False
    assert "401" in result["reason"]


def test_shape_lead_handles_missing_optional_fields():
    """Lead with only required fields shouldn't crash _shape_lead."""
    minimal = {
        "id": "555",
        "properties": {
            "hs_object_id": "555",
            "hs_createdate": "2026-04-15T00:00:00Z",
        },
    }
    out = _shape_lead(minimal)
    assert out["id"] == "555"
    assert out["createdate"] == "2026-04-15"
    assert out["contact_name"] is None  # both first+last missing
    assert out["status"] is None


def test_to_epoch_ms_uses_utc():
    """Boundary helper must produce UTC bounds — same caveat as Aimfox."""
    from datetime import datetime

    start = _to_epoch_ms(date(2026, 4, 1), start_of_day=True)
    end = _to_epoch_ms(date(2026, 4, 1), start_of_day=False)
    expected_start = int(datetime(2026, 4, 1, 0, 0, 0, tzinfo=UTC).timestamp() * 1000)
    assert int(start) == expected_start
    # End-of-day is later than start, within the same UTC date
    assert int(end) > int(start)
    assert int(end) - int(start) < 24 * 3600 * 1000

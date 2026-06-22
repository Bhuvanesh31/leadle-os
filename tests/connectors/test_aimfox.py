"""Tests for the Aimfox REST connector.

Uses httpx.MockTransport for hermetic tests (no httpx-mock or respx dependency).
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import httpx

from connectors.aimfox.fetch import _sum_buckets, _window_to_epoch_ms, fetch


def _make_client(handler):
    transport = httpx.MockTransport(handler)
    return httpx.Client(transport=transport, headers={"Authorization": "Bearer test"})


def test_fetch_aggregates_buckets_into_campaign_stats():
    """Two campaigns, each with two daily buckets — totals roll up per campaign."""
    campaigns = {
        "status": "ok",
        "campaigns": [
            {"id": "c-alpha", "name": "Outbound Alpha", "state": "ACTIVE"},
            {"id": "c-beta", "name": "Outbound Beta", "state": "ACTIVE"},
        ],
    }
    interactions = {
        "c-alpha": {
            "status": "ok",
            "count": 2,
            "buckets": [
                {
                    "timestamp": 1,
                    "sent_connections": 10,
                    "sent_messages": 5,
                    "sent_inmails": 2,
                    "message_requests": 1,
                    "replies": 3,
                    "views": 9,
                    "sent_likes": 0,
                    "sent_endorsements": 0,
                    "accepted_connections": 4,
                },
                {
                    "timestamp": 2,
                    "sent_connections": 8,
                    "sent_messages": 4,
                    "sent_inmails": 0,
                    "message_requests": 0,
                    "replies": 2,
                    "views": 7,
                    "sent_likes": 0,
                    "sent_endorsements": 0,
                    "accepted_connections": 3,
                },
            ],
        },
        "c-beta": {
            "status": "ok",
            "count": 1,
            "buckets": [
                {
                    "timestamp": 1,
                    "sent_connections": 0,
                    "sent_messages": 0,
                    "sent_inmails": 0,
                    "message_requests": 0,
                    "replies": 0,
                    "views": 0,
                    "sent_likes": 0,
                    "sent_endorsements": 0,
                    "accepted_connections": 0,
                },
            ],
        },
    }

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/campaigns"):
            return httpx.Response(200, json=campaigns)
        if request.url.path.endswith("/analytics/interactions"):
            cid = request.url.params["campaign_id"]
            return httpx.Response(200, json=interactions[cid])
        return httpx.Response(404)

    with _make_client(handler) as client:
        result = fetch("test", date(2026, 5, 1), date(2026, 5, 7), client=client)

    assert result["available"] is True
    assert result["meta"] == {
        "source": "rest",
        "window": ["2026-05-01", "2026-05-07"],
        "name_contains": None,
    }
    camps = result["data"]["campaigns"]
    assert len(camps) == 2
    alpha = next(c for c in camps if c["id"] == "c-alpha")
    # sends = sent_connections + sent_messages + sent_inmails + message_requests
    #       = (10+5+2+1) + (8+4+0+0) = 18 + 12 = 30
    assert alpha == {
        "id": "c-alpha",
        "name": "Outbound Alpha",
        "stats": {"sends": 30, "replies": 5, "meetings": 0},
    }
    beta = next(c for c in camps if c["id"] == "c-beta")
    assert beta["stats"] == {"sends": 0, "replies": 0, "meetings": 0}


def test_fetch_returns_unavailable_on_auth_error():
    """A 401 on the campaigns list should produce a degraded result, not raise."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"status": "error", "message": "Unauthorized"})

    with _make_client(handler) as client:
        result = fetch("bad-key", date(2026, 5, 1), date(2026, 5, 7), client=client)

    assert result["available"] is False
    assert "aimfox REST error" in result["reason"]
    assert "401" in result["reason"]


def test_fetch_handles_empty_workspace():
    """Zero campaigns is a valid state, not an error."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/campaigns"):
            return httpx.Response(200, json={"status": "ok", "campaigns": []})
        return httpx.Response(500)

    with _make_client(handler) as client:
        result = fetch("test", date(2026, 5, 1), date(2026, 5, 7), client=client)

    assert result == {
        "available": True,
        "data": {"campaigns": []},
        "meta": {
            "source": "rest",
            "window": ["2026-05-01", "2026-05-07"],
            "name_contains": None,
        },
    }


def test_fetch_passes_window_as_epoch_ms_to_analytics_endpoint():
    """The /analytics/interactions call must receive UTC epoch-ms bounds and bucket=1 day."""
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/campaigns"):
            return httpx.Response(
                200,
                json={
                    "status": "ok",
                    "campaigns": [{"id": "c1", "name": "Solo", "state": "ACTIVE"}],
                },
            )
        if request.url.path.endswith("/analytics/interactions"):
            captured["params"] = dict(request.url.params)
            return httpx.Response(200, json={"status": "ok", "count": 0, "buckets": []})
        return httpx.Response(404)

    with _make_client(handler) as client:
        fetch("test", date(2026, 5, 1), date(2026, 5, 7), client=client)

    assert captured["params"]["campaign_id"] == "c1"
    assert captured["params"]["bucket"] == "1 day"
    # 2026-05-01 00:00:00 UTC = 1777593600000 ms
    # 2026-05-07 23:59:59.999999 UTC = 1778191999999 ms
    assert captured["params"]["from"] == "1777593600000"
    assert int(captured["params"]["to"]) >= 1778191999000  # allow microsecond rounding


def test_window_to_epoch_ms_uses_utc_not_local():
    """Boundary helper must produce UTC bounds regardless of system tz."""
    start_ms, end_ms = _window_to_epoch_ms(date(2026, 5, 1), date(2026, 5, 1))
    expected_start = int(datetime(2026, 5, 1, 0, 0, 0, tzinfo=UTC).timestamp() * 1000)
    expected_end_floor = int(datetime(2026, 5, 1, 23, 59, 59, tzinfo=UTC).timestamp() * 1000)
    assert start_ms == expected_start
    assert end_ms >= expected_end_floor


def test_fetch_filters_campaigns_by_name_contains_before_metrics_calls():
    """name_contains should drop irrelevant campaigns BEFORE per-campaign metrics fetches."""
    metrics_calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/campaigns"):
            return httpx.Response(
                200,
                json={
                    "status": "ok",
                    "campaigns": [
                        {"id": "1", "name": "Leadle_GTM_Open_House", "state": "ACTIVE"},
                        {"id": "2", "name": "ClientX_Outbound", "state": "ACTIVE"},
                        {"id": "3", "name": "leadle_revops_cold", "state": "ACTIVE"},  # lowercase
                        {"id": "4", "name": "Random Campaign", "state": "ACTIVE"},
                    ],
                },
            )
        if request.url.path.endswith("/analytics/interactions"):
            metrics_calls.append(request.url.params["campaign_id"])
            return httpx.Response(200, json={"status": "ok", "count": 0, "buckets": []})
        return httpx.Response(404)

    with _make_client(handler) as client:
        result = fetch(
            "test",
            date(2026, 5, 1),
            date(2026, 5, 7),
            name_contains="Leadle",
            client=client,
        )

    # Only campaigns 1 and 3 should be kept (case-insensitive substring match)
    kept_ids = {c["id"] for c in result["data"]["campaigns"]}
    assert kept_ids == {"1", "3"}
    # Metrics endpoint must NOT have been called for the dropped campaigns (cost saver)
    assert set(metrics_calls) == {"1", "3"}
    assert result["meta"]["name_contains"] == "Leadle"


def test_fetch_without_name_contains_keeps_all_campaigns():
    """When name_contains is None, the filter is a no-op (backwards compatible)."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/campaigns"):
            return httpx.Response(
                200,
                json={
                    "status": "ok",
                    "campaigns": [
                        {"id": "1", "name": "Leadle X", "state": "ACTIVE"},
                        {"id": "2", "name": "ClientX", "state": "ACTIVE"},
                    ],
                },
            )
        if request.url.path.endswith("/analytics/interactions"):
            return httpx.Response(200, json={"status": "ok", "count": 0, "buckets": []})
        return httpx.Response(404)

    with _make_client(handler) as client:
        result = fetch("test", date(2026, 5, 1), date(2026, 5, 7), client=client)

    assert len(result["data"]["campaigns"]) == 2
    assert result["meta"]["name_contains"] is None


def test_sum_buckets_ignores_unused_fields():
    """Aimfox returns more fields than we use (views, likes, endorsements). They're ignored."""
    buckets = [
        {"sent_connections": 5, "replies": 2, "views": 100, "sent_likes": 50},
        {"sent_messages": 3, "replies": 1, "views": 80},
    ]
    totals = _sum_buckets(buckets)
    assert totals == {
        "sent_connections": 5,
        "sent_messages": 3,
        "sent_inmails": 0,
        "message_requests": 0,
        "replies": 3,
    }

"""Tests for connectors.instantly.fetch — mocked via httpx.MockTransport."""
import httpx
from connectors.instantly.fetch import fetch


def _mock(transport_map):
    # Sort by fragment length descending so more-specific paths match before
    # shorter prefixes (e.g. /campaigns/analytics before /campaigns).
    _sorted = sorted(transport_map.items(), key=lambda kv: len(kv[0]), reverse=True)

    def handler(request: httpx.Request) -> httpx.Response:
        for frag, payload in _sorted:
            if frag in str(request.url):
                return httpx.Response(200, json=payload)
        return httpx.Response(404, json={})
    return httpx.MockTransport(handler)


def test_fetch_shapes_campaigns_and_filters_by_name():
    tmap = {
        "/campaigns": {"items": [
            {"id": "c1", "name": "Upsta_SFDI_V1"},
            {"id": "c2", "name": "OtherClient_V1"}]},
        "/campaigns/analytics": {"emails_sent_count": 414, "open_count": 140,
                                 "link_click_count": 42, "bounced_count": 41,
                                 "reply_count": 0},
    }
    client = httpx.Client(transport=_mock(tmap))
    out = fetch("KEY", "2026-06-01", "2026-06-30", name_contains="upsta", client=client)
    assert out["available"] is True
    camps = out["data"]["campaigns"]
    assert [c["name"] for c in camps] == ["Upsta_SFDI_V1"]  # filtered
    assert camps[0]["sent"] == 414 and camps[0]["clicked"] == 42


def test_fetch_degrades_on_http_error():
    def boom(request): raise httpx.ConnectError("down")
    client = httpx.Client(transport=httpx.MockTransport(boom))
    out = fetch("KEY", "2026-06-01", "2026-06-30", name_contains="upsta", client=client)
    assert out["available"] is False and "reason" in out


# ---------------------------------------------------------------------------
# Task 9: senders (GET /accounts/analytics) + steps (GET /campaigns/analytics/steps)
# ---------------------------------------------------------------------------

def test_fetch_populates_senders_from_accounts_analytics():
    tmap = {
        "/campaigns": {"items": [{"id": "c1", "name": "Upsta_SFDI_V1"}]},
        "/campaigns/analytics": {"emails_sent_count": 100, "open_count": 20,
                                  "link_click_count": 5, "bounced_count": 3,
                                  "reply_count": 0},
        "/accounts/analytics": [
            {"from_email": "alice@upsta.co", "sent": 60, "bounced": 2},
            {"from_email": "bob@upsta.co",   "sent": 40, "bounced": 1},
        ],
        "/campaigns/analytics/steps": [],
    }
    client = httpx.Client(transport=_mock(tmap))
    out = fetch("KEY", "2026-06-01", "2026-06-30", client=client)
    assert out["available"] is True
    senders = out["data"]["senders"]
    assert len(senders) == 2
    alice = next(s for s in senders if s["from_email"] == "alice@upsta.co")
    assert alice["sent"] == 60
    assert alice["bounced"] == 2


def test_fetch_senders_missing_keys_default_to_zero():
    """API may return partial rows — missing sent/bounced should become 0."""
    tmap = {
        "/campaigns": {"items": [{"id": "c1", "name": "X"}]},
        "/campaigns/analytics": {},
        "/accounts/analytics": [{"from_email": "partial@x.co"}],  # no sent/bounced
        "/campaigns/analytics/steps": [],
    }
    client = httpx.Client(transport=_mock(tmap))
    out = fetch("KEY", "2026-06-01", "2026-06-30", client=client)
    senders = out["data"]["senders"]
    assert len(senders) == 1
    assert senders[0]["sent"] == 0
    assert senders[0]["bounced"] == 0


def test_fetch_senders_empty_when_endpoint_returns_empty():
    tmap = {
        "/campaigns": {"items": [{"id": "c1", "name": "X"}]},
        "/campaigns/analytics": {},
        "/accounts/analytics": [],
        "/campaigns/analytics/steps": [],
    }
    client = httpx.Client(transport=_mock(tmap))
    out = fetch("KEY", "2026-06-01", "2026-06-30", client=client)
    assert out["data"]["senders"] == []


def test_fetch_populates_steps_from_campaigns_analytics_steps():
    """Steps endpoint returns list of step analytics for the campaign."""
    tmap = {
        "/campaigns": {"items": [{"id": "c1", "name": "Upsta_V1"}]},
        "/campaigns/analytics": {"emails_sent_count": 100, "open_count": 20,
                                  "link_click_count": 5, "bounced_count": 2,
                                  "reply_count": 0},
        "/accounts/analytics": [],
        "/campaigns/analytics/steps": [
            {"step": 1, "opened": 15, "clicked": 3},
            {"step": 2, "opened": 5,  "clicked": 1},
        ],
    }
    client = httpx.Client(transport=_mock(tmap))
    out = fetch("KEY", "2026-06-01", "2026-06-30", client=client)
    steps = out["data"]["steps"]
    assert len(steps) == 2
    assert steps[0]["step"] == 1
    assert steps[0]["opened"] == 15
    assert steps[0]["clicked"] == 3


def test_fetch_steps_missing_keys_default_to_zero():
    """Step rows with missing opened/clicked keys should not raise."""
    tmap = {
        "/campaigns": {"items": [{"id": "c1", "name": "X"}]},
        "/campaigns/analytics": {},
        "/accounts/analytics": [],
        "/campaigns/analytics/steps": [{"step": 1}],  # missing opened/clicked
    }
    client = httpx.Client(transport=_mock(tmap))
    out = fetch("KEY", "2026-06-01", "2026-06-30", client=client)
    steps = out["data"]["steps"]
    assert steps[0]["opened"] == 0
    assert steps[0]["clicked"] == 0


def test_fetch_steps_aggregated_across_campaigns():
    """When multiple campaigns match, steps from all campaigns are accumulated."""
    tmap = {
        "/campaigns": {"items": [
            {"id": "c1", "name": "Upsta_V1"},
            {"id": "c2", "name": "Upsta_V2"},
        ]},
        "/campaigns/analytics": {"emails_sent_count": 50, "open_count": 10,
                                  "link_click_count": 2, "bounced_count": 1,
                                  "reply_count": 0},
        "/accounts/analytics": [],
        "/campaigns/analytics/steps": [
            {"step": 1, "opened": 10, "clicked": 2},
        ],
    }
    client = httpx.Client(transport=_mock(tmap))
    out = fetch("KEY", "2026-06-01", "2026-06-30", client=client)
    # 2 campaigns × 1 step each = 2 step rows
    assert len(out["data"]["steps"]) == 2

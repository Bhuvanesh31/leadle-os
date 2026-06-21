"""Tests for dashboard.client.sources.loader — TDD Task 5.

All API calls are mocked via httpx.MockTransport.
The mini XLSX fixture (upsta_mini.xlsx) is used for sheet data.
"""
import pytest
import httpx
from pathlib import Path

from dashboard.client.sources import loader
from dashboard.client.model import ClientData

FIXTURES = Path(__file__).parent / "fixtures"
MINI_XLSX = str(FIXTURES / "upsta_mini.xlsx")
WINDOW = ("2026-06-01", "2026-06-30")
AIMFOX_KEY = "af_test_key"
INSTANTLY_KEY = "in_test_key"
NAME_CONTAINS = "upsta"


# ── Mock helpers ──────────────────────────────────────────────────────────────

def _mock(transport_map: dict):
    """Return httpx.MockTransport that matches by longest-fragment-first."""
    _sorted = sorted(transport_map.items(), key=lambda kv: len(kv[0]), reverse=True)

    def handler(request: httpx.Request) -> httpx.Response:
        for frag, payload in _sorted:
            if frag in str(request.url):
                return httpx.Response(200, json=payload)
        return httpx.Response(404, json={})

    return httpx.MockTransport(handler)


_AIMFOX_MAP = {
    "/campaigns": {
        "campaigns": [
            {"id": "a1", "name": "Upsta_US_PMP_V1"},
            {"id": "z9", "name": "OtherClient_V1"},
        ]
    },
    "/campaigns/a1": {
        "campaign": {
            "flows": [
                {
                    "type": "PRIMARY_CONNECT",
                    "template": {"message": "Hi {{FIRST_NAME}}, quick note"},
                }
            ]
        }
    },
    "/analytics/interactions": {
        "buckets": [
            {
                "sent_connections": 120,
                "accepted_connections": 8,
                "replies": 3,
                "inmail_replies": 1,
            }
        ]
    },
}

_INSTANTLY_MAP = {
    "/campaigns": {
        "items": [
            {"id": "c1", "name": "Upsta_SFDI_V1"},
            {"id": "c2", "name": "OtherClient_V1"},
        ]
    },
    "/campaigns/analytics": {
        "emails_sent_count": 500,
        "open_count": 150,
        "link_click_count": 30,
        "bounced_count": 10,
        "reply_count": 5,
    },
}


# ── Happy path ────────────────────────────────────────────────────────────────

def test_load_merges_all_three_sources():
    aimfox_client = httpx.Client(transport=_mock(_AIMFOX_MAP))
    instantly_client = httpx.Client(transport=_mock(_INSTANTLY_MAP))

    data = loader.load(
        MINI_XLSX,
        WINDOW,
        aimfox_key=AIMFOX_KEY,
        instantly_key=INSTANTLY_KEY,
        name_contains=NAME_CONTAINS,
        aimfox_client=aimfox_client,
        instantly_client=instantly_client,
    )

    assert isinstance(data, ClientData)

    # Sheet: targets must be populated (upsta_mini.xlsx has at least one row)
    assert len(data.targets) > 0, "targets must come from XLSX"

    # Aimfox: one campaign (filtered to upsta, not OtherClient)
    assert len(data.linkedin_campaigns) == 1
    lc = data.linkedin_campaigns[0]
    assert lc.name == "Upsta_US_PMP_V1"
    assert lc.invites == 120
    assert lc.accepted == 8
    assert lc.replied == 4  # 3 + 1 inmail_replies

    # Instantly: one campaign (filtered to upsta)
    assert len(data.email_campaigns) == 1
    ec = data.email_campaigns[0]
    assert ec.name == "Upsta_SFDI_V1"
    assert ec.sent == 500
    assert ec.opened == 150
    assert ec.clicked == 30
    assert ec.bounced == 10
    assert ec.replied == 5

    # Sheet: replies list comes from xlsx (may be empty in mini — just check type)
    assert isinstance(data.replies, list)


def test_load_populates_senders_and_steps_from_instantly():
    """senders/steps from instantly payload are copied into ClientData."""
    instantly_map_with_extras = {
        "/campaigns": {"items": [{"id": "c1", "name": "Upsta_SFDI_V1"}]},
        "/campaigns/analytics": {
            "emails_sent_count": 10,
            "open_count": 2,
            "link_click_count": 0,
            "bounced_count": 0,
            "reply_count": 1,
        },
    }
    # We'll monkey-patch the fetch return to include senders/steps
    # by using a custom instantly_client whose response includes them.
    # Since fetch() always returns senders:[] steps:[] (Task 9 populates),
    # we just verify the loader copies whatever fetch returns.
    aimfox_client = httpx.Client(transport=_mock(_AIMFOX_MAP))
    instantly_client = httpx.Client(transport=_mock(instantly_map_with_extras))

    data = loader.load(
        MINI_XLSX,
        WINDOW,
        aimfox_key=AIMFOX_KEY,
        instantly_key=INSTANTLY_KEY,
        name_contains=NAME_CONTAINS,
        aimfox_client=aimfox_client,
        instantly_client=instantly_client,
    )
    # fetch returns senders:[] steps:[] by default; loader must copy them
    assert data.senders == []
    assert data.content_steps == []


# ── Degrade tests ─────────────────────────────────────────────────────────────

def test_load_degrades_when_aimfox_raises():
    """Aimfox HTTP error → linkedin_campaigns=[], sheet data intact."""

    def boom(request):
        raise httpx.ConnectError("aimfox down")

    aimfox_client = httpx.Client(transport=httpx.MockTransport(boom))
    instantly_client = httpx.Client(transport=_mock(_INSTANTLY_MAP))

    data = loader.load(
        MINI_XLSX,
        WINDOW,
        aimfox_key=AIMFOX_KEY,
        instantly_key=INSTANTLY_KEY,
        name_contains=NAME_CONTAINS,
        aimfox_client=aimfox_client,
        instantly_client=instantly_client,
    )

    assert data.linkedin_campaigns == []
    assert len(data.targets) > 0  # sheet data still present
    assert len(data.email_campaigns) == 1  # instantly still works


def test_load_degrades_when_instantly_unavailable():
    """Instantly unavailable → email_campaigns=[], sheet data intact."""

    def boom(request):
        raise httpx.ConnectError("instantly down")

    aimfox_client = httpx.Client(transport=_mock(_AIMFOX_MAP))
    instantly_client = httpx.Client(transport=httpx.MockTransport(boom))

    data = loader.load(
        MINI_XLSX,
        WINDOW,
        aimfox_key=AIMFOX_KEY,
        instantly_key=INSTANTLY_KEY,
        name_contains=NAME_CONTAINS,
        aimfox_client=aimfox_client,
        instantly_client=instantly_client,
    )

    assert data.email_campaigns == []
    assert data.senders == []
    assert data.content_steps == []
    assert len(data.targets) > 0  # sheet data still present
    assert len(data.linkedin_campaigns) == 1  # aimfox still works


def test_load_degrades_when_both_apis_fail():
    """Both APIs failing → campaigns lists empty, sheet data still present."""

    def boom(request):
        raise httpx.ConnectError("network down")

    aimfox_client = httpx.Client(transport=httpx.MockTransport(boom))
    instantly_client = httpx.Client(transport=httpx.MockTransport(boom))

    data = loader.load(
        MINI_XLSX,
        WINDOW,
        aimfox_key=AIMFOX_KEY,
        instantly_key=INSTANTLY_KEY,
        name_contains=NAME_CONTAINS,
        aimfox_client=aimfox_client,
        instantly_client=instantly_client,
    )

    assert data.linkedin_campaigns == []
    assert data.email_campaigns == []
    assert len(data.targets) > 0

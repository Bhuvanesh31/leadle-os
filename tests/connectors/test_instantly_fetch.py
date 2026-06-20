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

# tests/client/test_aimfox_source.py
import httpx

from dashboard.client.sources import aimfox_source


def _mock(m):
    # Sort by fragment length descending so more-specific paths win
    # (e.g. /campaigns/a1 matches before /campaigns).
    _sorted = sorted(m.items(), key=lambda kv: len(kv[0]), reverse=True)
    def h(req):
        for frag, payload in _sorted:
            if frag in str(req.url):
                return httpx.Response(200, json=payload)
        return httpx.Response(404, json={})
    return httpx.MockTransport(h)

def test_read_builds_campaign_with_variant_and_metrics():
    m = {
        "/campaigns": {"campaigns": [{"id": "a1", "name": "Upsta_US_PMP_V1"},
                                     {"id": "z9", "name": "Other_V1"}]},
        "/campaigns/a1": {"campaign": {"flows": [
            {"type": "PRIMARY_CONNECT", "template": {"message": "Hi {{FIRST_NAME}}, founder"}}]}},
        "/analytics/interactions": {"buckets": [
            {"sent_connections": 100, "accepted_connections": 5, "replies": 2, "inmail_replies": 1},
            {"sent_connections": 88, "accepted_connections": 4, "replies": 0, "inmail_replies": 0}]},
    }
    client = httpx.Client(transport=_mock(m))
    camps = aimfox_source.read("KEY", ("2026-05-01", "2026-07-01"),
                               name_contains="upsta", client=client)
    assert len(camps) == 1
    c = camps[0]
    assert c.name == "Upsta_US_PMP_V1"
    assert c.invites == 188 and c.accepted == 9 and c.replied == 3
    assert c.variant_message.startswith("Hi")

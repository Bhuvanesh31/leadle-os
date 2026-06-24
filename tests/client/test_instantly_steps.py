"""Step rows must carry their campaign name + step copy (subject/body)."""
import httpx
from connectors.instantly import fetch


def _client(routes):
    _prefix = "/api/v2"

    def handler(request):
        path = request.url.path
        if path.startswith(_prefix):
            path = path[len(_prefix):]
        return routes[path](request)

    return httpx.Client(transport=httpx.MockTransport(handler), base_url=fetch._BASE_URL)


def test_steps_carry_campaign_name_and_copy():
    camps = [{"id": "c1", "name": "UPSTA-US-Founders"}]
    routes = {
        "/campaigns/analytics/steps": lambda r: httpx.Response(
            200, json=[{"step": 1, "sent": 100, "opened": 40, "clicked": 5}]
        ),
        "/campaigns/c1": lambda r: httpx.Response(
            200, json={"sequences": [{"steps": [
                {"variants": [{"subject": "Quick question", "body": "Hi {{first}}, are you the right person for X? " * 5}]}
            ]}]},
        ),
    }
    steps = fetch._campaign_steps(_client(routes), camps)
    assert steps[0]["campaign"] == "UPSTA-US-Founders"
    assert steps[0]["subject"] == "Quick question"
    assert steps[0]["body_preview"].startswith("Hi {{first}}")
    assert len(steps[0]["body_preview"]) <= 120


def test_steps_degrade_when_copy_missing():
    camps = [{"id": "c1", "name": "UPSTA-US-Founders"}]
    routes = {
        "/campaigns/analytics/steps": lambda r: httpx.Response(
            200, json=[{"step": 2, "sent": 50, "opened": 10, "clicked": 0}]
        ),
        "/campaigns/c1": lambda r: httpx.Response(404, json={}),
    }
    steps = fetch._campaign_steps(_client(routes), camps)
    assert steps[0]["campaign"] == "UPSTA-US-Founders"
    assert steps[0]["subject"] == ""
    assert steps[0]["body_preview"] == ""

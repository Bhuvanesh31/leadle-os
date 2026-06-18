import asyncio
from dashboard.client.agents import narrative, actions


class _BoomClient:
    """Stand-in AsyncAnthropic whose .messages.create raises -> run_agent degrades."""
    class messages:
        @staticmethod
        async def create(*a, **k):
            raise RuntimeError("no api in test")


def test_narrative_falls_back_without_api():
    metrics = {"kpis": {"emails_sent": 224, "opened": 129, "meetings": 1,
                        "positive_replies": 2, "accepted": 42, "invites": 239}}
    out = asyncio.run(narrative.synthesize(metrics, audience="client",
                                           client="UPSTA", client_obj=_BoomClient()))
    assert out["degraded"] is True
    assert isinstance(out["narrative"], str) and out["narrative"]


def test_actions_falls_back_without_api():
    metrics = {"kpis": {"bounce_rate": 0.07, "emails_sent": 224}}
    out = asyncio.run(actions.synthesize(metrics, client="UPSTA",
                                         client_obj=_BoomClient()))
    assert out["degraded"] is True
    assert isinstance(out["actions"], list)

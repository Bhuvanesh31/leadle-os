"""Task 7 — KPI + scorecard tests against campaign-level ClientData.

Accumulates through Tasks 7-11. Each task section is clearly delimited.
"""
import yaml
from pathlib import Path
from datetime import datetime
from dashboard.client import compute
from dashboard.client.model import (
    ClientData, EmailCampaign, LinkedInCampaign, ReplyRecord,
)

ROOT = Path(__file__).resolve().parents[2]
RUBRIC = yaml.safe_load((ROOT / "config/client_report_rubric.yaml").read_text())


def _data():
    return ClientData(
        email_campaigns=[
            EmailCampaign("Upsta_SFDI_V1", 414, 140, 42, 41, 0),
            EmailCampaign("Upsta_PMP_V1",  598, 215,  0, 44, 0),
        ],
        linkedin_campaigns=[
            LinkedInCampaign("Upsta_US_PMP_V1", 188, 9, 3, "Hi founder"),
            LinkedInCampaign("Upsta_Recon_V3",   46, 0, 0, "Hi recon"),
        ],
        replies=[
            ReplyRecord("linkedin", "Upsta_US_PMP_V1", "neutral",   "Donna", None),
            ReplyRecord("linkedin", "Upsta_US_PMP_V1", "untagged",  "",      None),
        ],
    )


# ---------------------------------------------------------------------------
# Task 7: kpis() + scorecard()
# ---------------------------------------------------------------------------

def test_kpis_aggregate_and_leads_equal_positive():
    k = compute.kpis(_data(), RUBRIC)
    # email aggregates
    assert k["emails_sent"] == 1012          # 414 + 598
    assert k["bounced"] == 85               # 41 + 44
    assert round(k["bounce_rate"], 4) == round(85 / 1012, 4)  # event-based
    assert k["opened"] == 355               # 140 + 215
    assert k["clicked"] == 42              # 42 + 0
    delivered = 1012 - 85
    assert k["delivered"] == delivered
    assert round(k["open_rate"], 6) == round(355 / delivered, 6)
    # linkedin aggregates
    assert k["invites"] == 234              # 188 + 46
    assert k["accepted"] == 9
    # replies from ReplyRecord list
    assert k["li_replies"] == 2             # both channel=="linkedin"
    assert k["email_replies"] == 0
    assert k["total_replies"] == 2
    assert k["positive_replies"] == 0       # no "positive" sentiment in fixture
    assert k["neutral_replies"] == 1
    assert k["negative_replies"] == 0
    # leads == positive_replies (invariant)
    assert k["leads"] == k["positive_replies"]


def test_kpis_meetings_counts_warm_leads_with_meeting_status():
    """meetings should still count from warm_leads if present; 0 when absent."""
    k = compute.kpis(_data(), RUBRIC)
    assert k["meetings"] == 0  # no warm_leads in _data()


def test_kpis_zero_guard_division():
    """Empty data must not raise ZeroDivisionError."""
    empty = ClientData()
    k = compute.kpis(empty, RUBRIC)
    assert k["open_rate"] == 0.0
    assert k["bounce_rate"] == 0.0
    assert k["accept_rate"] == 0.0


def test_scorecard_positive_zero_emails_grades_F():
    """With emails_sent==0 but positive_replies>0, positive rate must be 0.0 (not 1.0),
    and its grade must be 'F' — proving _rate() is used instead of max(emails_sent, 1)."""
    from dashboard.client.model import ReplyRecord
    # No email campaigns (emails_sent=0), but inject a positive reply via the legacy path
    # by directly constructing a kpis dict to isolate scorecard's zero-guard.
    k_zeroemails = {
        "emails_sent": 0,
        "fresh_prospects": 0,
        "opened": 0,
        "clicked": 0,
        "bounced": 0,
        "delivered": 0,
        "open_rate": 0.0,
        "click_rate": 0.0,
        "bounce_rate": 0.0,
        "invites": 0,
        "accepted": 0,
        "accept_rate": 0.0,
        "li_replies": 0,
        "email_replies": 0,
        "total_replies": 1,
        "positive_replies": 1,  # positive reply exists, but no emails were sent
        "neutral_replies": 0,
        "negative_replies": 0,
        "leads": 1,
        "meetings": 0,
    }
    sc = compute.scorecard(k_zeroemails, RUBRIC)
    # positive = _rate(1, 0) = 0.0, not 1.0 — zero emails means zero positive rate
    assert sc["grades"]["positive"] == "F", (
        f"Expected 'F' but got '{sc['grades']['positive']}'; "
        "scorecard() must use _rate() not max(emails_sent, 1)"
    )


def test_scorecard_open_grade_A():
    k = compute.kpis(_data(), RUBRIC)
    sc = compute.scorecard(k, RUBRIC)
    # open_rate = 355 / 927 ≈ 0.383 → >=0.20 band = A
    assert sc["grades"]["open_rate"] == "A"


def test_scorecard_has_required_keys():
    k = compute.kpis(_data(), RUBRIC)
    sc = compute.scorecard(k, RUBRIC)
    assert "grades" in sc and "overall" in sc
    for metric in ("open_rate", "reply_rate", "positive", "bounce_rate", "accept_rate"):
        assert metric in sc["grades"], f"missing grade for {metric}"


def test_scorecard_overall_is_weakest():
    """overall must equal the weakest (lowest) grade across all graded metrics."""
    k = compute.kpis(_data(), RUBRIC)
    sc = compute.scorecard(k, RUBRIC)
    order = "ABCDF"
    worst = max(sc["grades"].values(), key=lambda g: order.index(g))
    assert sc["overall"] == worst

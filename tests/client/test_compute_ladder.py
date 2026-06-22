# tests/client/test_compute_ladder.py
from pathlib import Path

import yaml

from dashboard.client import compute
from dashboard.client.model import (
    ClientData,
    EmailCampaign,
    LinkedInCampaign,
    ReplyRecord,
    WarmLead,
)

_CFG = Path(__file__).resolve().parents[2] / "config"


def _data():
    return ClientData(
        email_campaigns=[
            EmailCampaign(name="C1", sent=2, opened=1, clicked=0, bounced=0, replied=0)
        ],
        linkedin_campaigns=[LinkedInCampaign(name="L1", invites=10, accepted=3, replied=1)],
        warm_leads=[
            WarmLead(
                channel="LinkedIn",
                account="UPSTA",
                response_date="2026-06-01",
                status="Meeting booked",
                response_text="Sure let's connect.",
                linkedin_url="https://linkedin.com/in/danalin",
                name="Dana Lin",
                title="VP Sales",
                company="Acme",
                company_url="https://acme.com",
                location="New York",
            ),
            WarmLead(
                channel="Email",
                account="UPSTA",
                response_date="2026-06-02",
                status="Long follow up",
                response_text="Will check back.",
                linkedin_url="https://linkedin.com/in/salmanbari",
                name="Salman Bari",
                title="Director",
                company="BetaCo",
                company_url="https://betaco.com",
                location="London",
            ),
        ],
    )


def _rubric():
    return yaml.safe_load((_CFG / "client_report_rubric.yaml").read_text())


def test_lead_ladder_hot_from_tracker():
    lad = compute.lead_ladder(_data(), _rubric())
    hot_names = {h["name"] for h in lad["hot"]}
    assert "Dana Lin" in hot_names  # "Meeting booked" -> Hot
    assert "Salman Bari" in hot_names  # "Long follow up" -> Hot (positive)


def test_compute_all_assembles_bag():
    bag = compute.compute_all(_data(), _rubric())
    assert set(bag) >= {
        "kpis",
        "scorecard",
        "campaigns",
        "content",
        "variants",
        "senders",
        "deliverability",
        "timing",
        "reach",
        "leads",
    }
    assert bag["kpis"]["emails_sent"] == 2


def test_positive_reply_is_hot_lead():
    data = ClientData(
        replies=[
            ReplyRecord(channel="email", campaign="C1", sentiment="positive", name="Jane Doe")
        ],
    )
    lad = compute.lead_ladder(data, _rubric())
    hot_names = [h["name"] for h in lad["hot"]]
    assert "Jane Doe" in hot_names
    assert lad["positive_leads"] == 1


def test_leads_count_equals_positive_replies():
    data = ClientData(
        email_campaigns=[EmailCampaign(name="C1", sent=10)],
        replies=[
            ReplyRecord(channel="email", campaign="C1", sentiment="positive", name="Alice"),
            ReplyRecord(channel="email", campaign="C1", sentiment="positive", name="Bob"),
            ReplyRecord(channel="email", campaign="C1", sentiment="neutral", name="Charlie"),
        ],
    )
    rubric = _rubric()
    lad = compute.lead_ladder(data, rubric)
    k = compute.kpis(data, rubric)
    assert lad["positive_leads"] == 2
    assert k["leads"] == 2
